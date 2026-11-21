import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
from unittest.mock import patch
from regression_support import emit_result
from asurada.review_capture import project_capture_cached
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review
from asurada.review_command import execute_review, review_summary


def run():
    checks={};scripts=Path(__file__).resolve().parent
    fixture=scripts.parent/'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    with TemporaryDirectory() as temp:
        root=Path(temp);capture=root/'capture.jsonl';capture.write_bytes(fixture.read_bytes())
        destination=root/'projection.jsonl';manifest=root/'projection.json'
        def project():return project_capture_cached(capture,destination,manifest,context=TaskContext.start('projection',2000))
        report=project();before=destination.read_bytes()
        with patch('asurada.review_capture.project_capture',side_effect=AssertionError('must not decode again')):
            checks['published_projection_reused']=project()==report
        changed=dict(report,version='old-projection');manifest.write_text(json.dumps(changed))
        try:project();checks['old_projection_version_rejected']=False
        except ValueError as e:checks['old_projection_version_rejected']=str(e)=='capture_projection_version_conflict'
        manifest.write_text(json.dumps(report))
        capture.write_bytes(capture.read_bytes()+b'\n')
        try:project();checks['different_capture_cannot_overwrite_evidence']=False
        except ValueError as e:checks['different_capture_cannot_overwrite_evidence']=str(e)=='capture_projection_input_conflict' and destination.read_bytes()==before
        capture.write_bytes(fixture.read_bytes());destination.write_bytes(before+b'\n')
        try:project();checks['corrupt_projection_rejected']=False
        except ValueError as e:checks['corrupt_projection_rejected']=str(e)=='capture_projection_integrity_failure'
        destination.write_bytes(before);manifest.unlink()
        checks['uncommitted_projection_rebuilt']=project()['projection_sha256']==report['projection_sha256']
        source=root/'session.jsonl';source.write_text(json.dumps(dict(session_uid='s',lap_number=2,track='Suzuka',source_timestamp_ms=1,raw={'last_lap_time_ms':100000})))
        store=WorkflowStore(root/'tasks.db')
        run_session_review(store,task_id='cancelled',source=source)
        # Represent an interrupted task with no committed steps, then exercise
        # the real separate-process cancellation command and review CLI.
        with store._connect() as db:
            db.execute("UPDATE tasks SET status='queued',results='[]',attempts=0 WHERE id='cancelled'")
        command=[sys.executable,str(scripts/'review_task.py'),'--database',str(store.path),'--task-id','cancelled','cancel']
        process=subprocess.run(command,capture_output=True,text=True)
        checks['cancel_command_persists_state']=process.returncode==0 and json.loads(process.stdout)['status']=='cancelled'
        command=[sys.executable,str(scripts/'run_session_review.py'),'--database',str(store.path),'--task-id','cancelled','--source',str(source)]
        process=subprocess.run(command,capture_output=True,text=True)
        checks['cancelled_cli_is_not_success']=process.returncode==2 and json.loads(process.stdout)['status']=='cancelled' and not process.stderr
        store.create('expired',{'steps':[]},timeout_s=0)
        with store._connect() as db:db.execute("UPDATE tasks SET status='expired' WHERE id='expired'")
        result,code=execute_review(lambda:store.get('expired'),store=store,task_id='expired')
        checks['expired_empty_checkpoint_summary']=code==2 and review_summary(result)=={'status':'expired'}
        run_session_review(store,task_id='complete',source=source)
        command=[sys.executable,str(scripts/'run_session_review.py'),'--database',str(store.path),'--task-id','complete','--source',str(source)]
        process=subprocess.run(command,capture_output=True,text=True)
        checks['completed_cli_success']=process.returncode==0 and json.loads(process.stdout)['status']=='completed'
        source.write_text(source.read_text()+'\n')
        process=subprocess.run(command,capture_output=True,text=True);failure=json.loads(process.stdout)
        checks['conflict_does_not_relabel_old_success']=process.returncode==1 and failure['status']=='invocation_failed' and failure['task_status']=='completed'
        raw_output=root/'raw'
        raw_success=[sys.executable,str(scripts/'review_raw_capture.py'),'--capture',str(capture),'--output',str(raw_output),'--task-id','raw']
        first=subprocess.run(raw_success,capture_output=True,text=True)
        manifest_before=(raw_output/'projection.json').stat().st_mtime_ns
        second=subprocess.run(raw_success,capture_output=True,text=True)
        checks['raw_cli_success_and_cached_resume']=first.returncode==second.returncode==0 and json.loads(second.stdout)['status']=='completed' and (raw_output/'projection.json').stat().st_mtime_ns==manifest_before
        raw_store=WorkflowStore(raw_output/'review.db')
        with raw_store._connect() as db:db.execute("UPDATE tasks SET status='cancelled',results='[]' WHERE id='raw'")
        cancelled=subprocess.run(raw_success,capture_output=True,text=True)
        checks['raw_cancelled_empty_checkpoint_no_index_error']=cancelled.returncode==2 and json.loads(cancelled.stdout)['status']=='cancelled' and not cancelled.stderr
        raw_command=[sys.executable,str(scripts/'review_raw_capture.py'),'--capture',str(root/'missing.jsonl'),'--output',str(root/'failed-raw'),'--task-id','missing']
        process=subprocess.run(raw_command,capture_output=True,text=True)
        checks['projection_failure_machine_readable']=process.returncode==1 and json.loads(process.stdout)['status']=='invocation_failed' and json.loads((root/'failed-raw/review.json').read_text())['error']['type']=='FileNotFoundError'
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

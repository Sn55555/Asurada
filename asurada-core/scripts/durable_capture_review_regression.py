from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch
from regression_support import emit_result
from asurada.capture_ingest import CaptureJsonlSource
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore
from asurada.review_command import execute_review
import asurada.session_review_workflow as workflow


def run():
    checks={}
    fixture=Path(__file__).resolve().parents[1]/'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    with TemporaryDirectory() as temp:
        root=Path(temp);store=WorkflowStore(root/'tasks.db')
        def review(task,directory,timeout=3):
            return run_session_review(store,task_id=task,source=fixture,capture_directory=root/directory,timeout_s=timeout)
        with patch.object(workflow,'review_segments',side_effect=RuntimeError('injected analysis failure')):
            try:review('restore','restore');checks['projection_checkpoint_before_analysis_failure']=False
            except RuntimeError:
                state=store.get('restore')
                checks['projection_checkpoint_before_analysis_failure']=state['status']=='failed' and state['results'][0]['step']=='project_capture'
        expires=store.get('restore')['expires']
        with patch.object(workflow,'project_capture_cached',side_effect=AssertionError('committed projection must not rerun')):
            restored=review('restore','restore')
        report=restored['results'][-1]['result']
        checks['resume_skips_committed_projection']=restored['status']=='completed' and len(restored['results'])==7
        checks['resume_retains_original_deadline']=restored['expires']==expires
        checks['report_links_raw_and_projected_hash']=report['capture_provenance']['projection_sha256']==report['source_sha256'] and bool(report['capture_provenance']['capture_sha256'])
        entered,release,finished=Event(),Event(),Event()
        def paused_source(path):
            try:
                for packet in CaptureJsonlSource(path):
                    entered.set();release.wait(2)
                    yield packet
            finally:finished.set()
        results=[]
        with patch('asurada.review_capture.CaptureJsonlSource',side_effect=paused_source):
            thread=Thread(target=lambda:results.append(review('cancel','cancel')))
            thread.start();assert entered.wait(1)
            WorkflowStore(store.path).cancel('cancel')
            thread.join(.5)
            checks['projection_cancel_returns_without_waiting_for_input']=not thread.is_alive() and results[0]['status']=='cancelled'
            checks['cancelled_projection_has_no_checkpoint']=not store.get('cancel')['results']
            release.set();assert finished.wait(1);thread.join(1)
        checks['cancelled_projection_not_published']=not (root/'cancel/projection.json').exists() and not (root/'cancel/review-snapshots.jsonl').exists()
        entered.clear();release.clear();finished.clear()
        with patch('asurada.review_capture.CaptureJsonlSource',side_effect=paused_source):
            try:
                result,code=execute_review(lambda:review('timeout','timeout',.1),store=store,task_id='timeout')
                checks['projection_uses_task_deadline']=entered.is_set() and store.get('timeout')['status']=='expired' and code==2 and result['status']=='expired'
            finally:release.set();assert finished.wait(1)
        checks['expired_projection_not_committed']=not store.get('timeout')['results'] and not (root/'timeout/projection.json').exists()
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

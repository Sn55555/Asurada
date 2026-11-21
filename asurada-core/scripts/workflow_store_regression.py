from pathlib import Path
from tempfile import TemporaryDirectory
import json
from regression_support import emit_result
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review


def run():
    with TemporaryDirectory() as directory:
        root=Path(directory);store=WorkflowStore(root/'tasks.db');calls=[]
        store.create('recover',{'steps':['one','two']})
        def one(*args):calls.append('one');return 1
        def fail(*args):raise RuntimeError('injected interruption')
        try:store.run('recover',(('one',one),('two',fail)))
        except RuntimeError:pass
        checks={'checkpoint_saved':len(store.get('recover')['results'])==1}
        store=WorkflowStore(root/'tasks.db')
        result=store.run('recover',(('one',one),('two',lambda *args:2)))
        checks['resumes_without_repeating_committed_step']=result['status']=='completed' and calls==['one'] and result['attempts']==3
        store.run('recover',(('one',one),('two',fail)))
        checks['completed_idempotent']=calls==['one']
        try:store.create('recover',{'steps':['different']});checks['input_bound']=False
        except ValueError:checks['input_bound']=True
        store.create('cancel',{'steps':['one']});store.cancel('cancel')
        checks['cancelled_not_run']=store.run('cancel',(('one',one),))['status']=='cancelled' and calls==['one']
        store.create('expired',{'steps':['one']},timeout_s=0)
        try:store.run('expired',(('one',one),))
        except TimeoutError:pass
        checks['expiry_persisted']=store.get('expired')['status']=='expired'
        source=root/'session.jsonl'
        rows=[{'session_uid':'s','session_epoch':0,'lap_number':lap+1,'track':'Suzuka','source_timestamp_ms':lap*1000,'raw':{'last_lap_time_ms':duration}} for lap,duration in [(1,100000),(2,99000),(3,98500)]]
        source.write_text('\n'.join(json.dumps(row) for row in rows))
        report=run_session_review(store,task_id='review',source=source)
        final=report['results'][-1]['result']
        checks['review_pipeline']=report['status']=='completed' and final['comparisons'][0]['change_ms']==-1500 and final['training_recommendation'] is None
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())

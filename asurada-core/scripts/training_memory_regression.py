from pathlib import Path
from tempfile import TemporaryDirectory
import json
from regression_support import emit_result
from asurada.training_memory import TrainingMemory
from asurada.workflow_store import WorkflowStore
from asurada.session_review_workflow import run_session_review


def run():
    checks={}
    with TemporaryDirectory() as temp:
        root=Path(temp);now=[1000.];memory=TrainingMemory(root/'memory.db',clock=lambda:now[0])
        def put(key,time_ms):
            return memory.put(driver='one',kind='session_fact',key=key,value={'track':'Suzuka','lap':int(key),'time_ms':time_ms},evidence=[{'source_sha256':'fixture'}],ttl_s=10,session_uid='s',epoch=0)
        first,last=put('1',100000),put('2',99000)
        checks['driver_isolated']=not memory.query(driver='two',kind='session_fact',session_uid='s',epoch=0)
        checks['epoch_isolated']=not memory.query(driver='one',kind='session_fact',session_uid='s',epoch=1)
        now[0]=1005;put('1',100000)
        facts=memory.query(driver='one',kind='session_fact',session_uid='s',epoch=0)
        checks['retry_does_not_duplicate_or_extend_ttl']=len(facts)==2 and all(item['expires_at']==1010 for item in facts)
        value={'track':'Suzuka','baseline_time_ms':100000,'observed_time_ms':99000,'delta_ms':-1000}
        args=dict(driver='one',kind='verified_performance',key='comparison',value=value,evidence=[{'source':'two official laps'}],ttl_s=100,verification={'method':'official_lap_delta_v1','evidence_ids':[first,last]})
        memory.put(**args)
        checks['verified_performance_separate']=len(memory.query(driver='one',kind='verified_performance'))==1
        try:memory.put(**dict(args,key='wrong',value=dict(value,delta_ms=-2000)));checks['invented_delta_rejected']=False
        except ValueError:checks['invented_delta_rejected']=True
        try:memory.put(driver='one',kind='user_preference',key='voice',value='short',evidence=[{'origin':'model_guess'}],ttl_s=100);checks['inferred_preference_rejected']=False
        except ValueError:checks['inferred_preference_rejected']=True
        now[0]=1011
        checks['expired_facts_not_retrieved']=not memory.query(driver='one',kind='session_fact',session_uid='s',epoch=0)
        checks['expired_cleanup']=memory.purge_expired()==2
        source=root/'session.jsonl'
        source.write_text('\n'.join(json.dumps({'session_uid':'race','lap_number':lap+1,'session_epoch':3,'track':'Suzuka','source_timestamp_ms':lap*1000,'raw':{'last_lap_time_ms':duration}}) for lap,duration in [(1,100000),(2,99000),(3,98500)]))
        store=WorkflowStore(root/'tasks.db')
        result=run_session_review(store,task_id='review',source=source,driver_id='driver-a',memory=memory)
        again=run_session_review(store,task_id='review',source=source,driver_id='driver-a',memory=memory)
        facts=memory.query(driver='driver-a',kind='session_fact',session_uid='race',epoch=3)
        checks['review_persists_scoped_evidence']=len(facts)==3 and all(f['evidence'][0]['source_sha256'] for f in facts)
        checks['workflow_retry_idempotent']=again['results']==result['results'] and len(result['results'][-1]['result']['memory']['memory_ids'])==3
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

import tempfile
import json
import subprocess
import sys
from pathlib import Path
from asurada.capability_executor import CapabilityExecutor
from asurada.workflow_store import WorkflowStore
from asurada.task_runtime import TaskContext
from asurada.capabilities.history import ReviewScope
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={};state=make_state()
    with tempfile.TemporaryDirectory() as tmp:
        store=WorkflowStore(Path(tmp)/'reviews.sqlite3')
        laps=[{'session_uid':state.session_uid,'epoch':state.session_epoch,'track':state.track,'lap':n,'time_ms':t,'evidence':{'source_sha256':'fixture-hash','source_timestamp_ms':state.source_timestamp_ms}} for n,t in [(1,90000),(2,89750),(3,89900)]]
        store.create('review',{'driver_id':'driver','steps':['index_official_laps']})
        store.run('review',(('index_official_laps',lambda request,results,context:laps),))
        def execute(arguments,driver='driver',permissions=frozenset({'read_session_history'})):
            runner=CapabilityExecutor(context=TaskContext.start('tools',1000),permissions=permissions,historical=True,review_store=store,driver_id=driver)
            return runner.execute('compare_review_laps',state=state,arguments=arguments)
        args={'review_task_id':'review','lap_numbers':[1,2]}
        result=execute(args)
        checks['structured_values_and_evidence']=result['data']['delta_ms']==-250 and result['data']['unit']=='ms' and result['data']['evidence'][1]['lap']==2 and 'speak_text' not in result
        scope=ReviewScope(state.session_uid,state.session_epoch,state.track)
        runner=CapabilityExecutor(context=TaskContext.start('scope',1000),permissions=frozenset({'read_session_history'}),historical=True,review_store=store,driver_id='driver')
        scoped=runner.execute('compare_review_laps',state=scope,arguments=args)
        checks['scope_is_not_fabricated_snapshot']=scoped['snapshot_id'] is None and scoped['scope_id']==scope.identity() and scoped['data']==result['data']
        try:runner.execute('current_strategy',state=scope);checks['scope_cannot_answer_live_facts']=False
        except ValueError:checks['scope_cannot_answer_live_facts']=True
        projection=Path(tmp)/'scope.json'
        projection.write_text(json.dumps({'session_uid':state.session_uid,'session_epoch':state.session_epoch,'track':state.track}))
        command=[sys.executable,str(Path(__file__).with_name('query_snapshot_tool.py')),'--snapshot',str(projection),'--capability','compare_review_laps','--historical','--review-store',str(store.path),'--driver-id','driver','--arguments-json',json.dumps(args)]
        process=subprocess.run(command,capture_output=True,text=True,timeout=5)
        checks['minimal_projection_cli']=process.returncode==0 and json.loads(process.stdout)[0]['data']['delta_ms']==-250
        for name,kwargs in [('owner',{'driver':'other'}),('permission',{'permissions':frozenset()})]:
            try:execute(args,**kwargs);checks[name]=False
            except PermissionError:checks[name]=True
        for name,numbers in [('missing',[1,4]),('duplicate',[1,1]),('boolean',[True,2]),('empty',[])]:
            try:execute({**args,'lap_numbers':numbers});checks[name]=False
            except ValueError:checks[name]=True
        state.session_epoch+=1
        try:execute(args);checks['epoch_isolated']=False
        except ValueError:checks['epoch_isolated']=True
        state.session_epoch-=1
        store.create('pending',{'driver_id':'driver','steps':['index_official_laps']})
        try:execute({**args,'review_task_id':'pending'});checks['incomplete_rejected']=False
        except ValueError:checks['incomplete_rejected']=True
    return {'passed':all(checks.values()),'checks':checks,'scope':'actual SQLite checkpoint and executor; fixture lap facts, not full voice tool loop'}


if __name__=='__main__':emit_result(run())

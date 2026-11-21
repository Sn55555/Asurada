import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from asurada.analysis_agent import ReviewAnalysisAgent
from asurada.capability_executor import CapabilityExecutor
from asurada.capabilities.history import ReviewScope
from asurada.task_runtime import TaskContext
from asurada.workflow_store import WorkflowStore
from regression_support import emit_result


def run():
    checks={};scope=ReviewScope('session',0,'Shanghai')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);store=WorkflowStore(root/'review.db')
        laps=[{'session_uid':'session','epoch':0,'track':'Shanghai','lap':n,'time_ms':t,'evidence':{'source_sha256':'fixture'}} for n,t in [(1,100000),(2,99000)]]
        store.create('review',{'driver_id':'driver','steps':['index_official_laps']})
        store.run('review',(('index_official_laps',lambda r,s,c:laps),))
        call={'action':'call','tool':'compare_review_laps','arguments':{'review_task_id':'review','lap_numbers':[1,2]}}
        finish={'action':'finish','result_ids':['result-1']}
        def execute(decisions,**options):
            seq=iter(decisions)
            planner=SimpleNamespace(next_step=lambda payload,context:next(seq))
            executor=CapabilityExecutor(context=TaskContext.start('analysis',1000),permissions=frozenset({'read_session_history'}),historical=True,review_store=store,driver_id='driver')
            return ReviewAnalysisAgent(planner=planner,executor=executor,**options).run(question='compare two laps',scope=scope,review_task_id='review')
        result=execute([call,finish])
        checks['executes_and_selects_evidence']=result['status']=='completed' and result['selected_results'][0]['data']['delta_ms']==-1000
        checks['renders_grounded_lap_answer']='第 2 圈比第 1 圈快 1.000 秒' in result['answer']['text'] and result['answer']['blocks'][0]['evidence'][0]['source_sha256']=='fixture'
        checks['unknown_reference_rejected']=execute([{'action':'finish','result_ids':['invented']}])['status']=='failed'
        checks['no_write_tool']=execute([{**call,'tool':'stop'}])['status']=='failed'
        checks['no_other_review']=execute([{**call,'arguments':{**call['arguments'],'review_task_id':'other'}}])['status']=='failed'
        checks['bounded_model_calls']=execute([call],max_model_calls=1)['status']=='budget_exhausted'
        checks['bounded_tool_calls']=execute([call,call],max_tool_calls=1)['status']=='failed'
        checks['empty_completion_is_not_success']=execute([{'action':'finish','result_ids':[]}])['status']=='insufficient_data'
        invalid={**call,'arguments':{**call['arguments'],'lap_numbers':[1,9]}}
        repaired=execute([invalid,call,{'action':'finish','result_ids':['result-2']}])
        checks['observes_failure_and_recovers']=repaired['status']=='completed' and repaired['observations'][0]['status']=='failed'
        checks['failed_result_not_selectable']=execute([invalid,finish])['status']=='failed'
        planner_file=root/'planner.py'
        planner_file.write_text('import json,sys\np=json.load(sys.stdin)\nprint(json.dumps('+repr(call)+' if not p["observations"] else '+repr(finish)+'))\n')
        scope_file=root/'scope.json';scope_file.write_text(json.dumps({'session_uid':'session','session_epoch':0,'track':'Shanghai'}))
        output=root/'analysis.json'
        command=[sys.executable,str(Path(__file__).with_name('run_review_analysis.py')),'--question','compare two laps','--review-task-id','review','--driver-id','driver','--planner-command',shlex.join([sys.executable,str(planner_file)]),'--review-store',str(store.path),'--scope',str(scope_file),'--output',str(output)]
        process=subprocess.run(command,capture_output=True,text=True,timeout=5)
        checks['actual_command_planner_cli']=process.returncode==0 and json.loads(output.read_text())['selected_results'][0]['data']['delta_ms']==-1000
        checks['cli_includes_answer']=process.returncode==0 and '快 1.000 秒' in json.loads(output.read_text())['answer']['text']
    return {'passed':all(checks.values()),'checks':checks,'scope':'scripted planner and real executor/SQLite/command CLI; no live LLM or voice'}


if __name__=='__main__':emit_result(run())

import json
from types import SimpleNamespace
from unittest.mock import patch
from asurada.analysis_planner import HttpAnalysisPlanner,decode_step
from asurada.task_runtime import TaskContext,TaskCancelled
from regression_support import emit_result


def run():
    checks={};provider=SimpleNamespace(model='test',base_url='https://example.invalid/v1',_headers=lambda:{'Authorization':'Bearer fixture'})
    step={'action':'call','tool':'compare_review_laps','arguments_json':'{"review_task_id":"review","lap_numbers":[1,2]}','result_ids':[]}
    for style in ('responses','chat'):
        planner=HttpAnalysisPlanner(provider,style=style);context=TaskContext.start('planner',1000)
        response={'status':'completed','output_text':json.dumps(step),'usage':{'input_tokens':10,'output_tokens':20}} if style=='responses' else {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(step)}}],'usage':{'prompt_tokens':10,'completion_tokens':20}}
        with patch('asurada.analysis_planner.request_json',return_value=response) as transport:
            result=planner.next_step({'question':'compare','tools':[]},context=context)
        kwargs=transport.call_args.kwargs;body=kwargs['body']
        checks[style+'_step']=result['arguments']['lap_numbers']==[1,2]
        checks[style+'_shared_budget']=kwargs['context'] is context and 0<kwargs['timeout_ms']<=1000
        checks[style+'_output_cap']=body.get('max_output_tokens',body.get('max_tokens'))==1024
        checks[style+'_usage_recorded']=planner.calls[0]['usage']==response['usage'] and planner.calls[0]['status']=='completed'
        bad={'status':'incomplete','output_text':json.dumps(step)} if style=='responses' else {'choices':[{'finish_reason':'length','message':{'content':json.dumps(step)}}]}
        with patch('asurada.analysis_planner.request_json',return_value=bad):
            try:planner.next_step({},context=context);checks[style+'_truncation_rejected']=False
            except ValueError:checks[style+'_truncation_rejected']=True
    for name,changed in [('mixed',{**step,'result_ids':['invented']}),('bad_json',{**step,'arguments_json':'broken'}),('extra',{**step,'answer':'invented answer'})]:
        try:decode_step(changed);checks[name]=False
        except ValueError:checks[name]=True
    context=TaskContext.start('cancelled',1000);context.cancel()
    with patch('asurada.analysis_planner.request_json') as transport:
        try:planner.next_step({},context=context);checks['cancelled_never_sends']=False
        except TaskCancelled:checks['cancelled_never_sends']=not transport.called
    return {'passed':all(checks.values()),'checks':checks,'scope':'mock HTTP response/request contract; no provider or billing acceptance'}


if __name__=='__main__':emit_result(run())

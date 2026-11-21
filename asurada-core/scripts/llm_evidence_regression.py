from dataclasses import replace
from regression_support import emit_result
from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest, _extract_json_or_text_payload
from asurada.llm_response_schema import validate_llm_response
from asurada.task_runtime import BoundedTaskExecutor


def run():
    request = LlmExplainerRequest('s','t','r','why','why','test',500,{'state_snapshot':{'gap_behind_s':.5, 'ers_pct':None}})
    valid = dict(status='answerable',answer_text='后车差距较小。',confidence=.8,reason_fields=['state_snapshot.gap_behind_s'])
    class Backend:
        name='evidence_fake'
        def __init__(self,payload, mutate=False): self.payload,self.mutate=payload,mutate
        def explain(self, req):
            if self.mutate: req.state_summary['state_snapshot']['invented']=123
            return self.payload
    def result(payload, mode='racing_explainer', mutate=False):
        return LlmExplainer(backend=Backend(payload,mutate),executor=BoundedTaskExecutor(1)).run(request=replace(request,interaction_mode=mode))
    checks={'valid_evidence_accepted':result(valid).status=='completed'}
    for label, payload in [('invented',{**valid,'reason_fields':['invented']}), ('null',{**valid,'reason_fields':['state_snapshot.ers_pct']}), ('missing',{**valid,'reason_fields':[]}),('plain',_extract_json_or_text_payload('后车0.2秒')),('binding',{**valid,'metadata':{'request_id':'other'}})]:
        checks[label+'_rejected'] = result(payload).fallback_reason=='llm_invalid_evidence'
    checks['backend_cannot_create_evidence']=result({**valid,'reason_fields':['invented']},mutate=True).fallback_reason=='llm_invalid_evidence' and 'invented' not in request.state_summary['state_snapshot']
    checks['companion_text_allowed']=result(_extract_json_or_text_payload('你好'),'companion_chat').status=='completed'
    for label,value in [('nan',float('nan')),('infinity',float('inf')),('boolean',True)]:
        checks[label+'_confidence_rejected']=not validate_llm_response({**valid,'confidence':value})[0]
    checks['false_refs_not_silently_empty']=not validate_llm_response({**valid,'reason_fields':False})[0]
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__': emit_result(run())

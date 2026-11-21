from copy import deepcopy
from types import SimpleNamespace
import time
from regression_support import emit_result
from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest
from asurada.task_runtime import BoundedTaskExecutor


def run():
    checks = {}
    request = LlmExplainerRequest('s','t','claim-request','why','why','test',500,
        {'state_snapshot':{'gap_ahead_s':1.25,'gap_behind_s':.5,'ers_pct':50}})
    refs = ['state_snapshot.gap_ahead_s','state_snapshot.gap_behind_s']
    valid = dict(status='answerable',answer_text='前后车距之差为 {{gap}}。',confidence=.8,
        reason_fields=refs, metadata={'request_id':'claim-request'},
        claims=[dict(id='gap',operation='difference',refs=refs,value=.75,unit='s',precision=2)])
    class Backend:
        name='claims-fake'
        def __init__(self,payload): self.payload=payload
        def explain(self,request): return deepcopy(self.payload)
    def run_response(payload):
        return LlmExplainer(backend=Backend(payload),executor=BoundedTaskExecutor(1)).run(request=request)
    result = run_response(valid)
    checks['actual_explainer_computes_and_renders'] = result.status=='completed' and result.response['answer_text']=='前后车距之差为 0.75秒。'
    checks['claims_and_template_retained'] = result.response['claims']==valid['claims'] and result.response['metadata']['claim_template']==valid['answer_text']
    checks['sidecar_second_validation_idempotent'] = run_response(result.response).response==result.response
    for name, text in [('arabic','后车还有 0.5 秒。'),('chinese','后车还有两秒。'),('percent','电量百分之五十。')]:
        legacy=deepcopy(valid)
        legacy['claims']=[]
        legacy['answer_text']=text
        checks[name+'_legacy_numeric_rejected']=run_response(legacy).fallback_reason=='llm_invalid_evidence'
    for name in ('wrong_value','wrong_unit','wrong_order','missing_binding','undeclared_source','unbound_text','missing_token','duplicate_id','nonfinite','rendered_tamper'):
        payload = deepcopy(valid)
        if name=='wrong_value': payload['claims'][0]['value']=.8
        if name=='wrong_unit': payload['claims'][0]['unit']='%'
        if name=='wrong_order': payload['claims'][0]['refs']=list(reversed(refs))
        if name=='missing_binding': payload['metadata']={}
        if name=='undeclared_source': payload['reason_fields']=refs[:1]
        if name=='unbound_text': payload['answer_text']+='还有 2 秒。'
        if name=='missing_token': payload['answer_text']='没有占位。'
        if name=='duplicate_id': payload['claims']*=2
        if name=='nonfinite': payload['claims'][0]['value']=float('nan')
        if name=='rendered_tamper':
            payload=deepcopy(result.response)
            payload['answer_text']='错误数字 9 秒。'
        checks[name+'_rejected'] = run_response(payload).fallback_reason=='llm_invalid_evidence'
    # Actual voice override creation followed by the output service's validator.
    from asurada.voice_input import VoiceInputCoordinator
    from asurada.speech_applicability import validate_query_applicability
    from phase3_llm_boundary_regression import _make_state
    state=_make_state()
    state.source_timestamp_ms=int(time.time()*1000)
    state.player.gap_ahead_s=1.25
    state.player.gap_behind_s=.5
    override=VoiceInputCoordinator._build_llm_response_override(object.__new__(VoiceInputCoordinator),
        route_decision=SimpleNamespace(lane='explainer',query_kind='why'),llm_result=result)
    params={'bundle':{'response_override':override,'input_event':{'request_id':'claim-request'}}}
    validate_query_applicability('emit_voice_query_bundle',params,state,deepcopy(state))
    checks['actual_voice_override_passes_service_validation']=True
    for change in ('value','text','request'):
        mutated=deepcopy(params)
        if change=='value':mutated['bundle']['response_override']['claims'][0]['value']=.9
        if change=='text':mutated['bundle']['response_override']['speak_text']='后车九秒。'
        if change=='request':mutated['bundle']['input_event']['request_id']='other'
        try:
            validate_query_applicability('emit_voice_query_bundle',mutated,state,deepcopy(state))
            checks['service_'+change+'_tamper_rejected']=False
        except ValueError:checks['service_'+change+'_tamper_rejected']=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

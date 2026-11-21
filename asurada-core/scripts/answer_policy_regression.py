from copy import deepcopy
from types import SimpleNamespace
import time
from asurada.answer_policy import CLARIFICATIONS
from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest
from asurada.voice_input import VoiceInputCoordinator
from asurada.speech_applicability import validate_query_applicability
from phase3_llm_boundary_regression import _make_state
from regression_support import emit_result


def run():
    checks = {}
    request = LlmExplainerRequest('s', 't', 'clarification-request', 'why', 'why', 'test', 500,
        {'state_snapshot': {'ers_pct': 50}})
    class Backend:
        name = 'clarification-fixture'
        def __init__(self, payload): self.payload = payload
        def explain(self, request): return deepcopy(self.payload)
    state = _make_state()
    state.source_timestamp_ms = int(time.time() * 1000)
    for field, expected in CLARIFICATIONS.items():
        payload = dict(status='needs_clarification', answer_text='还剩 999 圈，可以全力进攻。',
            confidence=.5, reason_fields=[], claims=[], metadata={'clarification_field': field})
        result = LlmExplainer(backend=Backend(payload)).run(request=request)
        checks[field + '_canonical_not_model_assertion'] = result.status == 'completed' and result.response['answer_text'] == expected
        override = VoiceInputCoordinator._build_llm_response_override(object.__new__(VoiceInputCoordinator),
            route_decision=SimpleNamespace(lane='explainer', query_kind='why'), llm_result=result)
        params = {'bundle': {'response_override': override, 'input_event': {'request_id': request.request_id}}}
        validate_query_applicability('emit_voice_query_bundle', params, state, deepcopy(state))
        checks[field + '_actual_override_deliverable'] = True
        tampered = deepcopy(params)
        tampered['bundle']['response_override']['speak_text'] = '剩余九百圈。'
        try:
            validate_query_applicability('emit_voice_query_bundle', tampered, state, deepcopy(state))
            checks[field + '_tamper_rejected'] = False
        except ValueError:
            checks[field + '_tamper_rejected'] = True
    for name, changes in [('unsupported_field', {'metadata': {'clarification_field': 'arbitrary'}}),
                          ('claims', {'claims': [{'id': 'fake'}]}),
                          ('fact_without_evidence', {'status': 'answerable', 'answer_text': '余量充足。'})]:
        invalid = dict(payload, **changes)
        result = LlmExplainer(backend=Backend(invalid)).run(request=request)
        checks[name + '_rejected'] = result.fallback_reason == 'llm_invalid_evidence'
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())

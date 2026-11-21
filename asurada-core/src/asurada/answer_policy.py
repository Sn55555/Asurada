"""Shared rendering policy; clarification cannot smuggle unverified assertions."""
from .llm_claims import render_claims
from .llm_evidence import InvalidLlmEvidence, validate_evidence

CLARIFICATIONS = {
    'query_scope': '你想了解哪方面的情况？',
    'lap_selection': '你想比较哪一圈？',
    'segment_selection': '你想比较哪个赛道区段？',
}


def render_racing_response(response, *, summary, request_id):
    validate_evidence(response, summary=summary, mode='racing_explainer', request_id=request_id)
    if response.get('status') == 'needs_clarification':
        if response.get('claims'):
            raise InvalidLlmEvidence('clarification_cannot_contain_claims')
        field = (response.get('metadata') or {}).get('clarification_field', 'query_scope')
        if not isinstance(field, str) or field not in CLARIFICATIONS:
            raise InvalidLlmEvidence('unsupported_clarification_field')
        # Never deliver arbitrary model prose via the clarification exemption.
        return CLARIFICATIONS[field]
    return render_claims(response, summary=summary, request_id=request_id)

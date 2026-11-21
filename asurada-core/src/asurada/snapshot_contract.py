"""Versioned snapshot and decision serialization shared by live/read/replay paths."""
from __future__ import annotations
from dataclasses import asdict
from typing import Any
from .models import SessionState, StrategyDecision, AssessmentResult, StateAssessment, DecisionRecord, StrategyMessage


def snapshot_payload(state: SessionState, decision: StrategyDecision) -> dict[str, Any]:
    payload = {'contract_version':'telemetry-v1', 'session_uid':state.session_uid, 'session_epoch':state.session_epoch,
            'track':state.track,'lap_number':state.lap_number,'total_laps':state.total_laps,
            'weather':state.weather,'safety_car':state.safety_car,'source_timestamp_ms':state.source_timestamp_ms,
            'player':asdict(state.player),'rivals':[asdict(item) for item in state.rivals],'raw':state.raw,
            'messages':[asdict(item) for item in decision.messages],
            'session_event':state.session_event,
            'decision_record':asdict(decision.record) if decision.record is not None else None}
    if state.personality is not None:
        payload['personality'] = asdict(state.personality)
    return payload


def restore_decision(state: SessionState, payload: dict[str, Any]) -> None:
    from .assessment import snapshot_id
    event = payload.get('session_event')
    if event is not None:
        if not isinstance(event, dict) or event.get('contract_version') != 'session-event-v1':
            raise ValueError('unsupported_session_event_contract')
        if (event.get('session_uid') != str(state.session_uid)
                or type(event.get('session_epoch')) is not int
                or event['session_epoch'] != state.session_epoch):
            raise ValueError('session_event_scope_mismatch')
        state.session_event = dict(event)
    record = payload.get('decision_record')
    if record is None:
        return  # Legacy telemetry remains readable, with no bound decision.
    if not isinstance(record,dict) or record.get('contract_version') != 'decision-v1':
        raise ValueError('unsupported_decision_contract')
    binding = snapshot_id(state)
    if (record.get('snapshot_id') != binding or record.get('session_uid') != state.session_uid
            or record.get('session_epoch') != state.session_epoch or record.get('source_timestamp_ms') != state.source_timestamp_ms):
        raise ValueError('decision_snapshot_mismatch')
    assessment = dict(record['assessment'])
    if assessment.get('snapshot_id') != binding:
        raise ValueError('assessment_snapshot_mismatch')
    domain = AssessmentResult(snapshot_id=binding, rule_version=assessment['rule_version'],
                              labels=StateAssessment(**assessment['labels']), fuel=dict(assessment['fuel']), thresholds=dict(assessment['thresholds']))
    restored = DecisionRecord(decision_id=record['decision_id'], snapshot_id=binding,
                              session_uid=state.session_uid, session_epoch=state.session_epoch,
                              source_timestamp_ms=state.source_timestamp_ms, assessment=domain,
                              actions=tuple(StrategyMessage(**item) for item in record['actions']),
                              candidates=tuple(record['candidates']), arbitration=dict(record['arbitration']),
                              model_admission=dict(record.get('model_admission', {})),
                              identity_version=record.get('identity_version', 'legacy'))
    from .decision_identity import VERSION, decision_content_id
    if restored.identity_version not in {'legacy', VERSION}:
        raise ValueError('unsupported_decision_identity')
    if restored.identity_version == VERSION and restored.decision_id != decision_content_id(restored):
        raise ValueError('decision_content_mismatch')
    state.assessment = domain
    state.decision_record = restored
    if isinstance(payload.get('personality'), dict):
        from .personality_runtime import PersonalitySnapshot
        try:
            personality = PersonalitySnapshot(**payload['personality'])
            if personality.matches(state):
                state.personality = personality
        except (TypeError, ValueError):
            pass

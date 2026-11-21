from __future__ import annotations

from unittest.mock import patch
from copy import deepcopy
from dataclasses import replace
from regression_support import emit_result, runtime_clock
from phase3_voice_regression import make_state
from asurada.assessment import assess_fuel, assess_domain, snapshot_id
from asurada.config import StrategyThresholds
from asurada.config import AppConfig
from asurada.conversation_context import ConversationContext
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from asurada.response_composer import compose_structured_query_response
from asurada.state_summary_for_llm import build_state_summary_for_llm
from asurada.strategy import StrategyEngine
from asurada.llm_evidence import evidence_fields


@runtime_clock(1_000_000)
def run():
    state = make_state()
    state.source_timestamp_ms = 1_000_000
    state.raw.update(fuel_laps_remaining_source='derived_from_sample_consumption', fuel_in_tank=20, fuel_capacity=50)
    with patch.object(ResourceRiskModelRuntime, '_load'), patch.object(StrategyActionModelRuntime, '_load'):
        engine = StrategyEngine(AppConfig().thresholds)
    checks = {}
    for label, fuel, expected in [('insufficient', 12.4, 'critical'), ('sufficient', 15, 'stable')]:
        state.player.fuel_laps_remaining = fuel
        assessment = assess_fuel(state)
        core = engine._assess_state(state)
        answer, _ = compose_structured_query_response(state=state, query_kind='fuel_status', primary_message=None)
        advice, _ = compose_structured_query_response(state=state, query_kind='fuel_management_advice', primary_message=None)
        summary = build_state_summary_for_llm(state=state, primary_message=None, conversation_context=ConversationContext())
        checks[label] = core.fuel_state == expected == assessment.verdict and assessment.describe() in answer and assessment.describe() in advice
        checks[label + '_summary'] = summary.state_snapshot['fuel_assessment'] == assessment.to_dict()
    state.raw.clear()
    checks['missing_is_unavailable'] = engine._assess_state(state).fuel_state == 'unavailable'
    state.raw.update(fuel_in_tank=0, fuel_capacity=100)
    checks['actual_zero_is_critical'] = assess_fuel(state).verdict == 'critical' and '终盘覆盖暂不能可靠判断' in assess_fuel(state).describe()
    state.raw.update(fuel_in_tank=float('nan'))
    checks['nonfinite_is_unavailable'] = assess_fuel(state).verdict == 'unavailable'
    state.player.tyre.wear_pct = 45
    custom = assess_domain(state, StrategyThresholds(tyre_wear_warn=40))
    answer, _ = compose_structured_query_response(state=state, query_kind='tyre_management_advice', primary_message=None)
    checks['custom_threshold_shared'] = custom.labels.tyre_state == 'manage' and '开始保胎' in answer
    old_binding = custom.snapshot_id
    state.player.tyre.wear_pct = 20
    checks['mutated_snapshot_reassessed'] = assess_domain(state).snapshot_id != old_binding and assess_domain(state).labels.tyre_state == 'stable'
    for label, value in [('missing', None), ('bool', True), ('text', '50'), ('negative', -1),
                         ('over_100', 150), ('nan', float('nan')), ('infinite', float('inf'))]:
        invalid = deepcopy(state)
        invalid.player.ers_pct = invalid.player.tyre.wear_pct = value
        domain = assess_domain(invalid)
        checks[label + '_resource_unavailable'] = domain.labels.ers_state == domain.labels.tyre_state == 'unavailable'
        for query in ('ers_status', 'tyre_status', 'tyre_management_advice', 'tyre_wear_outlook'):
            answer, _ = compose_structured_query_response(state=invalid, query_kind=query, primary_message=None)
            checks[label + '_' + query] = '数据不可用' in answer
        summary = build_state_summary_for_llm(state=invalid, primary_message=None, conversation_context=ConversationContext()).to_dict()
        fields = evidence_fields(summary)
        checks[label + '_cannot_be_cited'] = all(ref not in fields for ref in
            ('state_snapshot.ers_pct', 'state_snapshot.tyre.wear_pct'))
        # Exercise the rule candidate path, not just its label helper.
        context = engine._build_context(invalid, [invalid])
        risks, _ = engine._score_risks(invalid, domain.labels, context)
        codes = {candidate.code for candidate in engine._build_candidates(invalid, domain.labels, risks, context)}
        checks[label + '_no_resource_candidate'] = not codes.intersection({'ERS_LOW', 'BOX_WINDOW', 'TYRE_MANAGE'})
    for value in (0, 100):
        boundary = deepcopy(state)
        boundary.player.ers_pct = boundary.player.tyre.wear_pct = value
        labels = assess_domain(boundary).labels
        checks[str(value) + '_percentage_boundary_valid'] = labels.ers_state != 'unavailable' and labels.tyre_state != 'unavailable'
    old = deepcopy(state)
    current = assess_domain(old)
    old.assessment = replace(current, rule_version='domain-v1')
    checks['old_assessment_recomputed'] = assess_domain(old).rule_version == 'domain-v6'
    for label, value in [('bool', True), ('text', '20')]:
        invalid = deepcopy(state)
        invalid.raw.update(fuel_in_tank=value, fuel_capacity=100)
        checks[label + '_fuel_unavailable'] = assess_fuel(invalid).verdict == 'unavailable'
    from model_admission_regression import evaluate
    from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
    decision = evaluate(ModelAdmissionPolicy(modes={name:'disabled' for name in MODEL_NAMES}), 0)
    record = decision.record
    original = record.actions[0].detail
    decision.messages[0].detail = 'mutated display'
    checks['record_retains_original_action'] = record.actions[0].detail == original
    checks['record_has_binding_and_candidates'] = bool(record.snapshot_id and record.decision_id and record.candidates) and record.assessment.snapshot_id == record.snapshot_id
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

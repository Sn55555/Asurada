from regression_support import emit_result
from asurada.arbiter import StrategyArbiterV2, ArbiterInput, RuleCandidate


def priorities(scores):
    candidates = [RuleCandidate(code, priority, code, '') for code, priority in [
        ('LOW_FUEL', 95), ('DYNAMICS_UNSTABLE', 72), ('ATTACK_WINDOW', 56), ('DEFEND_WINDOW', 54), ('FRONT_LOAD', 58)]]
    result = StrategyArbiterV2().arbitrate(ArbiterInput(rule_candidates=candidates, sidecar_scores=scores))
    return {x.code: x.priority for x in result.ordered_actions}


def run():
    baseline = priorities({})
    checks = {'absent_preserves_priorities': baseline == {'LOW_FUEL':95,'DYNAMICS_UNSTABLE':72,'ATTACK_WINDOW':56,'DEFEND_WINDOW':54,'FRONT_LOAD':58}}
    for label, value in [('missing', {}), ('null', {'score':None}), ('nan', {'score':float('nan')}), ('infinity', {'score':float('inf')}), ('disabled', {'score':0,'enabled':False})]:
        checks[label] = priorities({'resource_models':{'fuel_risk':value}}) == baseline
    checks['valid_zero_can_reduce_risk'] = priorities({'resource_models':{'fuel_risk':{'enabled':True,'score':0}}})['LOW_FUEL'] == 85
    checks['partial_models_do_not_invent_other_scores'] = priorities({'resource_models':{'fuel_risk':{'score':95}}}) == {**baseline, 'LOW_FUEL':107}
    checks['zero_corner_quality_is_valid'] = priorities({'driving_quality_models':{'entry_quality':{'score':0}, 'apex_quality':{'score':0}}})['DYNAMICS_UNSTABLE'] == 80
    return {'passed':all(checks.values()),'checks':checks}

if __name__ == '__main__':
    emit_result(run())

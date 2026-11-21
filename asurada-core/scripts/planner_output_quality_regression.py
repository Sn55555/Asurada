"""Malformed planner contributions cannot create or suppress decision priority."""
from copy import deepcopy
from asurada.arbiter import StrategyArbiterV2, ArbiterInput, RuleCandidate
from asurada.contributor_admission import ContributorPolicy, NAMES
from regression_support import emit_result


def run():
    valid = {
        'pit_window_support': {'enabled': True, 'pit_window_open_prob': .4,
                              'rejoin_traffic_penalty': 20., 'pit_loss_now_score': 55.},
        'long_horizon_strategy': {'enabled': True, 'aggression_bias': -.3,
                                 'stint_risk_score': 65., 'strategy_confidence': .8,
                                 'remaining_required_stops': 1},
    }
    policy = ContributorPolicy(modes={n:'active' for n in NAMES},
                               evidence={n:'synthetic-contract-test' for n in NAMES})
    def priorities(scores):
        result = StrategyArbiterV2().arbitrate(ArbiterInput(
            rule_candidates=[RuleCandidate(c, p, c, '') for c,p in
                             [('ATTACK_WINDOW',56),('DEFEND_WINDOW',54),('BOX_WINDOW',65),('TYRE_MANAGE',50)]],
            sidecar_scores=scores))
        return {x.code:x.priority for x in result.ordered_actions}
    baseline = priorities({})
    checks = {'valid_contribution_changes_priority':priorities(valid)!=baseline}
    for name, payload in valid.items():
        for field in set(payload)-{'enabled'}:
            for label, value in [('missing',None),('null',None),('nan',float('nan')),
                                 ('infinity',float('inf')),('boolean',True),('text','0')]:
                bad = deepcopy(valid)
                if label=='missing':del bad[name][field]
                else:bad[name][field]=value
                key = name+'_'+field+'_'+label
                checks[key+'_admission'] = policy.admit(name,bad[name]) == {}
                try:checks[key+'_no_effect'] = priorities(bad)==baseline
                except (ValueError, OverflowError, TypeError):checks[key+'_no_effect'] = False
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

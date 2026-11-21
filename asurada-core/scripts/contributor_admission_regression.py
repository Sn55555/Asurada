from dataclasses import asdict
from unittest.mock import patch
from regression_support import emit_result
from phase1_rival_pit_window_support_regression import _build_state
from asurada.config import StrategyThresholds
from asurada.contributor_admission import ContributorPolicy,NAMES
from asurada.model_runtime import ResourceRiskModelRuntime,StrategyActionModelRuntime
from asurada.strategy import StrategyEngine


def evaluate(mode, aggression):
    policy=ContributorPolicy(modes={name:mode for name in NAMES},evidence={name:'synthetic-admission-test' for name in NAMES} if mode=='active' else {})
    with patch.object(ResourceRiskModelRuntime,'_load'),patch.object(StrategyActionModelRuntime,'_load'):
        engine=StrategyEngine(StrategyThresholds(),contributor_policy=policy)
    calls=[]
    class Result:
        def __init__(self,payload):self.payload=payload
        def to_dict(self):return self.payload
    def support(**kwargs):calls.append('support');return Result({'enabled':True,'pit_window_open_prob':.9,'rejoin_traffic_penalty':20.,'pit_loss_now_score':55.})
    def plan(**kwargs):calls.append('plan');return Result({'enabled':True,'aggression_bias':aggression,'strategy_confidence':.9,'stint_risk_score':80,'remaining_required_stops':1})
    engine.pit_window_support.evaluate=support;engine.long_horizon_strategy.plan=plan
    state=_build_state();state.raw.update(timing_mode='race_like',timing_support_level='official_preferred',fuel_in_tank=20,fuel_capacity=50)
    return engine.evaluate(state,[state]),calls


def run():
    disabled,calls=evaluate('disabled',0);low,_=evaluate('observe',-1);high,_=evaluate('observe',1);active,_=evaluate('active',1)
    def messages(d):return [asdict(m) for m in d.messages]
    checks={'disabled_skips_compute':not calls,
            'observe_has_no_decision_influence':messages(disabled)==messages(low)==messages(high),
            'active_can_change_decision':messages(active)!=messages(high),
            'observe_keeps_diagnostics':high.debug['arbiter_v2']['input']['long_horizon_strategy']['aggression_bias']==1,
            'observe_not_in_arbiter':not high.debug['arbiter_v2']['input']['sidecar_scores']['long_horizon_strategy'],
            'active_contribution_passes_gate':active.debug['arbiter_v2']['input']['sidecar_scores']['long_horizon_strategy']['aggression_bias']==1}
    try:ContributorPolicy(modes={'long_horizon_strategy':'active'},evidence={'long_horizon_strategy':'test'});checks['dependency_required']=False
    except ValueError:checks['dependency_required']=True
    try:ContributorPolicy(modes={name:'active' for name in NAMES});checks['evidence_required']=False
    except ValueError:checks['evidence_required']=True
    return {'passed':all(checks.values()),'checks':checks}

if __name__=='__main__':emit_result(run())

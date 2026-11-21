"""Action summaries consume shared thresholds and fuel evidence provenance."""
from asurada.assessment import assess_domain, assess_fuel
from asurada.config import StrategyThresholds
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={}
    for label,threshold,urgent in [('custom_open',1.5,True),('custom_closed',.5,False)]:
        state=make_state();state.rivals=[];state.raw={};state.player.status_tags=[]
        state.player.tyre.wear_pct=10;state.player.gap_ahead_s=5;state.player.gap_behind_s=1.1
        assess_domain(state,StrategyThresholds(rival_gap_defend=threshold))
        for query,phrase in [('attack_or_defend_summary','当前更偏向防守'),
                             ('attack_defend_tradeoff','当前防守代价更低'),
                             ('main_risk_summary','最大风险是后车逼近'),
                             ('risk_severity_followup','后车已经压到'),
                             ('risk_escalation_timing','当前后车只有')]:
            text,_=compose_structured_query_response(state=state,query_kind=query)
            checks[label+'_'+query]=(phrase in text)==urgent
    state.player.gap_ahead_s=1.1;state.player.gap_behind_s=5;state.player.drs_available=True
    assess_domain(state,StrategyThresholds(rival_gap_attack=1.2))
    text,_=compose_structured_query_response(state=state,query_kind='attack_or_defend_summary')
    checks['attack_summary_uses_core_window']='当前更偏向进攻' in text
    # Unknown rear distance is not evidence that attacking is cheaper.
    state.player.gap_behind_s=None
    text,_=compose_structured_query_response(state=state,query_kind='attack_defend_tradeoff')
    checks['unknown_rear_not_clear']='当前进攻代价更低' not in text
    state.player.gap_ahead_s=state.player.gap_behind_s=5
    state.raw={'fuel_in_tank':0,'fuel_capacity':100}  # Empty fuel is evidence; low tank percentage alone is not.
    state.player.fuel_laps_remaining=99  # Not a consumption-backed estimate.
    expected=assess_fuel(state).describe()
    for query in ('risk_severity_followup','risk_escalation_timing'):
        text,_=compose_structured_query_response(state=state,query_kind=query)
        checks[query+'_fuel_provenance']=expected in text and '99.0 圈' not in text
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

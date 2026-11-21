"""Real rival objects must not bypass the configured domain policy."""
from copy import deepcopy
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={}
    for label,limit,urgent in [('open',1.5,True),('closed',.5,False)]:
        state=make_state();state.raw={};state.player.status_tags=[];state.player.tyre.wear_pct=10
        state.player.gap_ahead_s=5;state.player.gap_behind_s=.8
        rear=deepcopy(state.player);rear.position=state.player.position+1;rear.name='RearFixture'
        rear.drs_available=True;rear.pit_status=None;rear.engine_damage_pct=0
        state.rivals=[rear]
        assess_domain(state,StrategyThresholds(rival_gap_defend=limit))
        for query in ('main_risk_summary','risk_severity_followup','risk_escalation_timing','attack_defend_tradeoff'):
            text,_=compose_structured_query_response(state=state,query_kind=query)
            checks[label+'_'+query]=('带着 DRS' in text)==urgent
    state.player.gap_behind_s=-1;rear.gap_confidence_ahead='medium'
    for query in ('main_risk_summary','risk_severity_followup','risk_escalation_timing'):
        text,_=compose_structured_query_response(state=state,query_kind=query)
        checks['invalid_'+query]='-1.000' not in text and '带着 DRS' not in text
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

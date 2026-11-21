"""User-facing gap verdicts follow core thresholds and missing-data semantics."""
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={}
    for label,ahead,behind,thresholds in [
        ('default',1.1,1.1,StrategyThresholds()),
        ('custom_open',1.4,1.4,StrategyThresholds(rival_gap_attack=1.5,rival_gap_defend=1.5)),
        ('custom_closed',.8,.8,StrategyThresholds(rival_gap_attack=.5,rival_gap_defend=.5)),
        ('missing',None,None,StrategyThresholds()),
        ('negative',-1,-1,StrategyThresholds()),
        ('nan',float('nan'),float('nan'),StrategyThresholds())]:
        state=make_state();state.rivals=[];state.player.drs_available=True
        state.player.gap_ahead_s=ahead;state.player.gap_behind_s=behind
        domain=assess_domain(state,thresholds)
        front,_=compose_structured_query_response(state=state,query_kind='front_gap')
        rear,_=compose_structured_query_response(state=state,query_kind='rear_gap')
        outlook,_=compose_structured_query_response(state=state,query_kind='attack_outcome_projection')
        checks[label+'_front']=('已经进直接进攻观察窗口' in front)==(domain.labels.attack_state=='available')
        checks[label+'_rear']=('已经进直接防守窗口' in rear)==(domain.labels.defend_state=='urgent')
        checks[label+'_outlook']=('有机会把前车压进直接对抗' in outlook)==(domain.labels.attack_state=='available')
        if domain.labels.attack_state=='unavailable':checks[label+'_unavailable']='数据不可用' in outlook
    state=make_state();state.rivals=[];state.player.drs_available=True
    state.player.gap_ahead_s=.8;state.player.gap_behind_s=None
    answer,_=compose_structured_query_response(state=state,query_kind='attack_outcome_projection')
    checks['missing_rear_does_not_crash_or_invent_gap']='未知' in answer and '有机会把前车' in answer
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

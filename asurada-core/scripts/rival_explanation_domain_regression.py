"""Explanations do not turn missing gaps or a question premise into decisions."""
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.models import StrategyMessage
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks={}
    def state_with(ahead=5,behind=5,threshold=1.):
        state=make_state();state.rivals=[];state.raw={};state.player.status_tags=[]
        state.player.gap_ahead_s=ahead;state.player.gap_behind_s=behind;state.player.drs_available=True
        assess_domain(state,StrategyThresholds(rival_gap_attack=threshold,rival_gap_defend=threshold))
        return state
    def answer(state,query,primary=None):
        return compose_structured_query_response(state=state,query_kind=query,primary_message=primary)[0]
    for label,gap in [('missing',None),('negative',-1),('nan',float('nan'))]:
        state=state_with(behind=gap)
        for query in ('rear_pressure_relief_outlook','defend_outcome_projection'):
            checks[label+'_'+query]='数据不可用' in answer(state,query)
        checks[label+'_no_defence_claim']='当前偏向防守' not in answer(state,'why_defend')
    for label,threshold,urgent in [('open',1.5,True),('closed',.5,False)]:
        state=state_with(behind=1.1,threshold=threshold)
        checks[label+'_pressure']=('主动把防守窗口管住' in answer(state,'rear_pressure_relief_outlook'))==urgent
        checks[label+'_outcome']=('压力还会继续存在' in answer(state,'defend_outcome_projection'))==urgent
    state=state_with(ahead=1.1,threshold=1.2)
    text=answer(state,'why_not_attack')
    checks['open_attack_not_outside_window']='没进直接进攻窗口' not in text
    checks['unbound_question_not_decision']='现在没有给出进攻窗口' not in text
    state=state_with()
    checks['clear_rear_not_defence_decision']='当前偏向防守' not in answer(state,'why_defend')
    primary=StrategyMessage('ATTACK_WINDOW',60,'attack','current attack reason')
    text=answer(state,'why_not_attack',primary)
    checks['actual_attack_not_denied']='current attack reason' in text and '没有给出进攻窗口' not in text
    primary=StrategyMessage('DEFEND_WINDOW',60,'defend','current defend reason')
    checks['actual_defend_reason_retained']='current defend reason' in answer(state,'why_defend',primary)
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

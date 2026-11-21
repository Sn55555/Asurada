"""Outlook query and core labels share attack/defence gap policy."""
from asurada.assessment import assess_domain
from asurada.config import StrategyThresholds
from asurada.models import StrategyMessage
from asurada.response_composer import compose_structured_query_response
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    checks = {}
    cases = [
        ('default_attack', 1.1, 3, StrategyThresholds(), True),
        ('default_defence_closed', 3, 1.05, StrategyThresholds(), False),
        ('custom_attack_closed', .9, 3, StrategyThresholds(rival_gap_attack=.5), False),
        ('custom_defence_open', 3, 1.4, StrategyThresholds(rival_gap_defend=1.5), True),
        ('negative_gaps', -1, -1, StrategyThresholds(), False),
        ('missing_gaps', None, None, StrategyThresholds(), False),
        ('attack_boundary', 1.2, 3, StrategyThresholds(), True),
        ('defence_boundary', 3, 1., StrategyThresholds(), True),
    ]
    for name, ahead, behind, thresholds, expected in cases:
        state = make_state()
        state.player.tyre.wear_pct = 55
        state.player.drs_available = True
        state.player.gap_ahead_s, state.player.gap_behind_s = ahead, behind
        labels = assess_domain(state, thresholds).labels
        answer, code = compose_structured_query_response(state=state, query_kind='tyre_wear_outlook')
        checks[name] = ('直接攻防窗口' in answer) == expected
        checks[name+'_core_agrees'] = (labels.attack_state=='available' or labels.defend_state=='urgent') == expected
        checks[name+'_code'] = code == 'QUERY_TYRE_WEAR_OUTLOOK'
    state.player.gap_ahead_s = state.player.gap_behind_s = 5
    for code in ('ATTACK_WINDOW', 'DEFEND_WINDOW'):
        answer, _ = compose_structured_query_response(state=state, query_kind='tyre_wear_outlook',
            primary_message=StrategyMessage(code, 60, 'fixture', 'fixture'))
        checks[code+'_current_action_retained'] = '直接攻防窗口' in answer
    state.player.tyre.wear_pct = None
    answer, _ = compose_structured_query_response(state=state, query_kind='tyre_wear_outlook')
    checks['invalid_wear_remains_unavailable'] = '数据不可用' in answer
    return {'passed': all(checks.values()), 'checks': checks}


if __name__=='__main__':
    emit_result(run())

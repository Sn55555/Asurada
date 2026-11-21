"""Reject unusable source clocks before exposing racing evidence to the LLM."""
import json
from unittest.mock import patch
from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.runtime_context import RuntimeContextDetector
from asurada.state_summary_for_llm import build_state_summary_for_llm
from asurada.conversation_context import ConversationContext
from asurada.models import StrategyMessage


def run():
    checks = {}
    cases = [('future', 100001), ('inf', float('inf')), ('nan', float('nan')),
             ('bool', True), ('zero', 0), ('negative', -1),
             ('fraction', 99999.5), ('text', '100000'), ('none', None)]
    for label, value in cases:
        state = make_state()
        state.source_timestamp_ms = value
        result = RuntimeContextDetector().detect(state=state, now_ms=100000)
        checks[label + '_not_racing'] = not result.racing_active and result.stale_snapshot
        checks[label + '_age'] = (result.snapshot_age_ms == -1 and result.reason == 'future_snapshot'
                                 if label == 'future' else result.snapshot_age_ms is None)
        context = ConversationContext()
        message = StrategyMessage('LOW_FUEL', 95, 'fuel', 'old')
        context.observe_strategy_message(message, state=state)
        with patch('asurada.runtime_context.time.time', return_value=100):
            summary = build_state_summary_for_llm(state=state, primary_message=message,
                                                 conversation_context=context)
        checks[label + '_evidence_masked'] = (
            summary.state_snapshot['assessment'] is None
            and summary.strategy_snapshot['primary_message'] is None
            and not summary.conversation_snapshot['recent_strategy_messages'])
        checks[label + '_metadata'] = summary.metadata['source_timestamp_ms'] == (
            100001 if label == 'future' else None)
        try:
            json.dumps(summary.to_dict(), allow_nan=False)
            checks[label + '_strict_json'] = True
        except (ValueError, TypeError):
            checks[label + '_strict_json'] = False
    for age in (0, 15000, 15001):
        state = make_state()
        state.source_timestamp_ms = 100000 - age
        result = RuntimeContextDetector().detect(state=state, now_ms=100000)
        checks['valid_boundary_' + str(age)] = result.racing_active == (age <= 15000)
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

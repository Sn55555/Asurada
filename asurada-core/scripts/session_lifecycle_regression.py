from dataclasses import replace
from regression_support import emit_result, runtime_clock
from phase3_voice_regression import make_state
from asurada.state import UnifiedStateStore
from asurada.models import StrategyMessage
from asurada.conversation_context import ConversationContext
from asurada.state_summary_for_llm import build_state_summary_for_llm


@runtime_clock(100000)
def run():
    def frame(uid, overall, frame, timestamp=100000):
        return replace(make_state(), session_uid=uid, source_timestamp_ms=timestamp,
                       raw={'overall_frame_identifier':overall, 'frame_identifier':frame})
    store = UnifiedStateStore()
    a = frame('a',100,100)
    store.update(a)
    store.update(frame('a',101,101,100100))
    checks = {'same_session_keeps_history':len(store.history()) == 2}
    checks['out_of_order_rejected'] = not store.update(frame('a',99,99)) and len(store.history()) == 2
    rewind = frame('a',102,80,100200)
    store.update(rewind)
    checks['rewind_new_epoch'] = rewind.session_epoch == 1 and len(store.history()) == 1 and store.last_transition.reason == 'rewind'
    store.update(frame('a',103,81,102000))
    checks['time_window'] = len(store.recent_seconds(1)) == 1
    b = frame('b',1,1)
    store.update(b)
    checks['new_session_clears_history'] = store.history() == [b] and b.session_epoch == 0
    invalid = replace(b, raw={'overall_frame_identifier':float('inf'), 'frame_identifier':float('nan')})
    checks['invalid_counters_do_not_crash_or_invent_rewind'] = store.update(invalid) and invalid.session_epoch == 0
    context = ConversationContext()
    message = StrategyMessage('LOW_FUEL',95,'fuel','old fuel evidence')
    context.observe_strategy_message(message,state=a)
    context.observe_user_query(request_id='r',transcript_text='fuel',query_kind='fuel_status',timestamp_ms=100000)
    context.bind(rewind)
    checks['epoch_clears_conversation'] = context.last_strategy_code() is None and context.last_query_kind() is None
    context.observe_strategy_message(message,state=rewind)
    context.bind(b)
    checks['session_clears_conversation'] = context.last_strategy_code() is None
    context.observe_strategy_message(message,state=b)
    context.observe_user_query(request_id='chat',transcript_text='hello',query_kind='open_fallback',timestamp_ms=100000,metadata={'lane':'companion'})
    context.observe_response(request_id='chat',query_kind='open_fallback',action_code='QUERY_COMPANION_CHAT',speak_text='hello',timestamp_ms=100000)
    stale = replace(b,source_timestamp_ms=1)
    summary = build_state_summary_for_llm(state=stale,primary_message=message,conversation_context=context)
    checks['stale_removes_strategy'] = summary.strategy_snapshot['primary_message'] is None and summary.conversation_snapshot['recent_strategy_messages'] == []
    checks['companion_history_retained'] = summary.conversation_snapshot['last_response']['speak_text'] == 'hello'
    return {'passed':all(checks.values()),'checks':checks}

if __name__ == '__main__':
    emit_result(run())

from copy import deepcopy
from regression_support import emit_result
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from asurada.output import ConsoleVoiceOutput


def run():
    class DeferredStop(FakeSpeechBackend):
        def stop(self, handle):
            self.stop_requested = True
    backend = DeferredStop()
    voice = ConsoleVoiceOutput(backend=backend)
    state = make_state()
    def emit(code, priority, current):
        decision = make_strategy_decision(state=current,code=code,priority=priority,title=code,detail='')
        return voice.emit(decision,state=current,render=False)
    emit('ERS_LOW',60,state)
    emit('LOW_FUEL',95,state)
    old_pending = voice._pending_envelope.job.output_event_id
    old_active = voice._active_envelope.job.output_event_id
    cursor = voice.read_events()['cursor']
    changed = deepcopy(state); changed.session_epoch += 1
    voice.bind_session(changed)
    checks = {'pending_removed_on_rewind':voice._pending_envelope is None,
              'stop_requested_without_releasing_owner':backend.stop_requested and voice._active_envelope is not None,
              'repeat_history_cleared':voice._last_completed_envelope is None,
              'transition_records_pending_id':voice.session_events[-1]['cancelled_pending']==old_pending}
    transition = [r['event'] for r in voice.read_events(cursor=cursor)['events']]
    checks['scope_change_publishes_owned_transitions'] = [(r['output_event_id'], r['event_type']) for r in transition] == [
        (old_pending, 'cancel'), (old_active, 'cancel_requested')]
    checks['transition_retains_original_scope'] = all(r['metadata']['session_scope'] == [state.session_uid, state.session_epoch] for r in transition)
    emit('SAFETY_CAR',130,changed)
    checks['new_session_waits_for_stop_ack'] = len(backend._handles)==1 and voice._pending_envelope.job.action_code=='SAFETY_CAR'
    backend.complete_all()
    voice.tick()
    checks['only_new_session_pending_starts'] = len(backend._handles)==2 and voice._active_envelope.job.action_code=='SAFETY_CAR'
    checks['new_speech_scope_bound'] = voice._active_envelope.job.metadata['session_scope']==(changed.session_uid,changed.session_epoch)
    before=len(voice.session_events)
    voice.bind_session(changed)
    checks['same_scope_does_not_reset'] = len(voice.session_events)==before
    voice.shutdown(timeout_s=0)
    shutdown_cursor = voice.read_events()['cursor']
    backend.complete_all(); voice.tick()
    terminal = [r['event'] for r in voice.read_events(cursor=shutdown_cursor)['events']]
    checks['deferred_shutdown_publishes_cancel_on_ack'] = len(terminal) == 1 and terminal[0]['event_type'] == 'cancel' and terminal[0]['metadata']['cancel_reason'] == 'shutdown'
    immediate = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    immediate.emit_query_response(state=state, query_kind='rear_gap', render=False)
    immediate.emit_query_response(state=state, query_kind='tyre_status', render=False)
    cursor = immediate.read_events()['cursor']
    checks['immediate_shutdown_confirmed'] = immediate.shutdown(timeout_s=0)
    events = [r['event'] for r in immediate.read_events(cursor=cursor)['events']]
    checks['shutdown_publishes_pending_and_active_terminal'] = [r['event_type'] for r in events] == ['cancel', 'cancel_requested', 'cancel']
    cursor = immediate.read_events()['cursor']
    immediate.shutdown(timeout_s=0); immediate.tick()
    checks['shutdown_terminal_not_repeated'] = not immediate.read_events(cursor=cursor)['events']
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

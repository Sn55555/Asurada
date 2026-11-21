from copy import deepcopy
from asurada.output import ConsoleVoiceOutput
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from regression_support import emit_result


def run():
    checks = {}
    class BrokenStop(FakeSpeechBackend):
        broken = True
        def stop(self, handle):
            if self.broken: raise OSError('fixture stop failed')
            super().stop(handle)
    for path in ('session', 'preempt', 'shutdown'):
        backend = BrokenStop()
        output = ConsoleVoiceOutput(backend=backend)
        state = make_state()
        def send(code, priority, interrupt=False):
            decision = make_strategy_decision(state=state, code=code, priority=priority, title=code, detail='')
            decision.debug['arbiter_v2']['output']['final_voice_action']['interrupt'] = interrupt
            return output.emit(decision, state=state, render=False)
        send('ERS_LOW', 60)
        old_id = output._active_envelope.job.output_event_id
        if path != 'preempt': send('LOW_FUEL', 95)
        cursor = output.read_events()['cursor']
        if path == 'session':
            changed = deepcopy(state); changed.session_epoch += 1
            checks['scope_change_survives_stop_error'] = output.bind_session(changed)
            checks['scope_transition_recorded'] = output.session_events[-1]['type'] == 'speech_scope_changed'
        elif path == 'preempt':
            result = send('SAFETY_CAR', 130, True)
            checks['urgent_queued_when_stop_fails'] = result['event']['event_type'] == 'enqueue'
        else:
            checks['shutdown_unconfirmed_on_error'] = not output.shutdown(timeout_s=.01)
        events = [r['event'] for r in output.read_events(cursor=cursor)['events']]
        checks[path + '_stop_error_published'] = any(e['event_type'] == 'cancel_requested' and e['metadata'].get('stop_error_type') == 'OSError' for e in events)
        checks[path + '_ownership_retained'] = output._active_envelope.job.output_event_id == old_id and len(backend._handles) == 1
        if path != 'preempt': checks[path + '_pending_removed'] = output._pending_envelope is None
        backend.broken = False
        checks[path + '_shutdown_recovers'] = output.shutdown(timeout_s=.05)
        checks[path + '_ownership_released'] = output._active_envelope is None
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())

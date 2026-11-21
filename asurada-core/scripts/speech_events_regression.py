import time
import uuid
import threading
from unittest.mock import patch
from asurada.speech_events import SpeechEventStream
from asurada.speech_service import SpeechService
from asurada.speech_client import SharedSpeechClient
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from phase3_voice_input_regression import _make_state
from regression_support import emit_result, runtime_clock


@runtime_clock(1777100000000)
def run():
    stream = SpeechEventStream(capacity=2)
    cursor = stream.read()['cursor']
    for i in range(3): stream.append(dict(event_type='start', request_id=str(i)))
    page = stream.read(cursor=cursor, limit=1)
    checks = {'retention_gap_visible': page['gap'] and page['has_more'] and len(page['events']) == 1,
              'restart_visible': SpeechEventStream().read(cursor=page['cursor'])['reset']}
    second = stream.read(cursor=page['cursor'])
    checks['cursor_advances_without_repeating'] = second['events'][0]['sequence'] == 3 and not second['has_more']
    page['events'][0]['event']['request_id'] = 'tampered'
    checks['consumer_cannot_mutate_stream'] = stream.read()['events'][0]['event']['request_id'] == '1'
    small = SpeechEventStream(max_bytes=32)
    small.append(dict(event_type='start', text='x'*100))
    checks['oversized_event_reports_loss'] = small.size == 0 and small.read()['gap']
    small.append(dict(event_type='start', value=float('nan')))
    checks['invalid_event_does_not_fail_output'] = small.read()['gap']
    class Backend(NullSpeechBackend):
        audible = True
        def start(self, job): return {'active': True}
        def is_active(self, handle): return handle is not None and handle['active']
    output = ConsoleVoiceOutput(backend=Backend())
    state = _make_state()
    first = output.emit_query_response(state=state, query_kind='rear_gap', render=False)
    handle = output._active_handle
    output.emit_query_response(state=state, query_kind='tyre_status', render=False)
    initial = output.read_events()
    checks['submission_events_captured'] = [e['event']['event_type'] for e in initial['events']] == ['start', 'enqueue']
    handle['active'] = False
    output.tick()
    later = output.read_events(cursor=initial['cursor'])
    checks['tick_completion_then_queued_start'] = [e['event']['event_type'] for e in later['events']] == ['complete', 'start']
    checks['completion_request_bound'] = later['events'][0]['event']['request_id'] == first['interaction_input_event']['request_id']
    # Exercise service dispatch/client method without opening a listener.
    service = SpeechService('/tmp/asurada-events-regression-unused.sock', output=output)
    client = object.__new__(SharedSpeechClient)
    client.timeout_s = 1.
    def call(method, params=None):
        return service.dispatch(dict(version='speech-ipc-v1', request_id=uuid.uuid4().hex,
            expires_at=time.time()+1, method=method, params=params or {}))
    client.call = call
    checks['client_service_event_route'] = client.read_events(cursor=initial['cursor'])['events'] == later['events']
    checks['read_pages_not_retained_in_command_cache'] = not service._results
    checks['playback_status_client_service_route'] = client.playback_status()['status'] == 'playing'
    original_probe = output.backend.is_active
    def failed_probe(handle): raise OSError('fixture status unavailable')
    output.backend.is_active = failed_probe
    checks['unknown_status_preserved'] = client.playback_status()['status'] == 'unknown' and client.is_playing()
    output.backend.is_active = original_probe
    def failed_call(method, params=None): raise TimeoutError('fixture IPC timeout')
    offline = object.__new__(SharedSpeechClient)
    offline.timeout_s = 1.
    offline.call = failed_call
    checks['ipc_failure_not_idle'] = offline.playback_status()['status'] == 'unknown' and offline.is_playing()
    budgets = []
    budget_client = object.__new__(SharedSpeechClient)
    budget_client.timeout_s = 1.
    def capture_call(reader, method, params):
        budgets.append((reader.timeout_s, method, params))
        return {}
    with patch.object(SharedSpeechClient, 'call', capture_call):
        budget_client.read_events(timeout_s=.02)
    checks['event_budget_isolated_from_commands'] = (budget_client.timeout_s == 1.
        and budgets == [(.02, 'events', {'cursor': None, 'limit': 64})])
    def capture_status(reader, method, params=None):
        budgets.append((reader.timeout_s, method))
        return {'version': 'playback-status-v1', 'status': 'idle', 'error_type': None}
    with patch.object(SharedSpeechClient, 'call', capture_status):
        checks['confirmed_idle_is_not_playing'] = not budget_client.is_playing()
    checks['status_probe_budget_isolated'] = budgets[-1] == (.05, 'playback_status') and budget_client.timeout_s == 1.
    with patch.object(SharedSpeechClient, 'call', lambda *args, **kwargs: {'status': 'idle'}):
        checks['malformed_status_is_unknown'] = budget_client.playback_status()['status'] == 'unknown'
    locked, release = threading.Event(), threading.Event()
    def hold_output():
        with output._output_lock:
            locked.set()
            release.wait(2)
    holder = threading.Thread(target=hold_output)
    holder.start()
    try:
        assert locked.wait(1)
        started = time.perf_counter()
        try:
            output.read_events(timeout_s=.01)
            checks['busy_output_read_times_out'] = False
        except TimeoutError:
            checks['busy_output_read_times_out'] = time.perf_counter() - started < .5
    finally:
        release.set()
        holder.join(1)
    checks['output_lock_released_after_timeout'] = not holder.is_alive() and bool(output.read_events())
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())

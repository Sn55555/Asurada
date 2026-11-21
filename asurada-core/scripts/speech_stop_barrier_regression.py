import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from regression_support import emit_result
from asurada.speech_clock import speech_time
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from asurada.output import ConsoleVoiceOutput
from asurada.interaction import build_snapshot_query_input_event
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.speech_submission import LiveSpeechSubmission
from asurada.voice_interrupt import VoiceTurnInterruption


def run():
    checks = {}
    with TemporaryDirectory(dir='/tmp', prefix='speech-barrier-') as temp:
        backend = FakeSpeechBackend()
        service = SpeechService(Path(temp) / 'voice.sock', output=ConsoleVoiceOutput(backend=backend)).start()
        entered, release = threading.Event(), threading.Event()
        lane = None
        try:
            state = make_state()
            client = SharedSpeechClient(service.path)
            stopper = SharedSpeechClient(service.path)
            with VoiceTurnInterruption(client) as turns:
                context = turns.begin(state=state)
                # Simulate a different process stopping while this turn is in ASR/LLM.
                stopper.emit_control_query_bundle(state=state, bundle={'structured_query': {'query_kind': 'stop'}, 'input_event': build_snapshot_query_input_event(state=state, query_kind='stop').to_dict()})
                try:
                    turns.output_for(context).emit_voice_query_bundle(state=state, bundle={})
                    checks['turn_started_before_remote_stop_rejected'] = False
                except RuntimeError as exc:
                    checks['turn_started_before_remote_stop_rejected'] = 'speech_cancelled_by_stop_barrier' in str(exc)
            checks['old_turn_never_started_playback'] = len(backend._handles) == 0

            class DelayedClient(SharedSpeechClient):
                def emit(self, *args, **kwargs):
                    entered.set()
                    release.wait(2)
                    return super().emit(*args, **kwargs)

            lane = LiveSpeechSubmission(DelayedClient(service.path))
            decision = make_strategy_decision(state=state, code='ERS_LOW', priority=60, title='ers', detail='')
            lane.emit(decision, state=state)
            assert entered.wait(1)
            stopper.emit_control_query_bundle(state=state, bundle={'structured_query': {'query_kind': 'stop'}, 'input_event': build_snapshot_query_input_event(state=state, query_kind='stop').to_dict()})
            release.set()
            until = time.monotonic() + 1
            receipts = []
            while time.monotonic() < until:
                receipts = lane.snapshot()['receipts']
                if receipts: break
                time.sleep(.005)
            checks['queued_before_stop_rejected_after_delay'] = bool(receipts) and 'speech_cancelled_by_stop_barrier' in receipts[0].get('error', '')
            checks['old_queue_never_started_playback'] = len(backend._handles) == 0
            result = client.emit_query_response(state=state, query_kind='fuel_status')
            checks['new_request_after_stop_can_play'] = result['output_lifecycle']['event']['event_type'] == 'start' and len(backend._handles) == 1
            # Missing/future timestamps cannot bypass the local service boundary.
            for label, stamp in [('missing', None), ('future', speech_time() + 10), ('nan', float('nan'))]:
                request = dict(version='speech-ipc-v1', request_id=label, expires_at=time.time()+1,
                    method='emit_query_response', params={'state': client._state(state), 'query_kind': 'fuel_status'})
                if stamp is not None: request['produced_at_monotonic'] = stamp
                try:
                    service.dispatch(request)
                    checks[label + '_timestamp_rejected'] = False
                except ValueError:
                    checks[label + '_timestamp_rejected'] = True
        finally:
            release.set()
            if lane is not None: checks['submission_worker_closed'] = lane.close()
            checks['service_closed'] = service.close()
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())

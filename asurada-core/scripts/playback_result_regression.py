import subprocess
import sys
from dataclasses import replace
from asurada.output import ConsoleVoiceOutput
from asurada.tts_backends import MacOSSayBackend, VoiceSidecarSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.audio_agent_client import AudioPlaybackResult, VoiceSidecarClient
from asurada.voice_sidecar_protocol import TtsRenderResponse
from phase3_voice_input_regression import _make_state, _make_turn
from regression_support import emit_result, runtime_clock


@runtime_clock(1777100000000)
def run():
    checks = {}
    state = _make_state()
    class ProcessBackend(MacOSSayBackend):
        code = 0
        def start(self, job):
            return subprocess.Popen([sys.executable, '-c', f'raise SystemExit({self.code})'])
    for code in (0, 7):
        backend = ProcessBackend(); backend.code = code
        output = ConsoleVoiceOutput(backend=backend)
        coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
        coordinator.process_completed_turn(state=state, turn=replace(_make_turn('后车差距'), turn_id=f'exit:{code}'),
            voice_output=output, render=False)
        output._active_handle.wait(timeout=3)
        event = output.tick()['event']
        coordinator.refresh_delivery(state=state, voice_output=output)
        checks[f'exit_{code}_terminal'] = event['event_type'] == ('complete' if code == 0 else 'failed')
        checks[f'exit_{code}_history'] = coordinator.conversation_context.snapshot()['last_response']['metadata']['delivery_status'] == ('completed' if code == 0 else 'failed')
        checks[f'exit_{code}_ownership_released'] = output._active_envelope is None and not coordinator.delivery_context.requests
        if code:
            checks['failure_not_repeat_history'] = output._last_completed_envelope is None
    class FailedClient:
        def play_tts(self, **kwargs):
            raise RuntimeError('fixture sidecar failure')
    sidecar = object.__new__(VoiceSidecarSpeechBackend)
    sidecar._client = FailedClient()
    output = ConsoleVoiceOutput(backend=sidecar)
    output.emit_query_response(state=state, query_kind='rear_gap', render=False)
    output._active_handle.thread.join(3)
    result = output.tick()
    checks['sidecar_thread_failure_propagates'] = (result['event']['event_type'] == 'failed'
        and result['event']['metadata']['reason'] == 'sidecar_playback_failed')
    checks['no_false_complete_event'] = [r['event']['event_type'] for r in output.read_events()['events']] == ['start', 'failed']
    for status, size, expected in [('played', 20, 'complete'), ('completed', 0, 'failed'),
            ('unsupported', 20, 'failed'), ('accepted', 20, 'failed'), ('failed', 0, 'failed'),
            ('played', 0, 'failed'), ('played', True, 'failed'), ('played', -1, 'failed')]:
        class ResultClient:
            def play_tts(self, **kwargs):
                return AudioPlaybackResult(status=status, player_binary='fixture', audio_format='wav', audio_bytes=size, metadata={})
        sidecar._client = ResultClient()
        output = ConsoleVoiceOutput(backend=sidecar)
        output.emit_query_response(state=state, query_kind='rear_gap', render=False)
        output._active_handle.thread.join(3)
        checks[f'result_{status}_{size}'] = output.tick()['event']['event_type'] == expected
    class MissingResult:
        def play_tts(self, **kwargs): return None
    sidecar._client = MissingResult()
    output = ConsoleVoiceOutput(backend=sidecar)
    output.emit_query_response(state=state, query_kind='rear_gap', render=False)
    output._active_handle.thread.join(3)
    checks['missing_result_not_success'] = output.tick()['event']['event_type'] == 'failed'
    class Meter:
        def clear(self, **kwargs): pass
    actual_client = object.__new__(VoiceSidecarClient)
    actual_client.voice_meter = Meter()
    class EmptyAudioClient:
        def play_tts(self, **kwargs):
            return actual_client.play_rendered_tts(response=TtsRenderResponse(
                status='completed', audio_base64=None, audio_format='wav', sample_rate_hz=16000),
                cancellation=kwargs['cancellation'])
    sidecar._client = EmptyAudioClient()
    output = ConsoleVoiceOutput(backend=sidecar)
    output.emit_query_response(state=state, query_kind='rear_gap', render=False)
    output._active_handle.thread.join(3)
    checks['actual_unplayable_response_reaches_failed_event'] = output.tick()['event']['event_type'] == 'failed'
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(run())

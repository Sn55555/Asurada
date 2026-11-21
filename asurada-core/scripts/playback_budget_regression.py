import base64
import json
import sys
from unittest.mock import patch
from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.voice_sidecar_protocol import (
    TtsRenderRequest, TtsStreamStart, TtsAudioFrame, TtsStreamEnd,
    build_tts_stream_start_envelope, build_tts_audio_frame_envelope, build_tts_stream_end_envelope)
from regression_support import emit_result


def run():
    client = VoiceSidecarClient(VoiceSidecarClientConfig('http://fixture.invalid', timeout_ms=30, playback_timeout_ms=1500))
    request = TtsRenderRequest(text='fixture', persona_id='fixture', voice_profile_id='fixture')
    envelopes = [build_tts_stream_start_envelope(TtsStreamStart('completed', 'wav', 16000)),
        build_tts_audio_frame_envelope(TtsAudioFrame(1, base64.b64encode(b'fixture').decode(), 7)),
        build_tts_stream_end_envelope(TtsStreamEnd('completed', 1, 7))]
    options = []
    def stream(*args, **kwargs):
        options.append(kwargs)
        yield from (json.dumps(envelope.to_dict()).encode() for envelope in envelopes)
    # This process accepts bytes and waits; it never opens an audio device.
    with patch('asurada.audio_agent_client.iter_http_lines', side_effect=stream), patch(
            'asurada.audio_agent_client._resolve_stream_audio_player',
            return_value=(sys.executable, ('-c', 'import sys,time;sys.stdin.buffer.read();time.sleep(.12)'))):
        result = client.play_tts(request=request)
    checks = {'playback_outlives_network_timeout': result.status == 'played' and result.audio_bytes == 7,
              'network_idle_limits_preserved': options[0]['connect_timeout_s'] == .03 and options[0]['read_timeout_s'] == .03,
              'explicit_positive_budget_required': False}
    try: client.play_tts(request=request, timeout_ms=0)
    except ValueError: checks['explicit_positive_budget_required'] = True
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'fixture stream plus actual non-audio process; no audible playback'}


if __name__ == '__main__': emit_result(run())

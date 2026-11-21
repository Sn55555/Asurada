import json
from unittest.mock import patch
from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.task_runtime import TaskContext, TaskCancelled
from asurada.voice_sidecar_protocol import (
    TtsRenderRequest, TtsRenderResponse, TtsStreamStart, TtsStreamEnd, TtsAudioFrame, build_tts_audio_frame_envelope,
    build_tts_render_response_envelope, build_tts_stream_start_envelope, build_tts_stream_end_envelope)
from regression_support import emit_result


def run():
    client = VoiceSidecarClient(VoiceSidecarClientConfig(base_url='http://fixture.invalid', timeout_ms=1000))
    request = TtsRenderRequest(text='test', persona_id='asurada_default', voice_profile_id='asurada_cn_ai_v1', audio_format='pcm_s16le')
    context = TaskContext.start('tts-client', 500)
    response = TtsRenderResponse(status='error', audio_base64=None, audio_format='wav', sample_rate_hz=16000, metadata={})
    with patch('asurada.cancellable_http.request_json', return_value=build_tts_render_response_envelope(response).to_dict()) as transport:
        client.render_tts(request=request, context=context)
    checks = {'buffered_context_forwarded': transport.call_args.kwargs['context'] is context}
    start = TtsStreamStart(status='completed', audio_format='pcm_s16le', sample_rate_hz=16000, metadata={})
    end = TtsStreamEnd(status='completed', total_frames=1, total_audio_bytes=2, metadata={})
    frame = TtsAudioFrame(sequence_id=1, audio_base64='AQA=', audio_bytes=2)
    lines = [json.dumps(envelope.to_dict()).encode() for envelope in (
        build_tts_stream_start_envelope(start), build_tts_audio_frame_envelope(frame), build_tts_stream_end_envelope(end))]
    closed = []; captured = []
    def stream(*args, **kwargs):
        captured.append(kwargs)
        try: yield from lines
        finally: closed.append(True)
    with patch('asurada.audio_agent_client.iter_http_lines', side_effect=stream):
        result = client.stream_tts(request=request, context=context, timeout_ms=100)
    options = captured[0]
    checks['stream_budget_and_cancellation_shared'] = options['context'].cancellation is context.cancellation and options['context'].deadline <= context.deadline and options['context'].remaining() <= .1
    checks['budget_header_enabled'] = options['propagate_budget'] is True and options['trust_env'] is False
    checks['stream_parsed_and_closed'] = result[0].status == 'completed' and closed == [True]
    context.cancel()
    with patch('asurada.cancellable_http.connection_route', side_effect=AssertionError('cancelled request opened connection')):
        try: client.stream_tts(request=request, context=context); checks['cancel_before_connect'] = False
        except TaskCancelled: checks['cancel_before_connect'] = True
    return {'passed': all(checks.values()), 'checks': checks, 'scope': 'client transport contract; no HTTP listener or playback'}


if __name__ == '__main__': emit_result(run())

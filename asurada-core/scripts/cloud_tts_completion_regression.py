import base64
import json
from unittest.mock import patch
from regression_support import emit_result
from asurada.task_runtime import TaskContext
from asurada.voice_sidecar_protocol import TtsRenderRequest
from asurada.voice_sidecar_tts import DoubaoStreamingHttpSidecarTtsRenderer


def run():
    renderer = DoubaoStreamingHttpSidecarTtsRenderer('http://fixture.invalid/tts','fixture','fixture','fixture','fixture')
    request = TtsRenderRequest(text='test',persona_id='asurada_default',voice_profile_id='asurada_cn_ai_v1',audio_format='pcm_s16le')
    audio = b'\x01\x00' * 20
    def event(code, body):
        return [f'event: {code}'.encode(), ('data: '+json.dumps(body)).encode(), b'']
    frame = event(352, {'code': 0, 'data': base64.b64encode(audio).decode()})
    terminal = event(152, {'code': 20000000})
    cases = {'missing_finish':frame,'empty_success':terminal,
             'cancelled':frame+event(151,{'code':0}),
             'failed':frame+event(153,{'code':0}),
             'wrong_finish_status':frame+event(152,{'code':0}),
             'non_object':frame+[b'data: []',b'']+terminal,
             'corrupt_utf8':frame+[b'data: {"message":"\xff"}',b'']+terminal,
             'malformed_json':frame+[b'data: {broken}',b'']+terminal}
    checks = {}
    for mode in ('stream','buffered'):
        for name, lines in [('valid',frame+terminal), *cases.items()]:
            closed = []
            def source(*args, **kwargs):
                try: yield from lines
                finally: closed.append(True)
            with patch('asurada.voice_sidecar_tts.iter_http_lines', side_effect=source):
                try:
                    context = TaskContext.start(name,1000)
                    if mode == 'stream':
                        result = b''.join(renderer.stream_render(request,frame_size_bytes=16,context=context).iter_chunks())
                        valid = result == audio
                    else:
                        result = renderer.render(request,context=context)
                        valid = result.status == 'completed' and bool(result.audio_base64)
                except (ValueError,RuntimeError):
                    checks[mode+'_'+name] = name != 'valid' and bool(closed)
                else:
                    checks[mode+'_'+name] = name == 'valid' and valid and bool(closed)
    return {'passed':all(checks.values()),'checks':checks,'scope':'renderer buffer and stream entrypoints with protocol lines; real HTTP-body truncation separately covered by socketpair regression'}


if __name__ == '__main__': emit_result(run())

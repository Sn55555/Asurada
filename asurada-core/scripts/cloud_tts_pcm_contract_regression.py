import base64
from io import BytesIO
import json
from unittest.mock import patch
import wave
from regression_support import emit_result
from asurada.voice_sidecar_tts import DoubaoStreamingHttpSidecarTtsRenderer
from asurada.voice_sidecar_protocol import TtsRenderRequest


def renderer(**kwargs):
    return DoubaoStreamingHttpSidecarTtsRenderer('http://fixture.invalid/tts','fixture','fixture','fixture','fixture',**kwargs)


def wire(chunks):
    for chunk in chunks:
        yield b'event: 352'
        yield ('data: '+json.dumps({'code':0,'data':base64.b64encode(chunk).decode()})).encode()
        yield b''
    yield b'event: 152'
    yield b'data: {"code":20000000}'
    yield b''


def run():
    request=TtsRenderRequest(text='test',persona_id='asurada_default',voice_profile_id='asurada_cn_ai_v1',audio_format='pcm_s16le')
    checks={}
    for fmt in ('mp3','wav','ogg_opus'):
        with patch('asurada.voice_sidecar_tts.iter_http_lines') as upstream:
            try: renderer(request_format=fmt).stream_render(request,frame_size_bytes=512)
            except ValueError as exc: checks['reject_'+fmt+'_before_network']=str(exc)=='doubao_streaming_requires_pcm' and not upstream.called
            else: checks['reject_'+fmt+'_before_network']=False
    pcm=b'\x01\x02'*700
    pieces=[pcm[:1],pcm[1:4],pcm[4:701],pcm[701:]]
    with patch('asurada.voice_sidecar_tts.iter_http_lines',side_effect=lambda *a,**k:wire(pieces)):
        chunks=list(renderer().stream_render(request,frame_size_bytes=513).iter_chunks())
    checks['fragmented_samples_preserve_all_bytes']=b''.join(chunks)==pcm
    checks['every_emitted_frame_is_sample_aligned']=all(len(c)%2==0 for c in chunks)
    with patch('asurada.voice_sidecar_tts.iter_http_lines',side_effect=lambda *a,**k:wire(pieces)):
        response=renderer().render(request)
    with wave.open(BytesIO(base64.b64decode(response.audio_base64)),'rb') as audio:
        checks['buffered_wav_matches_pcm']=audio.getnframes()==700 and audio.readframes(700)==pcm
    for mode in ('stream','buffered'):
        with patch('asurada.voice_sidecar_tts.iter_http_lines',side_effect=lambda *a,**k:wire([b'\x01\x02\x03'])):
            try:
                if mode=='stream':list(renderer().stream_render(request,frame_size_bytes=512).iter_chunks())
                else:renderer().render(request)
            except ValueError as exc:checks[mode+'_truncated_sample_rejected']=str(exc)=='tts_pcm_sample_truncated'
            else:checks[mode+'_truncated_sample_rejected']=False
    return {'passed':all(checks.values()),'checks':checks,'scope':'actual renderer and WAV wrapping with injected upstream protocol; no cloud or speaker'}


if __name__=='__main__':emit_result(run())

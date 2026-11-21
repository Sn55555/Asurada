from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import wave
from regression_support import emit_result
from asurada.voice_sidecar_tts import MacOSSaySidecarTtsRenderer, validate_wav_audio
from asurada.voice_sidecar_protocol import TtsRenderRequest


def wav(frames, rate=16000):
    output=BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
        audio.writeframes(b'\x01\x00'*frames)
    return output.getvalue()


def run():
    checks={}
    for name,payload in [('empty',wav(0)),('truncated',wav(20)[:-4]),('wrong_rate',wav(20,8000)),('invalid',b'invalid')]:
        try:
            validate_wav_audio(payload,sample_rate_hz=16000)
            checks[name+'_rejected']=False
        except ValueError:checks[name+'_rejected']=True
    validate_wav_audio(wav(20),sample_rate_hz=16000)
    checks['valid_pcm_accepted']=True
    renderer=MacOSSaySidecarTtsRenderer(say_binary='test-say',afconvert_binary='test-convert')
    request=TtsRenderRequest(text='test',persona_id='asurada_default',voice_profile_id='asurada_cn_ai_v1',audio_format='pcm_s16le')
    def empty_converter(command,**kwargs):
        if command[0]=='test-convert':Path(command[-1]).write_bytes(wav(0))
    with patch('asurada.voice_sidecar_tts.command_json_text',side_effect=empty_converter):
        for name,render in [('buffered',lambda:renderer.render(request)),('streamed',lambda:renderer.stream_render(request,frame_size_bytes=2048))]:
            try:render();checks[name+'_empty_not_completed']=False
            except ValueError:checks[name+'_empty_not_completed']=True
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

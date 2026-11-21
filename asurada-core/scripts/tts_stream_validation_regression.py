from copy import deepcopy
import json
from unittest.mock import patch
from asurada.tts_stream_validation import TtsStreamValidator
from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.voice_sidecar_protocol import (
    TtsRenderRequest, TtsStreamStart, TtsAudioFrame, TtsStreamEnd,
    build_tts_stream_start_envelope, build_tts_audio_frame_envelope, build_tts_stream_end_envelope)
from regression_support import emit_result


def run():
    events = [e.to_dict() for e in (
        build_tts_stream_start_envelope(TtsStreamStart('completed','wav',16000)),
        build_tts_audio_frame_envelope(TtsAudioFrame(1,'AQA=',2)),
        build_tts_stream_end_envelope(TtsStreamEnd('completed',1,2)))]
    checks = {}
    for name, mutate in [
        ('sequence_gap',lambda e:e[1]['payload'].update(sequence_id=2)),
        ('bool_sequence',lambda e:e[1]['payload'].update(sequence_id=True)),
        ('byte_mismatch',lambda e:e[1]['payload'].update(audio_bytes=3)),
        ('invalid_base64',lambda e:e[1]['payload'].update(audio_base64='!')),
        ('total_mismatch',lambda e:e[2]['payload'].update(total_audio_bytes=3)),
        ('missing_end',lambda e:e.pop()),
        ('duplicate_start',lambda e:e.insert(1,deepcopy(e[0]))),
        ('after_end',lambda e:e.append(deepcopy(e[1]))),
        ('empty_success',lambda e:(e.pop(1),e[1]['payload'].update(total_frames=0,total_audio_bytes=0))),
    ]:
        changed=deepcopy(events);mutate(changed);validator=TtsStreamValidator()
        try:
            for event in changed:validator.accept(event)
            validator.finish();checks[name]=False
        except ValueError:checks[name]=True
    client=VoiceSidecarClient(VoiceSidecarClientConfig('http://fixture.invalid'))
    request=TtsRenderRequest(text='test',persona_id='test',voice_profile_id='test')
    malformed=deepcopy(events);malformed[1]['payload']['sequence_id']=2
    def lines(*args,**kwargs):yield from (json.dumps(e).encode() for e in malformed)
    with patch('asurada.audio_agent_client.iter_http_lines',side_effect=lines), patch(
            'asurada.audio_agent_client._resolve_stream_audio_player',return_value=(None,())):
        for name,call in [('collection',client.stream_tts),('playback',client.play_tts)]:
            try:call(request=request);checks[name+'_rejects_bad_frame']=False
            except ValueError:checks[name+'_rejects_bad_frame']=True
    return {'passed':all(checks.values()),'checks':checks,'scope':'stream integrity and both client entrypoints; no audio device'}


if __name__=='__main__':emit_result(run())

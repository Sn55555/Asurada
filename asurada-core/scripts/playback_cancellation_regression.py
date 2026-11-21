import base64
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from regression_support import emit_result
from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.playback_control import PlaybackControl, PlaybackCancelled
from asurada.voice_sidecar_protocol import TtsRenderRequest, TtsRenderResponse


def run():
    client=VoiceSidecarClient(VoiceSidecarClientConfig(base_url='http://unused',timeout_ms=500))
    control=PlaybackControl(); started=threading.Event(); players=[]; failures=[]
    real_popen=subprocess.Popen
    def popen(*args,**kwargs):
        proc=real_popen(*args,**kwargs);players.append(proc);started.set();return proc
    def buffered():
        try:client.play_rendered_tts(response=TtsRenderResponse(status='completed',audio_base64=base64.b64encode(b'fake').decode(),audio_format='wav',sample_rate_hz=16000),cancellation=control)
        except Exception as exc:failures.append(exc)
    with patch('asurada.audio_agent_client._resolve_audio_player',return_value=(sys.executable,('-c','import time; time.sleep(10)'))),patch('asurada.audio_agent_client.subprocess.Popen',side_effect=popen):
        thread=threading.Thread(target=buffered);thread.start();ready=started.wait(1)
        t=time.monotonic();control.cancel();thread.join(1);elapsed=time.monotonic()-t
    checks={'player_cancelled':ready and not thread.is_alive() and players[0].poll() is not None and any(isinstance(e,PlaybackCancelled) for e in failures), 'cancel_prompt':elapsed<1}
    opened=threading.Event();closed=threading.Event();failures=[]
    def response(*args, **kwargs):
        context=kwargs['context']
        try:
            opened.set()
            while True:
                context.remaining();time.sleep(.005)
            yield b''
        finally:closed.set()
    control=PlaybackControl()
    def stream():
        try:client.play_streamed_tts(request=TtsRenderRequest(text='test',persona_id='test',voice_profile_id='test'),cancellation=control)
        except Exception as exc:failures.append(exc)
    with patch('asurada.audio_agent_client.iter_http_lines',side_effect=response):
        thread=threading.Thread(target=stream);thread.start();opened.wait(1);control.cancel();thread.join(1)
    checks['blocked_stream_closed']=closed.is_set() and not thread.is_alive() and any(isinstance(e,PlaybackCancelled) for e in failures)
    closed.clear(); control=PlaybackControl(); deadline_started=time.monotonic()
    with patch('asurada.audio_agent_client.iter_http_lines',side_effect=response):
        try:
            client.play_streamed_tts(request=TtsRenderRequest(text='test',persona_id='test',voice_profile_id='test'),
                                     timeout_ms=80,cancellation=control)
            checks['total_deadline_stops_read']=False
        except PlaybackCancelled:
            checks['total_deadline_stops_read']=closed.is_set() and control.event.is_set() and time.monotonic()-deadline_started<1
    return {'passed':all(checks.values()),'checks':checks,'analysis':{'cancel_elapsed_ms':round(elapsed*1000,2)}}

if __name__=='__main__':emit_result(run())

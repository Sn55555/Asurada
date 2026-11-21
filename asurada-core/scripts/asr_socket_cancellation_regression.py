import base64
import json
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from regression_support import emit_result
from asurada.voice_sidecar_asr import VoiceSidecarRealtimeAsrRecognizer
from asurada.task_runtime import TaskContext, TaskCancelled, TaskCapacityExceeded
from asurada.recognition_runtime import listen_with_context
from asurada.voice_sidecar_protocol import AsrRealtimePartial, build_asr_realtime_partial_envelope


def scenario(*, timeout=False, blocked_send=False):
    client, server = socket.socketpair()
    yielded = threading.Event(); closed = threading.Event(); errors=[]
    class Capture:
        config=SimpleNamespace(command_timeout_s=5)
        def iter_events(self, context=None):
            try:
                yielded.set()
                if blocked_send:
                    yield SimpleNamespace(type='chunk',audio_base64=base64.b64encode(b'x'*(2*1024*1024)).decode())
                else:
                    yield SimpleNamespace(type='end',status='recorded',metadata={},ended_at_ms=10)
            finally:closed.set()
    recognizer=VoiceSidecarRealtimeAsrRecognizer(audio_capture=Capture())
    context=TaskContext.start('asr-socket',100 if timeout else 3000)
    def work():
        try:recognizer.listen_once(context=context)
        except Exception as exc:errors.append(exc)
    with patch('asurada.voice_sidecar_asr.socket.create_connection',return_value=client):
        worker=threading.Thread(target=work)
        worker.start()
        try:
            assert yielded.wait(1)
            # Leave the peer open and silent; optionally also stop reading so send blocks.
            time.sleep(.03)
            started=time.monotonic()
            if not timeout:context.cancel()
            worker.join(1)
            stopped=not worker.is_alive()
            assert stopped
            server.settimeout(.2)
            while server.recv(65536):pass
            expected=TimeoutError if timeout else TaskCancelled
            return dict(returns=stopped and time.monotonic()-started<.5,
                        reason=bool(errors) and isinstance(errors[0],expected),
                        capture_closed=closed.is_set(),socket_closed=client.fileno()==-1,
                        threads_closed=not any(t.name in {'asr-socket-cancel','voice-sidecar-realtime-asr'} for t in threading.enumerate()))
        finally:
            context.cancel();server.close();worker.join(1)


def run():
    checks={}
    for name,kwargs in [('cancel_final',{}),('deadline_final',{'timeout':True}),('cancel_send',{'blocked_send':True})]:
        checks.update({name+'_'+key:value for key,value in scenario(**kwargs).items()})
    client,server=socket.socketpair()
    callback_entered=threading.Event();release=threading.Event();outcomes=[]
    def callback(text):callback_entered.set();release.wait(4)
    capture=SimpleNamespace(config=SimpleNamespace(command_timeout_s=5),
        iter_events=lambda **kwargs:iter([SimpleNamespace(type='end',status='recorded',metadata={},ended_at_ms=10)]))
    recognizer=VoiceSidecarRealtimeAsrRecognizer(audio_capture=capture,partial_callback=callback)
    context=TaskContext.start('callback-cancel',3000)
    def listen():
        try:listen_with_context(recognizer,context)
        except TaskCancelled:outcomes.append('cancelled')
    with patch('asurada.voice_sidecar_asr.socket.create_connection',return_value=client):
        worker=threading.Thread(target=listen);worker.start()
        try:
            server.sendall((json.dumps(build_asr_realtime_partial_envelope(AsrRealtimePartial('partial','zh-CN')).to_dict())+'\n').encode())
            assert callback_entered.wait(1)
            context.cancel();worker.join(.3)
            deadline=time.monotonic()+2
            while getattr(recognizer,'receiver_shutdown_confirmed',None) is not False and time.monotonic()<deadline:time.sleep(.01)
            checks['blocked_callback_reports_unconfirmed_receiver']=recognizer.receiver_shutdown_confirmed is False and outcomes==['cancelled']
            try:listen_with_context(recognizer,TaskContext.start('must-not-overlap',100));busy=False
            except TaskCapacityExceeded:busy=True
            checks['blocked_receiver_keeps_recognizer_slot']=busy
        finally:
            release.set();server.close();worker.join(1)
            deadline=time.monotonic()+1
            while not getattr(recognizer,'receiver_shutdown_confirmed',False) and time.monotonic()<deadline:time.sleep(.005)
        checks['released_callback_allows_confirmed_cleanup']=recognizer.receiver_shutdown_confirmed and client.fileno()==-1
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

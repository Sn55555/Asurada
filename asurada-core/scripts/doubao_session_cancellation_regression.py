import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from regression_support import emit_result
from asurada.voice_sidecar_asr import DoubaoRealtimeAsrStreamSession
from asurada.task_runtime import TaskContext, TaskCancelled
from phase3_doubao_realtime_asr_recognizer_regression import _build_ws_success_frame


class Closed(Exception): pass
class Timeout(Exception): pass


def run():
    checks={}
    backend=SimpleNamespace(url='wss://unused.invalid',connect_timeout_s=5,recv_timeout_s=2,name='fake',
        _build_full_request=lambda **kwargs:{'audio':{}},_build_headers=lambda:[])
    for phase in ('open_send','finish_recv','finish_deadline','late_connect','positive'):
        entered=threading.Event();abort=threading.Event();release=threading.Event();errors=[];results=[];timeouts=[]
        context=TaskContext.start(phase,100 if phase=='finish_deadline' else 2000)
        class WS:
            headers={}
            closed=False
            sent=0
            polls=0
            def settimeout(self,value): pass
            def send_binary(self,payload):
                self.sent+=1
                if phase=='open_send':
                    entered.set();abort.wait(3);raise Closed()
            def recv(self):
                entered.set()
                if phase=='positive':
                    self.polls+=1
                    if self.polls<3: raise Timeout()
                    return _build_ws_success_frame(-1,{'result':{'text':'final'}})
                abort.wait(3);raise Closed()
            def abort(self):abort.set()
            def shutdown(self):self.closed=True
        ws=WS()
        def connect(*args,**kwargs):
            timeouts.append(kwargs['timeout'])
            if phase=='late_connect':entered.set();release.wait(3)
            return ws
        module=SimpleNamespace(create_connection=connect,WebSocketTimeoutException=Timeout,WebSocketConnectionClosedException=Closed)
        session=DoubaoRealtimeAsrStreamSession(backend=backend,locale='zh-CN',context=context)
        def work():
            try:
                session.open()
                if phase not in ('open_send','late_connect'):
                    session.append_audio_chunk(b'audio')
                    results.append(session.finish(started_at_ms=1,ended_at_ms=2,capture_status='recorded'))
            except Exception as exc:errors.append(exc)
            finally:session.close()
        with patch.dict(sys.modules,websocket=module):
            worker=threading.Thread(target=work);worker.start()
            try:
                assert entered.wait(1)
                if phase not in ('positive','finish_deadline'):context.cancel()
                if phase=='late_connect':release.set()
                worker.join(1)
                checks[phase+'_closed']=not worker.is_alive() and ws.closed and (session._watcher is None or not session._watcher.is_alive())
                checks[phase+'_budget']=0<timeouts[0]<=2
                if phase=='positive':
                    checks['finish_poll_timeout_does_not_truncate_result']=not errors and results[0].transcript_text=='final' and ws.polls==3
                else:
                    checks[phase+'_no_late_result']=not results and isinstance(errors[0],TimeoutError if phase=='finish_deadline' else TaskCancelled)
                if phase=='late_connect':checks['cancelled_connect_sends_no_audio']=ws.sent==0
            finally:context.cancel();abort.set();release.set();worker.join(1)
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

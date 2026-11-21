import base64
import http.client
import json
import select
import socket
import threading
import time
from regression_support import emit_result
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from asurada.voice_sidecar_protocol import AsrTranscribeRequest, AsrTranscribeResponse, build_asr_transcribe_request_envelope


def run():
    checks={};entered=threading.Event();cancelled=threading.Event();release=threading.Event()
    class Backend:
        name='controlled-asr';supports_task_context=True
        cooperative=True
        calls=0
        def transcribe_audio(self, *, context, **kwargs):
            self.calls+=1;entered.set()
            if self.cooperative:
                context.cancellation.wait(2)
                if context.cancellation.is_set():cancelled.set()
                context.remaining()
            else:release.wait(3)
            return AsrTranscribeResponse(status='recognized',transcript_text='ok',confidence=1.,started_at_ms=1,ended_at_ms=2,locale='zh-CN',metadata={})
    backend=Backend()
    server=VoiceSidecarServer(config=VoiceSidecarServerConfig(host='127.0.0.1',port=0,asr_timeout_ms=70),asr_backend=backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    body=json.dumps(build_asr_transcribe_request_envelope(AsrTranscribeRequest(audio_base64=base64.b64encode(b'fake').decode(),audio_format='wav',locale='zh-CN')).to_dict())
    def connection():return http.client.HTTPConnection('127.0.0.1',server.listening_port,timeout=1)
    def call():
        conn=connection()
        try:
            conn.request('POST','/v1/asr/transcribe',body=body,headers={'Content-Type':'application/json'})
            response=conn.getresponse();response.read();return response.status
        finally:conn.close()
    try:
        conn=connection();conn.request('POST','/v1/asr/transcribe',body=body)
        assert entered.wait(1)
        conn.close()
        checks['disconnect_cancels_provider_context']=cancelled.wait(.3)
        # Non-cooperative provider calls must retain capacity after a 504.
        backend.cooperative=False
        statuses=[]
        # The just-cancelled cooperative call may still be returning from its wrapper.
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            status=call()
            if status==504:statuses.append(status);break
            time.sleep(.005)
        statuses.append(call())
        checks['two_slow_calls_return_deadline']=statuses==[504,504]
        before=backend.calls
        checks['timed_out_workers_still_hold_capacity']=call()==503 and backend.calls==before
        conn=connection();conn.request('GET','/healthz');response=conn.getresponse()
        checks['health_remains_available_during_asr_overload']=response.status==200;response.read();conn.close()
        release.set();deadline=time.monotonic()+1;status=None
        while time.monotonic()<deadline:
            status=call()
            if status==200:break
            time.sleep(.005)
        checks['capacity_recovers_after_actual_worker_exit']=status==200
        conn=connection();conn.putrequest('POST','/v1/asr/transcribe');conn.putheader('Content-Length',str(16*1024*1024+1));conn.endheaders()
        response=conn.getresponse();response.read();conn.close()
        checks['oversized_body_rejected_before_read']=response.status==400
        idle=[]
        try:
            idle=[socket.create_connection(('127.0.0.1',server.listening_port),timeout=1) for _ in range(24)]
            deadline=time.monotonic()+.5;readable=[]
            while len(readable)<8 and time.monotonic()<deadline:
                readable,_,_=select.select(idle,[],[],.01)
            rejected=sum(sock.recv(1)==b'' for sock in readable)
            checks['idle_connection_flood_is_bounded']=rejected>=8 and len(idle)-rejected<=16
        finally:
            for sock in idle:sock.close()
    finally:
        release.set();server.shutdown();thread.join(1)
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

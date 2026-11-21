import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import threading
import time
from regression_support import emit_result
from asurada.audio_agent_client import VoiceSidecarClient,VoiceSidecarClientConfig
from asurada.voice_sidecar_server import VoiceSidecarServer,VoiceSidecarServerConfig
from asurada.voice_sidecar_asr import DoubaoFlashHttpSidecarAsrBackend
from asurada.voice_sidecar_protocol import AsrTranscribeRequest
from asurada.task_runtime import TaskContext,TaskCancelled


def run():
    checks={};requests=[];block=threading.Event();entered=threading.Event();disconnected=threading.Event()
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((dict(self.headers),body))
            if block.is_set():
                entered.set();deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    ready,_,_=select.select([self.connection],[],[],.02)
                    if ready and self.connection.recv(1,socket.MSG_PEEK)==b'':disconnected.set();return
                return
            data=json.dumps({'result':{'text':'recognized locally','utterances':[]}}).encode()
            self.send_response(200)
            self.send_header('x-api-status-code','20000000');self.send_header('x-tt-logid','local-provider-id')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    cloud=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    cloud_thread=threading.Thread(target=cloud.serve_forever,daemon=True);cloud_thread.start()
    backend=DoubaoFlashHttpSidecarAsrBackend(url=f'http://127.0.0.1:{cloud.server_port}/recognize',resource_id='test-resource',
        app_key=None,access_key=None,api_key='test-key',boosting_table_id=None,boosting_table_name=None,
        user_id='test-user',request_model_name='test-model')
    sidecar=VoiceSidecarServer(config=VoiceSidecarServerConfig(host='127.0.0.1',port=0),asr_backend=backend)
    sidecar_thread=threading.Thread(target=sidecar.serve_forever,daemon=True);sidecar_thread.start()
    client=VoiceSidecarClient(VoiceSidecarClientConfig(f'http://127.0.0.1:{sidecar.listening_port}',timeout_ms=5000))
    request=AsrTranscribeRequest(audio_base64=base64.b64encode(b'fake-audio').decode(),audio_format='wav',locale='zh-CN')
    try:
        result=client.transcribe_asr(request=request,context=TaskContext.start('normal',2000))
        headers,body=requests[0];headers={k.lower():v for k,v in headers.items()}
        checks['real_provider_adapter_parses_case_insensitive_headers']=result.status=='recognized' and result.metadata['provider_request_id']=='local-provider-id'
        checks['provider_auth_and_resource_preserved']=headers['x-api-key']=='test-key' and headers['x-api-resource-id']=='test-resource' and bool(headers['x-api-request-id'])
        checks['internal_budget_header_not_sent_to_provider']='x-asurada-timeout-ms' not in headers
        checks['provider_audio_and_options_preserved']=base64.b64decode(body['audio']['data'])==b'fake-audio' and body['request']['model_name']=='test-model' and body['request']['locale']=='zh-CN'
        block.set();context=TaskContext.start('cancel-chain',2000);errors=[]
        def call():
            try:client.transcribe_asr(request=request,context=context)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=call);worker.start()
        assert entered.wait(1)
        started=time.monotonic();context.cancel();worker.join(.5)
        checks['client_cancel_returns_without_provider_result']=not worker.is_alive() and isinstance(errors[0],TaskCancelled)
        checks['cancel_propagates_through_sidecar_to_provider_socket']=disconnected.wait(.5) and time.monotonic()-started<.6
        deadline=time.monotonic()+1
        while any(t.name=='asr-http-cancel' for t in threading.enumerate()) and time.monotonic()<deadline:time.sleep(.005)
        checks['both_http_cancel_watchers_exit']=not any(t.name=='asr-http-cancel' for t in threading.enumerate())
    finally:
        sidecar.shutdown();sidecar_thread.join(1);cloud.shutdown();cloud.server_close();cloud_thread.join(1)
    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

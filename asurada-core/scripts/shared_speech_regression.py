import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from regression_support import emit_result
from asurada.speech_clock import speech_time
from phase3_voice_regression import FakeSpeechBackend,make_state,make_strategy_decision
from asurada.output import ConsoleVoiceOutput
from asurada.speech_service import SpeechService,read_message,write_message
from asurada.speech_client import SharedSpeechClient
from asurada.interaction import build_snapshot_query_input_event

CLIENT_CODE='''
import json,os
from asurada.app import AsuradaApp
from asurada.config import AppConfig
from asurada.speech_client import make_voice_output,SharedSpeechClient
from asurada.speech_driver import SpeechOutputDriver
from phase3_voice_regression import make_state,make_strategy_decision
mode=os.environ['TEST_SPEECH_ROLE']
client=AsuradaApp(AppConfig()).voice_output if mode=='core' else make_voice_output(backend_factory=lambda:(_ for _ in ()).throw(AssertionError('local player constructed')))
state=make_state()
code,priority=('ERS_LOW',60) if mode=='core' else ('LOW_FUEL',95)
decision=make_strategy_decision(state=state,code=code,priority=priority,title=code,detail='')
with SpeechOutputDriver(client):result=client.emit(decision,state=state,render=False)
print(json.dumps({'owner_pid':client.health()['pid'],'event':result['event']['event_type'],'proxy':isinstance(client,SharedSpeechClient),'debug_received':'output_lifecycle' in decision.debug}))
'''


def run():
    checks={}
    with TemporaryDirectory(dir='/tmp',prefix='asurada-speech-') as temp:
        path=Path(temp)/'voice.sock';backend=FakeSpeechBackend();service=SpeechService(path,output=ConsoleVoiceOutput(backend=backend)).start()
        try:
            results=[]
            for role in ('core','voice'):
                env=dict(os.environ,ASURADA_SPEECH_SOCKET=str(path),TEST_SPEECH_ROLE=role)
                process=subprocess.run([sys.executable,'-c',CLIENT_CODE],env=env,capture_output=True,text=True,timeout=30)
                if process.returncode:raise AssertionError(process.stderr)
                results.append(json.loads(process.stdout.splitlines()[-1]))
            checks['independent_clients_share_one_owner']=all(r['owner_pid']==os.getpid() and r['proxy'] and r['debug_received'] for r in results)
            checks['single_queue_across_client_exit']=len(backend._handles)==1 and service.output._active_envelope.job.action_code=='ERS_LOW' and service.output._pending_envelope.job.action_code=='LOW_FUEL'
            rival=SpeechService(path,output=ConsoleVoiceOutput(backend=FakeSpeechBackend()))
            try:rival.start();checks['second_owner_rejected']=False
            except BlockingIOError:checks['second_owner_rejected']=True
            backend.complete_all()
            end=time.monotonic()+.5
            while len(backend._handles)<2 and time.monotonic()<end:time.sleep(.01)
            checks['owner_clock_advances_without_clients']=len(backend._handles)==2 and service.output._active_envelope.job.action_code=='LOW_FUEL'
            client=SharedSpeechClient(path);state=make_state()
            old_client=SharedSpeechClient(path).bind_delivery(speech_time())
            client.emit_control_query_bundle(state=state,bundle={'structured_query':{'query_kind':'stop'},'input_event':build_snapshot_query_input_event(state=state,query_kind='stop').to_dict()},render=False)
            checks['remote_stop_clears_owner_queue']=service.output._active_envelope is None and service.output._pending_envelope is None
            count=len(backend._handles)
            try:
                old_client.emit_query_response(state=state,query_kind='fuel_status',render=False)
                checks['other_client_old_work_rejected']=False
            except RuntimeError as exc:
                checks['other_client_old_work_rejected']='speech_cancelled_by_stop_barrier' in str(exc) and len(backend._handles)==count
            decision=make_strategy_decision(state=state,code='ERS_LOW',priority=60,title='ers',detail='')
            request=dict(version='speech-ipc-v1',request_id='same-request',expires_at=time.time()+1.,method='emit',params=dict(state=client._state(state,decision),messages=[m.__dict__ for m in decision.messages],debug=decision.debug))
            request['produced_at_monotonic']=speech_time()
            def wire(payload):
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
                    connection.settimeout(1.);connection.connect(str(path));write_message(connection,payload);return read_message(connection)
            count=len(backend._handles);first=wire(request);second=wire(request)
            checks['retry_same_request_does_not_repeat_playback']=first==second and first['ok'] and len(backend._handles)==count+1 and service.output._pending_envelope is None
            expired=wire(dict(request,request_id='expired',expires_at=time.time()-1))
            checks['expired_request_does_not_enqueue']=not expired['ok'] and service.output._pending_envelope is None
            conflict=wire(dict(request,method='is_playing'))
            checks['same_id_different_request_rejected']=not conflict['ok'] and 'identity_conflict' in conflict['error']
            checks['socket_only_owner_accessible']=path.stat().st_mode&0o777==0o600
        finally:checks['service_shutdown_confirmed']=service.close()
        try:SharedSpeechClient(path);checks['missing_owner_no_local_fallback']=False
        except (OSError,ConnectionError):checks['missing_owner_no_local_fallback']=True
        class Unconfirmed(FakeSpeechBackend):
            def stop(self,handle):pass
        backend=Unconfirmed();pending=SpeechService(path,output=ConsoleVoiceOutput(backend=backend)).start()
        client=SharedSpeechClient(path);state=make_state()
        response=client.emit_query_response(state=state,query_kind='fuel_status',render=False)
        checks['remote_structured_query_uses_owner']=response['output_lifecycle']['event']['event_type']=='start' and len(backend._handles)==1
        checks['unconfirmed_stop_keeps_owner_lock']=pending.close() is False and pending.lock is not None
        candidate=SpeechService(path,output=ConsoleVoiceOutput(backend=FakeSpeechBackend()))
        try:candidate.start();checks['replacement_waits_for_stop_ack']=False
        except BlockingIOError:checks['replacement_waits_for_stop_ack']=True
        backend.complete_all();checks['ack_allows_owner_shutdown']=pending.close()
        daemon_path=Path(temp)/'daemon.sock'
        daemon=subprocess.Popen([sys.executable,'-m','asurada.speech_service','--socket',str(daemon_path)],env=dict(os.environ,ASURADA_TTS_BACKEND='null'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            end=time.monotonic()+3.;info=None
            while time.monotonic()<end and daemon.poll() is None:
                try:info=SharedSpeechClient(daemon_path).health();break
                except OSError:time.sleep(.02)
            checks['standalone_service_entrypoint']=info is not None and info['pid']==daemon.pid and info['backend']=='NullSpeechBackend'
        finally:
            daemon.terminate()
            try:stdout,stderr=daemon.communicate(timeout=3)
            except subprocess.TimeoutExpired:daemon.kill();stdout,stderr=daemon.communicate();raise
        checks['standalone_shutdown_cleans_socket']=daemon.returncode==0 and not daemon_path.exists()

    return dict(passed=all(checks.values()),checks=checks)


if __name__=='__main__':emit_result(run())

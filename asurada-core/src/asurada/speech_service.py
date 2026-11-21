"""Local shared speech owner. JSON IPC; clients never instantiate a player."""
from __future__ import annotations

from .limits import IPC_MAX_MESSAGE_BYTES
from collections import OrderedDict
from copy import deepcopy
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import socketserver
import stat
import struct
import threading
import time
from .speech_clock import speech_time
import uuid

from .decode import decode_snapshot
from .fuel_feedback import fuel_observation
from .wing_damage import wing_advice_current
from .models import StrategyDecision, StrategyMessage
from .output import ConsoleVoiceOutput
from .personality_llm import PersonalityLlm
from .speech_driver import SpeechOutputDriver
from .published_session import PublishedSessionProbe
from .interaction import build_snapshot_query_input_event
from .speech_applicability import (
    validate_assist_applicability,
    validate_pit_follow_up_applicability,
    validate_query_applicability,
    validate_strategy_applicability,
)

MAX_MESSAGE=IPC_MAX_MESSAGE_BYTES


def read_message(connection,deadline=None):
    deadline=deadline if deadline is not None else time.monotonic()+1.
    def exact(size):
        data=bytearray()
        while len(data)<size:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError("speech_frame_timeout")
            connection.settimeout(remaining)
            chunk=connection.recv(size-len(data))
            if not chunk:raise ConnectionError('speech_ipc_closed')
            data.extend(chunk)
        return bytes(data)
    length=struct.unpack('!I',exact(4))[0]
    if length>MAX_MESSAGE:raise ValueError('speech_message_too_large')
    return json.loads(exact(length),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite_json')))


def write_message(connection,payload):
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    if len(encoded)>MAX_MESSAGE:raise ValueError('speech_message_too_large')
    connection.sendall(struct.pack('!I',len(encoded))+encoded)


class _Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    block_on_close=False
    request_queue_size=8
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(1.)
        try:
            result=self.server.owner.dispatch(read_message(self.request))
            write_message(self.request,{'ok':True,'result':result})
        except Exception as error:
            try:write_message(self.request,{'ok':False,'error':f'{type(error).__name__}: {error}'})
            except (OSError,ValueError):pass


class SpeechService:
    def __init__(self,path,*,output=None,session_source=None):
        self.path=Path(path).absolute()
        self.output=output or ConsoleVoiceOutput(personality_llm=PersonalityLlm.from_env())
        self.output.output_session_id="voice-output:service:"+uuid.uuid4().hex
        self._dispatch_lock=threading.Lock()
        self._results=OrderedDict()
        self._stop_barrier = speech_time()
        self.session_source = Path(session_source).resolve() if session_source is not None else None
        self.session_probe = PublishedSessionProbe(self.session_source) if self.session_source else None
        self.output.personality_live = self.session_probe is not None
        self._authority_stop = threading.Event()
        self._authority_thread = None
        self._last_delivery_state = None
        self.authority_error = None
        self.server=None;self.thread=None;self.driver=None;self.lock=None;self._closing=False
    def start(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=self.path.with_suffix(self.path.suffix+'.lock').open('a')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                info=self.path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('speech_socket_path_not_owned_socket')
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                    probe.settimeout(.2)
                    try:probe.connect(str(self.path))
                    except ConnectionRefusedError:pass
                    else:raise RuntimeError('speech_socket_already_served')
                self.path.unlink()
            self.server=_Server(str(self.path),_Handler)
            os.chmod(self.path,0o600)
            self.server.slots=threading.BoundedSemaphore(8);self.server.owner=self
            self.driver=SpeechOutputDriver(self.output);self.driver.__enter__()
            self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
            self.thread.start()
            if self.session_probe is not None:
                self._authority_thread = threading.Thread(target=self._watch_authority, name='speech-authority', daemon=True)
                self._authority_thread.start()
        except BaseException:
            if self.server is not None:
                self.server.server_close();self.path.unlink(missing_ok=True);self.server=None
            self.lock.close();self.lock=None
            raise
        return self
    def _watch_authority(self):
        while not self._authority_stop.wait(.05):
            if not self._dispatch_lock.acquire(timeout=.05):
                continue
            try:
                state = self._last_delivery_state
                if state is None:
                    continue
                try:
                    row = self.session_probe.read_snapshot()
                    valid = (row['session_uid'], row['session_epoch']) == (state.session_uid, state.session_epoch)
                    evidence = self.output.pit_feedback
                    if valid and evidence is not None and evidence.needs_snapshot(row["source_timestamp_ms"]):
                        self.output.observe_pit_evidence(decode_snapshot(row))
                except (ValueError, OSError):
                    valid = False
                if not valid:
                    self.output.end_pit_evidence("telemetry_authority_lost")
                    event = build_snapshot_query_input_event(state=state, query_kind='stop')
                    self.output.emit_control_query_bundle(state=state, bundle={
                        'structured_query': {'query_kind': 'stop'}, 'input_event': event.to_dict()}, render=False)
                    self._last_delivery_state = None
                self.authority_error = None
            except Exception as exc:
                self.authority_error = f'{type(exc).__name__}: {exc}'
            finally:
                self._dispatch_lock.release()
    def _validate_delivery(self, method, params, produced, *, delivery=True, job=None):
        if self._closing: raise RuntimeError("speech_service_closing")
        if delivery:
            if (isinstance(produced, bool) or not isinstance(produced, (int, float)) or
                    not math.isfinite(produced) or produced > speech_time()):
                raise ValueError('invalid_speech_production_time')
            if produced <= self._stop_barrier:
                raise ValueError('speech_cancelled_by_stop_barrier')
        if self.session_probe is not None and (method == 'bind_session' or delivery):
            state_row = params.get('state')
            if not isinstance(state_row, dict):
                raise ValueError('speech_requires_session_snapshot')
            latest_row = self.session_probe.read_snapshot()
            authoritative = (latest_row['session_uid'], latest_row['session_epoch'])
            incoming = (state_row.get('session_uid'), state_row.get('session_epoch'))
            if incoming != authoritative:
                raise ValueError('speech_session_not_authoritative')
            incoming_state = decode_snapshot(state_row)
            if method == 'emit_personality_reply' or (job is not None and job.metadata.get('optional_personality')):
                latest = decode_snapshot(latest_row)
                if job is not None and job.metadata.get("experience_kind"):
                    if not self.output._radio_experience.applicable(latest, job, live=True):
                        raise ValueError("driver_experience_no_longer_applicable")
                elif job is not None:
                    if not self.output._personality_dialogue.context_current(latest, live=True):
                        raise ValueError('personality_context_no_longer_safe')
                    if method == 'emit':
                        hint = latest.personality
                        context = job.metadata["personality"]
                        if (hint.event_id != context["event_id"] or hint.opportunity != context["opportunity"]
                                or hint.stage != context["stage"] or hint.opportunity_age_s is None
                                or not 0 <= hint.opportunity_age_s <= 2):
                            raise ValueError('personality_opportunity_changed')
                if method == 'emit_personality_reply':
                    return latest
            if method in ('emit_query_response', 'emit_voice_query_bundle'):
                validate_query_applicability(method, params, incoming_state, decode_snapshot(latest_row))
            elif method == 'emit':
                latest = decode_snapshot(latest_row)
                validate_strategy_applicability(params, incoming_state, latest)
                if job is not None:
                    validate_assist_applicability(job, incoming_state, latest)
                    validate_pit_follow_up_applicability(job, incoming_state, latest)
                    if job.metadata.get("fuel_original") and fuel_observation(latest) is None:
                        raise ValueError("fuel_advice_no_longer_safe")
                    if job.metadata.get("wing_levels") and not wing_advice_current(latest, job):
                        raise ValueError("wing_advice_no_longer_applicable")
            return incoming_state

    def dispatch(self,request):
        if request.get('version')!='speech-ipc-v1':raise ValueError('unsupported_speech_protocol')
        request_id=request['request_id']
        if not isinstance(request_id,str) or not 1<=len(request_id)<=128:raise ValueError('invalid_request_id')
        fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True,allow_nan=False).encode()).hexdigest()
        expires=request['expires_at']
        if not isinstance(expires,(int,float)) or isinstance(expires,bool):raise ValueError('invalid_deadline')
        if not self._dispatch_lock.acquire(timeout=max(0,min(1.,expires-time.time()))):raise TimeoutError('speech_dispatch_busy')
        try:
            if self._closing:raise RuntimeError("speech_service_closing")
            if request_id in self._results:
                old_fingerprint,value=self._results[request_id]
                if old_fingerprint!=fingerprint:raise ValueError('speech_request_identity_conflict')
                return value
            if expires<=time.time():raise TimeoutError('speech_request_expired')
            method=request['method'];params=request.get('params',{})
            delivery = method in ('emit', 'emit_query_response', 'emit_voice_query_bundle', 'emit_control_query_bundle', 'emit_personality_reply')
            stop = (method == 'emit_control_query_bundle' and
                    (params.get('bundle', {}).get('structured_query') or {}).get('query_kind') in ('stop', 'cancel'))
            guard = None
            if delivery and not stop or method == 'bind_session':
                frozen_params = deepcopy(params)
                produced = request.get('produced_at_monotonic')
                self._last_delivery_state = self._validate_delivery(method, frozen_params, produced, delivery=delivery)
                if delivery:
                    guard = lambda job: self._validate_delivery(method, frozen_params, produced, job=job)
            with self.output.submission_guard(guard):
                if method=='health':
                    value=dict(protocol='speech-ipc-v1',pid=os.getpid(),backend=type(self.output.backend).__name__,scope=self.output._session_scope,driver_error=self.driver.last_error,
                               session_source=str(self.session_source) if self.session_source else None, authority_error=self.authority_error,
                               playback_health=dict(self.output.playback_health),
                               personality_enabled=self.output._personality_dialogue.enabled,
                               humor_enabled=self.output._personality_dialogue.humor_enabled,
                               personality_llm=self.output.personality_model_status(),
                               pit_evidence=self.output.pit_feedback.store.worker.snapshot() if self.output.pit_feedback else None,
                               retired_identities=self.output._retired_sessions.health())
                elif method == 'personality_preferences':
                    value = self.output.configure_personality(params)
                elif method == 'personality_control_status':
                    if params:
                        raise ValueError("unexpected_personality_status_parameters")
                    value = self.output.personality_control_status()
                elif method == 'report_microphone':
                    state, ttl = params.get("state"), params.get("ttl_s")
                    if state not in ("unknown", "idle", "listening") or type(ttl) not in (int, float) or not 0 <= ttl <= 60:
                        raise ValueError("invalid_microphone_status")
                    self.output.report_microphone(state, ttl)
                    value = True
                elif method == 'radio_preference':
                    if set(params) != {"enabled"} or type(params["enabled"]) is not bool:
                        raise ValueError("invalid_radio_preference")
                    value = self.output.set_radio_preference(params["enabled"])
                elif method == 'correct_last_brake_habit':
                    if params:
                        raise ValueError("unexpected_habit_parameters")
                    value = self.output.correct_last_brake_habit()
                elif method == 'reserve_query_turn':
                    token = params.get('token')
                    duration = params.get('duration')
                    if (not isinstance(token, str) or not 1 <= len(token) <= 128
                            or type(duration) not in {int, float} or not 0 <= duration <= 60):
                        raise ValueError('invalid_speech_query_reservation')
                    self.output.reserve_query_turn(token, speech_time() + duration if duration else None)
                    value = True
                elif method == 'record_pit_feedback':
                    text, token, sent = params.get('text'), params.get('turn_id'), params.get('state')
                    if (not isinstance(text, str) or len(text) > 100 or not isinstance(token, str)
                            or not 1 <= len(token) <= 128 or not isinstance(sent, dict)):
                        raise ValueError('invalid_pit_feedback_request')
                    if self.session_probe is None:
                        value = {"status": "rejected", "reason": "pit_feedback_requires_live_session"}
                    else:
                        latest = self.session_probe.read_snapshot()
                        asked = decode_snapshot(sent)
                        age_ms = time.time() * 1000 - latest['source_timestamp_ms']
                        if (asked.session_uid, asked.session_epoch) != (latest['session_uid'], latest['session_epoch']) or not 0 <= age_ms <= 3000:
                            value = {"status": "rejected", "reason": "pit_feedback_snapshot_stale"}
                        else:
                            value = self.output.record_pit_feedback(state=decode_snapshot(latest), text=text, request_id=token,
                                **({"interpretation": params["interpretation"]} if "interpretation" in params else {}))
                elif method == 'emit_personality_reply':
                    text, token = params.get('text'), params.get('turn_id')
                    if not isinstance(text, str) or not isinstance(token, str) or not 1 <= len(token) <= 128:
                        raise ValueError('invalid_personality_request')
                    state = self._last_delivery_state if self.session_probe else decode_snapshot(params['state'])
                    value = self.output.emit_personality_reply(state=state, text=text, request_id=token, render=False)
                elif method=='is_playing':value=self.output.is_playing()
                elif method=='playback_status':value=self.output.playback_status()
                elif method=='events':
                    if set(params)-{'cursor','limit'}:raise ValueError('unknown_event_parameters')
                    value=self.output.read_events(**params)
                elif method=='bind_session':value=self.output.bind_session(decode_snapshot(params['state']))
                elif method=='emit':
                    state=decode_snapshot(params['state']) if params.get('state') is not None else None
                    decision=StrategyDecision([StrategyMessage(**m) for m in params['messages']],debug=params['debug'],record=state.decision_record if state else None)
                    lifecycle=self.output.emit(decision,state=state,render=False)
                    value=dict(lifecycle=lifecycle,debug=decision.debug)
                elif method in ('emit_query_response','emit_voice_query_bundle','emit_control_query_bundle'):
                    allowed={'state','primary_message','query_kind'} if method=='emit_query_response' else {'state','primary_message','bundle'}
                    if set(params)-allowed:raise ValueError('unknown_speech_parameters')
                    args=dict(params);args['state']=decode_snapshot(args['state'])
                    if args.get('primary_message') is not None:args['primary_message']=StrategyMessage(**args['primary_message'])
                    if stop:
                        # Serialized with delivery. Keep the barrier even if physical
                        # playback stop fails, so earlier work cannot start anew.
                        self._stop_barrier = speech_time()
                    value=getattr(self.output,method)(**args,render=False)
                else:raise ValueError('unsupported_speech_operation')
            # Read pages have no side effect to deduplicate. Caching 128 large
            # pages would multiply the event stream's bounded retention.
            if method != 'events':
                self._results[request_id]=(fingerprint,value)
            while len(self._results)>128:self._results.popitem(last=False)
            return value
        finally:self._dispatch_lock.release()
    def close(self):
        self._closing=True
        self._authority_stop.set()
        if self._authority_thread is not None:
            self._authority_thread.join(1)
            if self._authority_thread.is_alive():return False
        if self.server is not None:
            self.server.shutdown();self.server.server_close();self.server=None
            if self.thread:self.thread.join(1)
            self.path.unlink(missing_ok=True)
        if not self._dispatch_lock.acquire(timeout=1.):return False
        try:
            stopped=self.driver.close() if self.driver else True
            # A replacement owner must not start before playback stop is confirmed.
            if stopped and self.lock:self.lock.close();self.lock=None
            return stopped
        finally:self._dispatch_lock.release()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket',required=True,type=Path)
    parser.add_argument('--sidecar-tts',action='store_true')
    parser.add_argument('--session-source',type=Path)
    parser.add_argument('--pit-evidence-db',type=Path)
    args=parser.parse_args()
    from .tts_backends import VoiceSidecarSpeechBackend
    from .personality_runtime import personality_enabled
    from .pit_feedback import PitEvidenceStore, PitFeedbackTracker, evidence_path
    store = PitEvidenceStore(args.pit_evidence_db or evidence_path()) if args.session_source and personality_enabled() else None
    output=ConsoleVoiceOutput(backend=VoiceSidecarSpeechBackend() if args.sidecar_tts else None,
                              pit_feedback=PitFeedbackTracker(store) if store else None,
                              personality_llm=PersonalityLlm.from_env())
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    service=SpeechService(args.socket,output=output,session_source=args.session_source).start()
    try:stop.wait()
    finally:
        while not service.close():
            time.sleep(.1)  # Keep the ownership lock until the backend acknowledges stop.
        if store is not None:
            output.end_pit_evidence("service_stopped")
            store.close()


if __name__=='__main__':main()

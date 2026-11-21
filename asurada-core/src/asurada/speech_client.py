"""ConsoleVoiceOutput-compatible local IPC client, with no local fallback player."""
from dataclasses import asdict
from copy import copy
import os
import math
import socket
import time
from .speech_clock import speech_time
import uuid
from .models import StrategyDecision
from .snapshot_contract import snapshot_payload
from .speech_service import read_message,write_message


class SharedSpeechClient:
    externally_driven=True
    def __init__(self,path,*,timeout_s=1.):
        self.path=str(path);self.timeout_s=timeout_s
        self.delivery_started_at = None
        self.health()  # Fail startup rather than silently create a second owner.
    def bind_delivery(self, started_at):
        client = copy(self)
        client.delivery_started_at = started_at
        return client
    def call(self,method,params=None):
        request=dict(version='speech-ipc-v1',request_id=uuid.uuid4().hex,expires_at=time.time()+self.timeout_s,method=method,params=params or {})
        request['produced_at_monotonic'] = self.delivery_started_at if self.delivery_started_at is not None else speech_time()
        deadline=time.monotonic()+self.timeout_s
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout_s);connection.connect(self.path)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError("speech_request_timeout")
            connection.settimeout(remaining)
            write_message(connection,request);reply=read_message(connection,deadline=deadline)
        if not reply.get('ok'):raise RuntimeError(reply.get('error','speech_service_failed'))
        return reply['result']
    def _state(self,state,decision=None):
        return snapshot_payload(state,decision or StrategyDecision([],record=state.decision_record))
    def health(self):return self.call('health')
    def personality_preferences(self, **changes):
        return self.call('personality_preferences', changes)
    def set_radio_preference(self, enabled):
        return self.call('radio_preference', {'enabled': enabled})
    def correct_last_brake_habit(self):
        return self.call('correct_last_brake_habit')
    def reserve_query_turn(self, token, expires_at):
        duration = max(0., min(60., expires_at - speech_time())) if expires_at is not None else 0.
        client = copy(self)
        client.timeout_s = min(self.timeout_s, .075)
        return client.call('reserve_query_turn', {'token': token, 'duration': duration})
    def record_pit_feedback(self, *, state, text, request_id, interpretation=None):
        return self.call('record_pit_feedback', {'state': self._state(state), 'text': text, 'turn_id': request_id,
            **({'interpretation': interpretation} if interpretation is not None else {})})
    def emit_personality_reply(self, *, state, text, request_id, render=True):
        return self.call('emit_personality_reply', {'state': self._state(state), 'text': text, 'turn_id': request_id})
    def bind_session(self,state):return self.call('bind_session',{'state':self._state(state)})
    def is_playing(self):return self.playback_status()['status'] != 'idle'
    def playback_status(self):
        reader = copy(self)
        reader.timeout_s = min(self.timeout_s, .05)
        try:
            result = reader.call('playback_status')
            if (not isinstance(result, dict) or result.get('version') != 'playback-status-v1'
                    or result.get('status') not in {'idle', 'playing', 'unknown'}):
                raise ValueError('invalid_playback_status')
            return result
        except Exception as exc:
            return {'version': 'playback-status-v1', 'status': 'unknown', 'error_type': type(exc).__name__}
    def read_events(self, *, cursor=None, limit=64, timeout_s=.1):
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('invalid_event_read_timeout')
        reader = copy(self)
        reader.timeout_s = min(self.timeout_s, timeout_s)
        return reader.call('events', dict(cursor=cursor, limit=limit))
    def shutdown(self,**kwargs):return True  # Detach; other clients still own work.
    def emit(self,decision,*,state=None,render=True):
        result=self.call('emit',dict(state=self._state(state,decision) if state else None,messages=[asdict(m) for m in decision.messages],debug=decision.debug))
        decision.debug.update(result['debug']);return result['lifecycle']
    def _query(self,method,*,state,primary_message=None,render=True,**kwargs):
        params=dict(state=self._state(state),primary_message=asdict(primary_message) if primary_message else None,**kwargs)
        if 'bundle' in params and hasattr(params['bundle'],'to_dict'):params['bundle']=params['bundle'].to_dict()
        return self.call(method,params)
    def emit_query_response(self,**kwargs):return self._query('emit_query_response',**kwargs)
    def emit_voice_query_bundle(self,**kwargs):return self._query('emit_voice_query_bundle',**kwargs)
    def emit_control_query_bundle(self,**kwargs):return self._query('emit_control_query_bundle',**kwargs)


def make_voice_output(*,backend_factory=None, shared=True):
    path=os.getenv('ASURADA_SPEECH_SOCKET') if shared else None
    if path:return SharedSpeechClient(path)
    from .output import ConsoleVoiceOutput
    return ConsoleVoiceOutput(backend=backend_factory() if backend_factory else None)

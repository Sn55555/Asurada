"""Local turn cancellation and ordered stop versus query delivery.

The input thread can cancel a turn while recognition or explanation is blocked.
Cancellation discards its result; it does not claim to terminate the microphone
or a non-cooperative backend. Delivery and stop share one ordering lock.
"""
import threading
import time
from .speech_clock import speech_time
import uuid
from .task_runtime import TaskContext
from .interaction import build_snapshot_query_input_event
from .runtime_context import RuntimeContextDetector


class VoiceTurnInterruption:
    def __init__(self, output, *, scope_probe=None):
        self.output = output
        self._delivery = threading.Lock()
        self._state_lock = threading.Lock()
        self._context = None
        self._scope = None
        self.scope_probe = scope_probe
        self.cancel_reason = None
        self._closed = threading.Event()
        self._watcher = None

    def __enter__(self):
        if self.scope_probe is not None:
            self._watcher = threading.Thread(target=self._watch, name='voice-session-watch', daemon=True)
            self._watcher.start()
        return self

    def __exit__(self, *args):
        self._closed.set()
        with self._state_lock:
            if self._context is not None:
                self._context.cancel()
        if self._watcher is not None:
            self._watcher.join(1)

    def begin(self, *, timeout_ms=60000, state=None):
        with self._delivery, self._state_lock:
            if self._context is not None:
                self._context.cancel()
            self._context = TaskContext.start('voice-turn:'+uuid.uuid4().hex, timeout_ms)
            self._delivery_started_at = speech_time()
            self._scope = ((state.session_uid, state.session_epoch) if state is not None and
                           RuntimeContextDetector().detect(state=state).racing_active else None)
            self.cancel_reason = None
            return self._context

    def _check_scope(self, context):
        with self._state_lock:
            if context is not self._context or context.cancellation.is_set():
                return
            expected = self._scope
        if expected is None or self.scope_probe is None:
            return
        try:
            observed = self.scope_probe()
            reason = 'session_scope_changed' if observed != expected else None
        except Exception as exc:
            reason = f'published_session_unavailable:{type(exc).__name__}: {exc}'
        if reason is not None:
            with self._state_lock:
                if self._context is context:
                    self.cancel_reason = reason
                    context.cancel()

    def _watch(self):
        while not self._closed.wait(.05):
            with self._state_lock:
                context = self._context
            if context is not None:
                self._check_scope(context)

    def stop(self, state):
        with self._state_lock:
            if self._context is not None:
                self._context.cancel()
        # Cancellation is immediate, even if an already-submitted output call
        # must finish before stop can clear it. New delivery rechecks under lock.
        with self._delivery:
            with self._state_lock:
                if self._context is not None:
                    self._context.cancel()
            event = build_snapshot_query_input_event(state=state, query_kind='stop')
            return self.output.emit_control_query_bundle(state=state, bundle={
                'structured_query': {'query_kind':'stop'}, 'input_event':event.to_dict()}, render=False)

    def output_for(self, context):
        owner = self
        with self._state_lock:
            if context is not self._context:
                context.cancel()
            started = self._delivery_started_at
        output = self.output.bind_delivery(started) if hasattr(self.output, 'bind_delivery') else self.output
        class Output:
            def read_events(self, **kwargs):
                return output.read_events(**kwargs)
            def _emit(self, method, **kwargs):
                with owner._delivery:
                    owner._check_scope(context)
                    context.remaining()
                    return getattr(output, method)(**kwargs)
            def emit_voice_query_bundle(self, **kwargs):
                return self._emit('emit_voice_query_bundle', **kwargs)
            def emit_control_query_bundle(self, **kwargs):
                return self._emit('emit_control_query_bundle', **kwargs)
            def emit_personality_reply(self, **kwargs):
                return self._emit('emit_personality_reply', **kwargs)
            def record_pit_feedback(self, **kwargs):
                return self._emit('record_pit_feedback', **kwargs)
            def set_radio_preference(self, enabled):
                return self._emit('set_radio_preference', enabled=enabled)
            def correct_last_brake_habit(self):
                return self._emit('correct_last_brake_habit')
            def reserve_query_turn(self, token, expires_at):
                reserve = getattr(output, 'reserve_query_turn', None)
                if reserve is not None:
                    reserve(token, expires_at)
        return Output()

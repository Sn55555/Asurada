"""Apply stop, repeat and assist controls to the same queue owner."""
from __future__ import annotations
from .capability_definitions import capability_speech_priority
from typing import Any
from .interaction import InteractionInputEvent, OutputLifecycleEvent, SpeechJob, build_asr_stage_event
from .models import SessionState, StrategyMessage
from .output_contracts import _SpeechEnvelope, _OutputProcessingResult, _serialized


class OutputControlAdapter:
    """Apply stop, repeat and assist controls to the same queue owner. Shared state lives on ConsoleVoiceOutput."""

    @_serialized
    def emit_control_query_bundle(
        self,
        *,
        state: SessionState,
        bundle: Any,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> dict[str, Any]:
        """Execute one control query against the current output queue."""

        bundle_dict = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
        input_event = dict(bundle_dict.get("input_event") or {})
        structured_query = dict(bundle_dict.get("structured_query") or {})
        query_route = dict(bundle_dict.get("query_route") or {})
        confirmation_policy = dict(bundle_dict.get("confirmation_policy") or {})
        task_handle = dict(bundle_dict.get("task_handle") or {})
        normalization_event = dict(bundle_dict.get("normalization_event") or {})
        query_kind = str(structured_query.get("query_kind") or "")
        # Stop/cancel act on the current queue even if telemetry is stale.
        if query_kind not in {"stop","cancel"} and not self.bind_session(state):
            return self._scope_rejection()

        if query_kind == "repeat_last":
            return self._emit_repeat_last_control(
                state=state,
                input_event=input_event,
                structured_query=structured_query,
                query_route=query_route,
                confirmation_policy=confirmation_policy,
                task_handle=task_handle,
                normalization_event=normalization_event,
                render=render,
                extra_debug={
                    "fast_intent": bundle_dict.get("fast_intent"),
                    "voice_turn": bundle_dict.get("voice_turn"),
                },
            )

        if query_kind in {"stop", "cancel"}:
            self._radio_experience.cancel()
            self._cancel_personality_generation("voice_control_" + query_kind)
            return self._emit_stop_cancel_control(
                query_kind=query_kind,
                input_event=input_event,
                structured_query=structured_query,
                query_route=query_route,
                confirmation_policy=confirmation_policy,
                task_handle=task_handle,
                normalization_event=normalization_event,
                render=render,
                extra_debug={
                    "fast_intent": bundle_dict.get("fast_intent"),
                    "voice_turn": bundle_dict.get("voice_turn"),
                },
            )

        if query_kind in {
            "arm_brake_point_assist",
            "cancel_brake_point_assist",
            "brake_point_assist_status",
            "brake_point_assist_earlier",
            "brake_point_assist_later",
            "enable_corner_gear_assist",
            "disable_corner_gear_assist",
            "corner_gear_assist_status",
            "enable_attack_mode",
            "disable_attack_mode",
            "attack_mode_status",
        }:
            return self._emit_voice_assist_control(
                state=state,
                query_kind=query_kind,
                input_event=input_event,
                structured_query=structured_query,
                query_route=query_route,
                confirmation_policy=confirmation_policy,
                task_handle=task_handle,
                normalization_event=normalization_event,
                render=render,
                extra_debug={
                    "fast_intent": bundle_dict.get("fast_intent"),
                    "voice_turn": bundle_dict.get("voice_turn"),
                },
            )

        return self._emit_prepared_query(
            state=state,
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            primary_message=primary_message,
            render=render,
            extra_debug={
                "fast_intent": bundle_dict.get("fast_intent"),
                "voice_turn": bundle_dict.get("voice_turn"),
            },
        )


    def _emit_repeat_last_control(
        self,
        *,
        state: SessionState,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        render: bool,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.tick()
        base = self._latest_repeatable(state)
        if base is None:
            return self._emit_control_idle(
                input_event=input_event,
                structured_query=structured_query,
                query_route=query_route,
                confirmation_policy=confirmation_policy,
                task_handle=task_handle,
                normalization_event=normalization_event,
                render=render,
                reason="no_repeatable_output",
                extra_debug=extra_debug,
            )

        repeated = _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(input_event.get("turn_id") or "turn:unknown"),
                request_id=str(input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="query_response",
                action_code="QUERY_REPEAT_LAST",
                priority=capability_speech_priority("repeat_last"),
                speak_text=base.job.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "query_response",
                    "query_kind": "repeat_last",
                    "repeated_action_code": base.job.action_code,
                    "repeated_output_event_id": base.job.output_event_id,
                    "repeatable": False,
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=input_event,
            task_handle=task_handle,
            repeat_target=base.job,
        )
        result = self._process_submission(
            submitted_envelope=repeated,
            fallback_input_event=input_event,
            fallback_task_handle=task_handle,
        )
        debug = self._build_control_debug(
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            result=result,
            extra_debug=extra_debug,
        )
        if render:
            event = result.lifecycle_event
            if event.event_type == "start":
                print(f"[ASURADA][QUERY][REPEAT] {event.speak_text}")
            elif event.event_type == "enqueue":
                print(f"[ASURADA][QUERY][REPEAT-QUEUE] {event.speak_text}")
            elif event.event_type == "replace_pending":
                print(f"[ASURADA][QUERY][REPEAT-REPLACE] {event.speak_text}")
            elif event.event_type == "suppress":
                print(f"[ASURADA][QUERY][REPEAT-SUPPRESS] {event.metadata.get('reason', 'suppressed')}")
        return debug


    def _emit_voice_assist_control(
        self,
        *,
        state: SessionState,
        query_kind: str,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        render: bool,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if query_kind == "arm_brake_point_assist":
            control_result = self._brake_point_assist.arm_next_long_straight(state=state)
            action_code = "CONTROL_BRAKE_POINT_ASSIST_ON"
        elif query_kind == "cancel_brake_point_assist":
            control_result = self._brake_point_assist.cancel()
            action_code = "CONTROL_BRAKE_POINT_ASSIST_OFF"
        elif query_kind == "brake_point_assist_earlier":
            control_result = self._brake_point_assist.tune_earlier()
            action_code = "CONTROL_BRAKE_POINT_ASSIST_TUNE_EARLIER"
        elif query_kind == "brake_point_assist_later":
            control_result = self._brake_point_assist.tune_later()
            action_code = "CONTROL_BRAKE_POINT_ASSIST_TUNE_LATER"
        elif query_kind == "enable_corner_gear_assist":
            control_result = self._corner_gear_assist.enable(state=state)
            action_code = "CONTROL_CORNER_GEAR_ASSIST_ON"
        elif query_kind == "disable_corner_gear_assist":
            control_result = self._corner_gear_assist.disable()
            action_code = "CONTROL_CORNER_GEAR_ASSIST_OFF"
        elif query_kind == "corner_gear_assist_status":
            control_result = self._corner_gear_assist.status()
            action_code = "CONTROL_CORNER_GEAR_ASSIST_STATUS"
        elif query_kind == "enable_attack_mode":
            control_result = self._attack_mode.enable(state=state)
            action_code = "CONTROL_ATTACK_MODE_ON"
        elif query_kind == "disable_attack_mode":
            control_result = self._attack_mode.disable()
            action_code = "CONTROL_ATTACK_MODE_OFF"
        elif query_kind == "attack_mode_status":
            control_result = self._attack_mode.status()
            action_code = "CONTROL_ATTACK_MODE_STATUS"
        else:
            control_result = self._brake_point_assist.status()
            action_code = "CONTROL_BRAKE_POINT_ASSIST_STATUS"

        envelope = _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(input_event.get("turn_id") or "turn:unknown"),
                request_id=str(input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="query_response",
                action_code=action_code,
                priority=capability_speech_priority(query_kind),
                speak_text=control_result.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "query_response",
                    "query_kind": query_kind,
                    "control_reason": control_result.reason,
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=input_event,
            task_handle=task_handle,
        )
        result = self._process_submission(
            submitted_envelope=envelope,
            fallback_input_event=input_event,
            fallback_task_handle=task_handle,
        )
        debug = self._build_control_debug(
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            result=result,
            extra_debug=extra_debug,
        )
        debug["control_result"] = {
            "request_id": input_event['request_id'],
            "query_kind": query_kind,
            "armed": getattr(control_result, "armed", getattr(control_result, "enabled", False)),
            "reason": control_result.reason,
            "speak_text": control_result.speak_text,
        }
        if render:
            print(f"[ASURADA][QUERY][{query_kind.upper()}] {control_result.speak_text}")
        return debug


    def _emit_stop_cancel_control(
        self,
        *,
        query_kind: str,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        render: bool,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lifecycle_event: OutputLifecycleEvent
        event_envelope: _SpeechEnvelope | None
        cancelled_output_event: OutputLifecycleEvent | None = None
        cancelled_envelope: _SpeechEnvelope | None = None

        if query_kind == "stop":
            active = self._active_envelope
            pending = self._pending_envelope
            if active is not None:
                active.job.metadata["cancel_requested"] = True
                active.job.metadata['cancel_requested_by_request_id'] = input_event['request_id']
                stopped = self._request_stop_confirmation(active)
                if stopped:
                    self._active_handle = None
                    self._active_envelope = None
                lifecycle_event = self._build_event_from_envelope(
                    active,
                    "cancel" if stopped else "cancel_requested",
                    metadata={"reason": "voice_control_stop", "source_kind": active.job.source_kind},
                )
                event_envelope = active
                if pending is not None:
                    self._pending_envelope = None
                    cancelled_envelope = pending
                    cancelled_output_event = self._build_event_from_envelope(
                        pending,
                        "cancel",
                        metadata={"reason": "voice_control_stop", "source_kind": pending.job.source_kind},
                    )
            elif pending is not None:
                self._pending_envelope = None
                lifecycle_event = self._build_event_from_envelope(
                    pending,
                    "cancel",
                    metadata={"reason": "voice_control_stop_pending", "source_kind": pending.job.source_kind},
                )
                event_envelope = pending
            else:
                return self._emit_control_idle(
                    input_event=input_event,
                    structured_query=structured_query,
                    query_route=query_route,
                    confirmation_policy=confirmation_policy,
                    task_handle=task_handle,
                    normalization_event=normalization_event,
                    render=render,
                    reason="nothing_to_stop",
                    extra_debug=extra_debug,
                )
        else:
            pending = self._pending_envelope
            active = self._active_envelope
            if pending is not None:
                self._pending_envelope = None
                lifecycle_event = self._build_event_from_envelope(
                    pending,
                    "cancel",
                    metadata={"reason": "voice_control_cancel_pending", "source_kind": pending.job.source_kind},
                )
                event_envelope = pending
            elif active is not None and active.job.cancelable:
                active.job.metadata["cancel_requested"] = True
                active.job.metadata['cancel_requested_by_request_id'] = input_event['request_id']
                stopped = self._request_stop_confirmation(active)
                if stopped:
                    self._active_handle = None
                    self._active_envelope = None
                lifecycle_event = self._build_event_from_envelope(
                    active,
                    "cancel" if stopped else "cancel_requested",
                    metadata={"reason": "voice_control_cancel_active", "source_kind": active.job.source_kind},
                )
                event_envelope = active
            else:
                return self._emit_control_idle(
                    input_event=input_event,
                    structured_query=structured_query,
                    query_route=query_route,
                    confirmation_policy=confirmation_policy,
                    task_handle=task_handle,
                    normalization_event=normalization_event,
                    render=render,
                    reason="nothing_to_cancel",
                    extra_debug=extra_debug,
                )

        result = _OutputProcessingResult(
            lifecycle_event=lifecycle_event,
            event_envelope=event_envelope,
            cancelled_output_event=cancelled_output_event,
            cancelled_envelope=cancelled_envelope,
        )
        debug = self._build_control_debug(
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            result=result,
            extra_debug=extra_debug,
        )
        if render:
            print(f"[ASURADA][QUERY][{query_kind.upper()}] {result.lifecycle_event.metadata.get('reason', query_kind)}")
        return debug


    def _emit_control_idle(
        self,
        *,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        render: bool,
        reason: str,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = _OutputProcessingResult(
            lifecycle_event=self._build_fallback_event(
                event_type="idle",
                input_event=input_event,
                task_handle=task_handle,
                action_code="NONE",
                metadata={"reason": reason, "source_kind": "query_response"},
            ),
            event_envelope=None,
        )
        debug = self._build_control_debug(
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            result=result,
            extra_debug=extra_debug,
        )
        if render:
            print(f"[ASURADA][QUERY][IDLE] {reason}")
        return debug


    def _build_control_debug(
        self,
        *,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        result: _OutputProcessingResult,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        debug: dict[str, Any] = {
            "interaction_input_event": input_event,
            "structured_query": structured_query,
            "query_route": query_route,
            "confirmation_policy": confirmation_policy,
            "task_handle": task_handle,
            "voice_pipeline_log": {
                "asr": build_asr_stage_event(InteractionInputEvent(**input_event)).to_dict(),
                "query_normalization": normalization_event,
                "query_route": query_route,
                "confirmation_policy": confirmation_policy,
            },
        }
        if extra_debug:
            debug.update(extra_debug)
        self._write_debug_payload(debug=debug, result=result)
        if structured_query.get('query_kind') in {'stop', 'cancel'}:
            events = [result.lifecycle_event]
            if result.cancelled_output_event is not None:
                events.append(result.cancelled_output_event)
            targets = [dict(request_id=event.request_id, output_event_id=event.output_event_id,
                            status='cancelled' if event.event_type == 'cancel' else 'cancellation_requested',
                            error_type=event.metadata.get('stop_error_type'))
                       for event in events if event.event_type in {'cancel', 'cancel_requested'}]
            debug['control_result'] = dict(version='control-result-v1', request_id=input_event['request_id'],
                query_kind=structured_query['query_kind'], targets=targets,
                status=('pending' if any(t['status'] == 'cancellation_requested' for t in targets)
                        else 'completed' if targets else 'no_op'),
                reason=result.lifecycle_event.metadata.get('reason'))
        return debug



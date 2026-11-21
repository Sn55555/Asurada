"""Normalize snapshot/voice query input into the shared playback queue."""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from uuid import uuid4
from .interaction import (
    InteractionInputEvent,
    StructuredQuerySchema,
    build_asr_stage_event,
    build_confirmation_policy,
    build_query_normalization_event,
    build_snapshot_query_input_event,
    build_structured_query_schema,
    build_task_handle,
    render_structured_query_response,
    route_structured_query,
)
from .models import SessionState, StrategyMessage
from .output_contracts import _OutputProcessingResult, _serialized, strategy_speech_band
from .personality_dialogue import banter_requested, joke_opt_out_requested
from .capabilities.pit import explain_pit_with_cooperation


class OutputQueryAdapter:
    """Normalize snapshot/voice query input into the shared playback queue. Shared state lives on ConsoleVoiceOutput."""

    @_serialized
    def emit_query_response(
        self,
        *,
        state: SessionState,
        query_kind: str,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> dict[str, Any]:
        """Emit one structured query response through the same speech queue."""

        if not self.bind_session(state):
            return self._scope_rejection()

        input_event = build_snapshot_query_input_event(
            state=state,
            query_kind=query_kind,
            primary_message=primary_message,
        )
        # Explicit requests can be simultaneous against the same telemetry frame.
        identity = uuid4().hex
        input_event = replace(input_event, request_id=f"{input_event.request_id}:{identity}",
                              turn_id=f"{input_event.turn_id}:{identity}")
        structured_query = build_structured_query_schema(input_event)
        query_route = route_structured_query(structured_query)
        confirmation_policy = build_confirmation_policy(
            input_event=input_event,
            schema=structured_query,
            route=query_route,
        )
        task_handle = build_task_handle(
            input_event=input_event,
            route=query_route,
            confirmation_policy=confirmation_policy,
        )
        return self._emit_prepared_query(
            state=state,
            input_event=input_event.to_dict(),
            structured_query=structured_query.to_dict(),
            query_route=query_route.to_dict(),
            confirmation_policy=confirmation_policy.to_dict(),
            task_handle=task_handle.to_dict(),
            normalization_event=build_query_normalization_event(input_event).to_dict(),
            primary_message=primary_message,
            render=render,
        )


    @_serialized
    def emit_voice_query_bundle(
        self,
        *,
        state: SessionState,
        bundle: Any,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> dict[str, Any]:
        """Emit one pre-normalized voice query bundle through the unified queue."""

        if not self.bind_session(state):
            return self._scope_rejection()

        bundle_dict = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
        input_event = dict(bundle_dict.get("input_event") or {})
        structured_query = dict(bundle_dict.get("structured_query") or {})
        query_route = dict(bundle_dict.get("query_route") or {})
        confirmation_policy = dict(bundle_dict.get("confirmation_policy") or {})
        task_handle = dict(bundle_dict.get("task_handle") or {})
        normalization_event = dict(bundle_dict.get("normalization_event") or {})
        response_override = dict(bundle_dict.get("response_override") or {})
        llm_explainer = dict(bundle_dict.get("llm_explainer") or {})
        extra_debug = {
            "fast_intent": bundle_dict.get("fast_intent"),
            "voice_turn": bundle_dict.get("voice_turn"),
        }
        if llm_explainer:
            extra_debug["llm_explainer"] = llm_explainer
        return self._emit_prepared_query(
            state=state,
            input_event=input_event,
            structured_query=structured_query,
            query_route=query_route,
            confirmation_policy=confirmation_policy,
            task_handle=task_handle,
            normalization_event=normalization_event,
            response_override=response_override,
            primary_message=primary_message,
            render=render,
            extra_debug=extra_debug,
        )


    @_serialized
    def emit_personality_reply(self, *, state, text, request_id, render=True):
        if not banter_requested(text) or not self.bind_session(state):
            return self._scope_rejection()
        event = {"request_id": request_id, "query_text": text}
        if joke_opt_out_requested(text):
            # Consume an actually finished joke before resolving the deictic request.
            self.tick()
            line = self._personality_dialogue.mute_last_joke()
            if line is not None:
                pending = self._pending_envelope
                if pending is not None and pending.job.metadata.get("joke_line") == line:
                    self._pending_envelope = None
                    self._publish_transition(pending, "cancel", "specific_joke_muted")
                active = self._active_envelope
                if active is not None and active.job.metadata.get("joke_line") == line:
                    self._request_personality_stop(active, "specific_joke_muted")
                generation = self._personality_generation
                if generation is not None and generation.job.metadata.get("joke_line") == line:
                    self._cancel_personality_generation("specific_joke_muted")
            debug = {}
            event = self._build_fallback_event(event_type="suppress", input_event=event, task_handle={},
                action_code="PERSONALITY_BANTER", metadata={"reason": "specific_joke_muted" if line else "no_completed_joke"})
            self._write_debug_payload(debug=debug, result=_OutputProcessingResult(event, None))
            return debug
        envelope = self._personality_dialogue.opportunity(
            state, live=self.personality_live, event=event, task={},
            output_id=self._next_output_event_id, persona=self.persona, direct=True)
        if envelope is None:
            result_event = self._build_fallback_event(
                event_type="suppress", input_event=event, task_handle={}, action_code="PERSONALITY_BANTER",
                metadata={"reason": "humor_unavailable"})
            debug = {}
            self._write_debug_payload(debug=debug, result=_OutputProcessingResult(result_event, None))
            return debug
        debug = {}
        result = self._process_submission(
            submitted_envelope=envelope, fallback_input_event=event, fallback_task_handle={})
        self._write_debug_payload(debug=debug, result=result)
        return debug

    def _emit_prepared_query(
        self,
        *,
        state: SessionState,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        primary_message: StrategyMessage | None,
        render: bool,
        response_override: dict[str, Any] | None = None,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = StructuredQuerySchema(**structured_query)
        default_speak_text, default_action_code = render_structured_query_response(
            state=state,
            schema=schema,
            primary_message=primary_message,
        )
        speak_text = str((response_override or {}).get("speak_text") or default_speak_text)
        action_code = str((response_override or {}).get("action_code") or default_action_code)
        protected = primary_message is not None and strategy_speech_band(primary_message.code) >= 3
        cooperation_id = None
        context = schema.metadata.get("semantic_metadata") or {}
        self.observe_attack_choice(state, context, input_event.get("created_at_ms"))
        if (context.get("radio_topic") == "attack" and context.get("radio_act") in {"hold", "decline"}
                and schema.query_kind != "radio_reply"):
            speak_text = "好，先不攻。" + speak_text
        if (not protected and not response_override and self._personality_dialogue.enabled
                and schema.query_kind == "why_not_pit"
                and not (context.get("strategy_follow_up_target") or {}).get("expired")):
            explanation = explain_pit_with_cooperation(state)
            if explanation is not None:
                speak_text, cooperation_id = explanation
        if not protected and not response_override and query_route.get("lane") != "control":
            experience = getattr(self, "_radio_experience", None)
            if experience is not None:
                speak_text = experience.maybe_defer(
                    state, schema.query_kind, speak_text, request_id=str(input_event["request_id"]))
        speak_text, personality = self._personality_dialogue.personalize(
            state, speak_text, protected=protected or bool(response_override) or query_route.get("lane") == "control")
        if cooperation_id is not None:
            personality["pit_cooperation_id"] = cooperation_id
        envelope = self._build_query_envelope(
            input_event=input_event,
            task_handle=task_handle,
            schema=structured_query,
            speak_text=speak_text,
            action_code=action_code,
            personality=personality,
        )
        result = self._process_submission(
            submitted_envelope=envelope,
            fallback_input_event=input_event,
            fallback_task_handle=task_handle,
        )
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
        if response_override:
            debug["response_override"] = response_override
            debug["voice_pipeline_log"]["llm_sidecar"] = {
                "used": True,
                "status": response_override.get("status"),
                "source": response_override.get("source"),
                "backend_name": response_override.get("backend_name"),
                "fallback_reason": response_override.get("fallback_reason"),
            }
        elif extra_debug and extra_debug.get("llm_explainer"):
            llm_result = ((extra_debug.get("llm_explainer") or {}).get("result") or {})
            debug["voice_pipeline_log"]["llm_sidecar"] = {
                "used": False,
                "status": llm_result.get("status"),
                "source": "llm_sidecar",
                "backend_name": llm_result.get("backend_name"),
                "fallback_reason": llm_result.get("fallback_reason"),
            }
        self._write_debug_payload(debug=debug, result=result)
        if render:
            event = result.lifecycle_event
            if event.event_type == "start":
                print(f"[ASURADA][QUERY] {event.speak_text}")
            elif event.event_type == "enqueue":
                print(f"[ASURADA][QUERY][QUEUE] {event.speak_text}")
            elif event.event_type == "replace_pending":
                print(f"[ASURADA][QUERY][QUEUE-REPLACE] {event.speak_text}")
            elif event.event_type in {"suppress", "failed"}:
                print(f"[ASURADA][QUERY][{event.event_type.upper()}] {event.metadata.get('reason', event.event_type)}")
        return debug



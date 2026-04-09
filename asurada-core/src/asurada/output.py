from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .analysis import LapAnalysisSummary, SegmentAnalysis
from .interaction import (
    InteractionInputEvent,
    OutputLifecycleEvent,
    SpeechJob,
    StructuredQuerySchema,
    build_asr_stage_event,
    build_confirmation_policy,
    build_query_normalization_event,
    build_snapshot_query_input_event,
    build_structured_query_schema,
    build_task_handle,
    build_task_lifecycle_event,
    build_tts_stage_event,
    render_structured_query_response,
    route_structured_query,
)
from .models import SessionState, StrategyDecision, StrategyMessage
from .persona_registry import get_default_persona
from .tts_backends import (
    MacOSSayBackend,
    NullSpeechBackend,
    PiperBackend,
    PiperBackendConfig,
    SpeechBackend,
    resolve_default_speech_backend,
)


@dataclass
class _SpeechEnvelope:
    job: SpeechJob
    interaction_input_event: dict[str, Any]
    task_handle: dict[str, Any]


@dataclass
class _OutputProcessingResult:
    lifecycle_event: OutputLifecycleEvent
    event_envelope: _SpeechEnvelope | None
    completed_output_event: OutputLifecycleEvent | None = None
    completed_envelope: _SpeechEnvelope | None = None
    cancelled_output_event: OutputLifecycleEvent | None = None
    cancelled_envelope: _SpeechEnvelope | None = None


class ConsoleVoiceOutput:
    """Temporary stand-in for voice copilot and HUD output.

    备注:
    控制台输出同时承担当前阶段的策略调试视图。
    当策略引擎完成分层推理后，这里会把“状态评估 -> 风险评分 ->
    候选策略 -> 最终播报”按可读格式打印出来，便于快速校验策略逻辑。
    """

    def __init__(self, *, backend: SpeechBackend | None = None) -> None:
        self.output_session_id = "voice-output:console"
        self.backend = backend or self._default_backend()
        self.persona = get_default_persona()
        self._event_counter = 0
        self._active_envelope: _SpeechEnvelope | None = None
        self._active_handle: Any = None
        self._pending_envelope: _SpeechEnvelope | None = None
        self._last_completed_envelope: _SpeechEnvelope | None = None

    def emit(self, decision: StrategyDecision, *, render: bool = True) -> dict:
        """Emit one lifecycle-aware output step and return the lifecycle event."""

        interaction_input_event = decision.debug.get("interaction_input_event", {}) or {}
        task_handle = decision.debug.get("task_handle", {}) or {}
        arbiter_output = (decision.debug.get("arbiter_v2", {}) or {}).get("output", {}) or {}
        final_voice_action = arbiter_output.get("final_voice_action") or {}
        envelope = self._build_strategy_envelope(
            decision=decision,
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
            final_voice_action=final_voice_action,
        )
        result = self._process_submission(
            submitted_envelope=envelope,
            fallback_input_event=interaction_input_event,
            fallback_task_handle=task_handle,
        )
        self._write_debug_payload(
            debug=decision.debug,
            result=result,
        )
        pipeline_log = decision.debug.setdefault("voice_pipeline_log", {})
        lifecycle_event = result.lifecycle_event

        if lifecycle_event.event_type == "idle":
            if render:
                print("[ASURADA] 状态稳定，无高优先级播报。")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "complete":
            if render:
                print(f"[ASURADA][COMPLETE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "suppress":
            if render:
                print(f"[ASURADA][SUPPRESS] {lifecycle_event.action_code}: {lifecycle_event.metadata.get('reason', 'suppressed')}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "enqueue":
            if render:
                print(f"[ASURADA][QUEUE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "replace_pending":
            if render:
                print(f"[ASURADA][QUEUE-REPLACE] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "cancel":
            if render:
                print(f"[ASURADA][CANCEL] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]

        top = decision.messages[0]
        prefix = f"P{top.priority}"
        if render:
            print(f"[ASURADA][{prefix}] {top.title}: {top.detail}")
            for extra in decision.messages[1:3]:
                print(f"  - {extra.title}: {extra.detail}")
            self._emit_debug(decision)
        return decision.debug["output_lifecycle"]

    def emit_query_response(
        self,
        *,
        state: SessionState,
        query_kind: str,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> dict[str, Any]:
        """Emit one structured query response through the same speech queue."""

        input_event = build_snapshot_query_input_event(
            state=state,
            query_kind=query_kind,
            primary_message=primary_message,
        )
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

    def emit_voice_query_bundle(
        self,
        *,
        state: SessionState,
        bundle: Any,
        primary_message: StrategyMessage | None = None,
        render: bool = True,
    ) -> dict[str, Any]:
        """Emit one pre-normalized voice query bundle through the unified queue."""

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

        if query_kind == "repeat_last":
            return self._emit_repeat_last_control(
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
        envelope = self._build_query_envelope(
            input_event=input_event,
            task_handle=task_handle,
            schema=structured_query,
            speak_text=speak_text,
            action_code=action_code,
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
            elif event.event_type == "suppress":
                print(f"[ASURADA][QUERY][SUPPRESS] {event.metadata.get('reason', 'suppressed')}")
        return debug

    def _default_backend(self) -> SpeechBackend:
        return resolve_default_speech_backend()

    def _build_strategy_envelope(
        self,
        *,
        decision: StrategyDecision,
        interaction_input_event: dict[str, Any],
        task_handle: dict[str, Any],
        final_voice_action: dict[str, Any],
    ) -> _SpeechEnvelope | None:
        if not decision.messages or not final_voice_action:
            return None

        top = decision.messages[0]
        if top.code == "NONE":
            return None
        output_event_id = self._next_output_event_id()
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=output_event_id,
                interaction_session_id=str(interaction_input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(interaction_input_event.get("turn_id") or "turn:unknown"),
                request_id=str(interaction_input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="strategy_broadcast",
                action_code=top.code,
                priority=int(final_voice_action.get("priority") or top.priority or 0),
                speak_text=str(final_voice_action.get("speak_text") or top.title),
                cancelable=top.code != "SAFETY_CAR",
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "strategy_broadcast",
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=interaction_input_event,
            task_handle=task_handle,
        )

    def _build_query_envelope(
        self,
        *,
        input_event: dict[str, Any],
        task_handle: dict[str, Any],
        schema: dict[str, Any],
        speak_text: str,
        action_code: str,
    ) -> _SpeechEnvelope:
        return _SpeechEnvelope(
            job=SpeechJob(
                output_event_id=self._next_output_event_id(),
                interaction_session_id=str(input_event.get("interaction_session_id") or "runtime:unknown"),
                turn_id=str(input_event.get("turn_id") or "turn:unknown"),
                request_id=str(input_event.get("request_id") or "req:unknown"),
                snapshot_binding_id=str(input_event.get("snapshot_binding_id") or "snap:unknown"),
                source_kind="query_response",
                action_code=action_code,
                priority=95,
                speak_text=speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "query_response",
                    "query_kind": schema.get("query_kind"),
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=input_event,
            task_handle=task_handle,
        )

    def _process_submission(
        self,
        *,
        submitted_envelope: _SpeechEnvelope | None,
        fallback_input_event: dict[str, Any],
        fallback_task_handle: dict[str, Any],
    ) -> _OutputProcessingResult:
        completed_envelope = self._poll_completed_active()
        completed_output_event = self._build_event_from_envelope(completed_envelope, "complete") if completed_envelope is not None else None
        auto_started_envelope = None
        auto_started_event = None

        if completed_envelope is not None and self._pending_envelope is not None:
            pending_to_start = self._pending_envelope
            self._pending_envelope = None
            auto_started_envelope = pending_to_start
            auto_started_event = self._start_envelope(pending_to_start)

        if submitted_envelope is None:
            if auto_started_event is not None and auto_started_envelope is not None:
                return _OutputProcessingResult(
                    lifecycle_event=auto_started_event,
                    event_envelope=auto_started_envelope,
                    completed_output_event=completed_output_event,
                    completed_envelope=completed_envelope,
                )
            if completed_output_event is not None:
                return _OutputProcessingResult(
                    lifecycle_event=completed_output_event,
                    event_envelope=completed_envelope,
                    completed_output_event=completed_output_event,
                    completed_envelope=completed_envelope,
                )
            return _OutputProcessingResult(
                lifecycle_event=self._build_fallback_event(
                    event_type="idle",
                    input_event=fallback_input_event,
                    task_handle=fallback_task_handle,
                    action_code=self._active_action_code() or "NONE",
                    metadata={"reason": "no_submission"},
                ),
                event_envelope=None,
            )

        if self._is_duplicate_code(submitted_envelope.job.action_code):
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "suppress",
                    metadata={"reason": "duplicate_active_or_pending_code", "source_kind": submitted_envelope.job.source_kind},
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event,
                completed_envelope=completed_envelope,
            )

        if self._active_envelope is None:
            return _OutputProcessingResult(
                lifecycle_event=self._start_envelope(submitted_envelope),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event,
                completed_envelope=completed_envelope,
            )

        if self._pending_envelope is None:
            self._pending_envelope = submitted_envelope
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "enqueue",
                    metadata={"source_kind": submitted_envelope.job.source_kind},
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event,
                completed_envelope=completed_envelope,
            )

        if submitted_envelope.job.priority > self._pending_envelope.job.priority:
            cancelled_envelope = self._pending_envelope
            cancelled_output_event = self._build_event_from_envelope(
                cancelled_envelope,
                "cancel",
                metadata={"reason": "replaced_by_higher_priority_pending", "source_kind": cancelled_envelope.job.source_kind},
            )
            self._pending_envelope = submitted_envelope
            return _OutputProcessingResult(
                lifecycle_event=self._build_event_from_envelope(
                    submitted_envelope,
                    "replace_pending",
                    metadata={
                        "source_kind": submitted_envelope.job.source_kind,
                        "replaced_output_event_id": cancelled_envelope.job.output_event_id,
                    },
                ),
                event_envelope=submitted_envelope,
                completed_output_event=completed_output_event,
                completed_envelope=completed_envelope,
                cancelled_output_event=cancelled_output_event,
                cancelled_envelope=cancelled_envelope,
            )

        return _OutputProcessingResult(
            lifecycle_event=self._build_event_from_envelope(
                submitted_envelope,
                "suppress",
                metadata={"reason": "lower_priority_than_pending", "source_kind": submitted_envelope.job.source_kind},
            ),
            event_envelope=submitted_envelope,
            completed_output_event=completed_output_event,
            completed_envelope=completed_envelope,
        )

    def _poll_completed_active(self) -> _SpeechEnvelope | None:
        if self._active_envelope is None:
            return None
        if self.backend.is_active(self._active_handle):
            return None
        completed = self._active_envelope
        self._active_envelope = None
        self._active_handle = None
        self._last_completed_envelope = completed
        return completed

    def _start_envelope(self, envelope: _SpeechEnvelope) -> OutputLifecycleEvent:
        self._active_envelope = envelope
        self._active_handle = self.backend.start(envelope.job)
        return self._build_event_from_envelope(
            envelope,
            "start",
            metadata={"source_kind": envelope.job.source_kind},
        )

    def _write_debug_payload(
        self,
        *,
        debug: dict[str, Any],
        result: _OutputProcessingResult,
    ) -> None:
        output_lifecycle = {
            "event": result.lifecycle_event.to_dict(),
            "completed_output": result.completed_output_event.to_dict() if result.completed_output_event is not None else None,
            "cancelled_output": result.cancelled_output_event.to_dict() if result.cancelled_output_event is not None else None,
            "active_output": self._summarize_envelope(self._active_envelope),
            "pending_output": self._summarize_envelope(self._pending_envelope),
        }
        debug["output_lifecycle"] = output_lifecycle

        event_task_payload = result.event_envelope.task_handle if result.event_envelope is not None else {}
        event_type = result.lifecycle_event.event_type
        if event_type == "start":
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type="start",
                status="running",
            ).to_dict()
        elif event_type in {"enqueue", "replace_pending"}:
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type=event_type,
                status="pending",
            ).to_dict()
        elif event_type == "complete":
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type="complete",
                status="completed",
            ).to_dict()
        elif event_type == "suppress":
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type="suppress",
                status="cancelled",
                cancel_reason=str(result.lifecycle_event.metadata.get("reason") or "suppressed"),
            ).to_dict()
        elif event_type == "cancel":
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type="cancel",
                status="cancelled",
                cancel_reason=str(result.lifecycle_event.metadata.get("reason") or "cancelled"),
            ).to_dict()
        else:
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload,
                event_type="idle",
                status="pending",
            ).to_dict()

        completed_task_event = None
        if result.completed_envelope is not None:
            completed_task_event = build_task_lifecycle_event(
                task_handle=result.completed_envelope.task_handle,
                event_type="complete",
                status="completed",
            ).to_dict()
        cancelled_task_event = None
        if result.cancelled_envelope is not None:
            cancelled_task_event = build_task_lifecycle_event(
                task_handle=result.cancelled_envelope.task_handle,
                event_type="cancel",
                status="cancelled",
                cancel_reason="replaced_by_higher_priority_pending",
                cancelled_by_request_id=result.event_envelope.job.request_id if result.event_envelope is not None else None,
            ).to_dict()

        debug["task_lifecycle"] = {
            "event": current_task_event,
            "completed_task": completed_task_event,
            "cancelled_task": cancelled_task_event,
            "active_task": self._task_summary(self._active_envelope),
            "pending_task": self._task_summary(self._pending_envelope),
        }
        pipeline_log = debug.setdefault("voice_pipeline_log", {})
        pipeline_log["tts"] = build_tts_stage_event(
            interaction_input_event=(
                result.event_envelope.interaction_input_event
                if result.event_envelope is not None
                else {}
            ),
            output_lifecycle_event=result.lifecycle_event.to_dict(),
        ).to_dict()
        if result.completed_output_event is not None and result.completed_envelope is not None:
            pipeline_log["tts_completed"] = build_tts_stage_event(
                interaction_input_event=result.completed_envelope.interaction_input_event,
                output_lifecycle_event=result.completed_output_event.to_dict(),
            ).to_dict()
        else:
            pipeline_log.pop("tts_completed", None)
        if result.cancelled_output_event is not None and result.cancelled_envelope is not None:
            pipeline_log["tts_cancelled"] = build_tts_stage_event(
                interaction_input_event=result.cancelled_envelope.interaction_input_event,
                output_lifecycle_event=result.cancelled_output_event.to_dict(),
            ).to_dict()
        else:
            pipeline_log.pop("tts_cancelled", None)
        pipeline_log["task_lifecycle"] = debug["task_lifecycle"]

    def _build_event_from_envelope(
        self,
        envelope: _SpeechEnvelope | None,
        event_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> OutputLifecycleEvent:
        if envelope is None:
            return OutputLifecycleEvent(
                output_session_id=self.output_session_id,
                output_event_id=self._next_output_event_id(),
                event_type=event_type,
                channel="voice",
                action_code="NONE",
                priority=0,
                cancelable=True,
                turn_id="turn:unknown",
                request_id="req:unknown",
                snapshot_binding_id="snap:unknown",
                speak_text="",
                metadata=metadata or {},
            )
        job = envelope.job
        merged_metadata = {
            "source_kind": job.source_kind,
            "persona_id": job.persona_id,
            "voice_profile_id": job.voice_profile_id,
        }
        if metadata:
            merged_metadata.update(metadata)
        return OutputLifecycleEvent(
            output_session_id=self.output_session_id,
            output_event_id=job.output_event_id,
            event_type=event_type,
            channel="voice",
            action_code=job.action_code,
            priority=job.priority,
            cancelable=job.cancelable,
            turn_id=job.turn_id,
            request_id=job.request_id,
            snapshot_binding_id=job.snapshot_binding_id,
            speak_text=job.speak_text,
            metadata=merged_metadata,
        )

    def _build_fallback_event(
        self,
        *,
        event_type: str,
        input_event: dict[str, Any],
        task_handle: dict[str, Any],
        action_code: str,
        metadata: dict[str, Any] | None = None,
    ) -> OutputLifecycleEvent:
        return OutputLifecycleEvent(
            output_session_id=self.output_session_id,
            output_event_id=self._next_output_event_id(),
            event_type=event_type,
            channel="voice",
            action_code=action_code,
            priority=int(input_event.get("priority") or 0),
            cancelable=bool(input_event.get("cancelable", True)),
            turn_id=str(input_event.get("turn_id") or "turn:unknown"),
            request_id=str(input_event.get("request_id") or task_handle.get("request_id") or "req:unknown"),
            snapshot_binding_id=str(input_event.get("snapshot_binding_id") or "snap:unknown"),
            speak_text="",
            metadata=metadata or {},
        )

    def _summarize_envelope(self, envelope: _SpeechEnvelope | None) -> dict[str, Any] | None:
        if envelope is None:
            return None
        return {
            "output_session_id": self.output_session_id,
            "output_event_id": envelope.job.output_event_id,
            "action_code": envelope.job.action_code,
            "priority": envelope.job.priority,
            "source_kind": envelope.job.source_kind,
            "request_id": envelope.job.request_id,
            "persona_id": envelope.job.persona_id,
            "voice_profile_id": envelope.job.voice_profile_id,
        }

    def _task_summary(self, envelope: _SpeechEnvelope | None) -> dict[str, Any] | None:
        if envelope is None:
            return None
        return {
            "task_id": envelope.task_handle.get("task_id"),
            "request_id": envelope.task_handle.get("request_id"),
            "handler": envelope.task_handle.get("handler"),
            "status": "running" if envelope is self._active_envelope else "pending",
        }

    def _active_action_code(self) -> str | None:
        if self._active_envelope is None:
            return None
        return self._active_envelope.job.action_code

    def _is_duplicate_code(self, action_code: str) -> bool:
        if self._active_envelope is not None and self._active_envelope.job.action_code == action_code:
            return True
        if self._pending_envelope is not None and self._pending_envelope.job.action_code == action_code:
            return True
        return False

    def _next_output_event_id(self) -> str:
        self._event_counter += 1
        return f"out:{self._event_counter}"

    def _emit_debug(self, decision: StrategyDecision) -> None:
        """Render layered debug state for maintenance and tuning."""

        context = decision.debug.get("context", {})
        assessment = decision.debug.get("assessment", {})
        risk_profile = decision.debug.get("risk_profile", {})
        candidates = decision.debug.get("candidates", [])
        interaction_input_event = decision.debug.get("interaction_input_event", {})
        output_lifecycle = decision.debug.get("output_lifecycle", {})
        task_lifecycle = decision.debug.get("task_lifecycle", {})

        print("  [备注] 分层策略调试")
        if interaction_input_event:
            snapshot_binding = interaction_input_event.get("snapshot_binding", {})
            print(
                "    - 交互事件: "
                f"{interaction_input_event.get('intent_type')} "
                f"turn={interaction_input_event.get('turn_id')} "
                f"request={interaction_input_event.get('request_id')} "
                f"snapshot={snapshot_binding.get('snapshot_binding_id')}"
            )
        if output_lifecycle:
            event = output_lifecycle.get("event", {})
            print(
                "    - 输出生命周期: "
                f"{event.get('event_type')} "
                f"action={event.get('action_code')} "
                f"output_event={event.get('output_event_id')}"
            )
        if task_lifecycle:
            event = task_lifecycle.get("event", {})
            print(
                "    - 任务生命周期: "
                f"{event.get('event_type')} "
                f"task={event.get('task_id')} "
                f"status={event.get('status')}"
            )
        if context:
            print(f"    - 上下文因子: {self._format_mapping(context)}")
        if assessment:
            print(f"    - 状态评估: {self._format_mapping(assessment)}")
        if risk_profile:
            print(f"    - 风险评分: {self._format_mapping(risk_profile)}")
        if candidates:
            ranked = ", ".join(
                f"{item['code']}@{item['priority']}({item['layer']})"
                for item in candidates[:5]
            )
            print(f"    - 候选策略: {ranked}")
        if decision.messages:
            ordered = " > ".join(f"{item.code}@{item.priority}" for item in decision.messages[:5])
            print(f"    - 最终排序: {ordered}")

    def _format_mapping(self, payload: dict) -> str:
        """Format a flat mapping into one readable debug line."""

        return ", ".join(f"{key}={value}" for key, value in payload.items())

    def _emit_repeat_last_control(
        self,
        *,
        input_event: dict[str, Any],
        structured_query: dict[str, Any],
        query_route: dict[str, Any],
        confirmation_policy: dict[str, Any],
        task_handle: dict[str, Any],
        normalization_event: dict[str, Any],
        render: bool,
        extra_debug: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self._active_envelope or self._pending_envelope or self._last_completed_envelope
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
                priority=95,
                speak_text=base.job.speak_text,
                cancelable=True,
                persona_id=self.persona.persona_id,
                voice_profile_id=self.persona.voice_profile_id,
                metadata={
                    "source": "query_response",
                    "query_kind": "repeat_last",
                    "repeated_action_code": base.job.action_code,
                    "repeated_output_event_id": base.job.output_event_id,
                    "persona_id": self.persona.persona_id,
                    "voice_profile_id": self.persona.voice_profile_id,
                },
            ),
            interaction_input_event=input_event,
            task_handle=task_handle,
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
                self.backend.stop(self._active_handle)
                self._active_handle = None
                self._active_envelope = None
                self._last_completed_envelope = active
                lifecycle_event = self._build_event_from_envelope(
                    active,
                    "cancel",
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
                self.backend.stop(self._active_handle)
                self._active_handle = None
                self._active_envelope = None
                self._last_completed_envelope = active
                lifecycle_event = self._build_event_from_envelope(
                    active,
                    "cancel",
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
        return debug


class ConsoleLapSummaryOutput:
    """Print a compact single-lap review summary."""

    def emit(self, summary: LapAnalysisSummary) -> None:
        """Render lap summary metrics and segment review lines."""

        print("[ASURADA][LAP] 单圈总结")
        print(f"  - 最高车速: {summary.max_speed_kph:.0f} km/h")
        print(f"  - 最低车速: {summary.min_speed_kph:.0f} km/h")
        print(f"  - 重刹事件: {summary.heavy_braking_events}")
        print(f"  - 姿态不稳事件: {summary.unstable_events}")
        print(f"  - 前轮负荷过高事件: {summary.overload_events}")
        print(f"  - 扇区切换次数: {summary.sector_transitions}")
        if summary.top_risk_segments:
            print("  [赛道复盘] 高风险区段")
            for segment in summary.top_risk_segments:
                print(f"    - {self._segment_line(segment)}")
        if summary.dynamics_phases:
            print("  [驾驶动态] 分阶段摘要")
            for phase in summary.dynamics_phases:
                print(
                    "    - "
                    f"{phase.phase}: sample={phase.sample_count}, "
                    f"unstable={phase.unstable_events}, "
                    f"front_load={phase.overload_events}, "
                    f"heavy_brake={phase.heavy_braking_events}, "
                    f"avg_speed={phase.avg_speed_kph:.0f}"
                )
        if summary.driver_style_summary:
            print("  [驾驶风格] 标签")
            print(f"    - {', '.join(summary.driver_style_summary)}")
        if summary.deployment_segments:
            print("  [赛道复盘] 主要部署区")
            for segment in summary.deployment_segments:
                print(
                    "    - "
                    f"{segment.name}: 最高 {segment.max_speed_kph:.0f} km/h, "
                    f"最低 {segment.min_speed_kph:.0f} km/h"
                )

    def _segment_line(self, segment: SegmentAnalysis) -> str:
        """Format one segment summary row."""

        return (
            f"{segment.name} ({segment.zone_type}) | "
            f"unstable={segment.unstable_events}, "
            f"front_load={segment.overload_events}, "
            f"heavy_brake={segment.heavy_braking_events}, "
            f"vmax={segment.max_speed_kph:.0f}"
        )

"""Build lifecycle evidence and console diagnostics without owning playback."""
from __future__ import annotations
import time
from typing import Any
from .interaction import OutputLifecycleEvent, build_task_lifecycle_event, build_tts_stage_event
from .models import StrategyDecision
from .output_contracts import _SpeechEnvelope, _OutputProcessingResult


class OutputEventRenderer:
    """Build lifecycle evidence and console diagnostics without owning playback. Shared state lives on ConsoleVoiceOutput."""

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
        debug["speech_session_events"] = list(self.session_events)
        output_lifecycle["session_events"] = list(self.session_events)
        debug["output_lifecycle"] = output_lifecycle
        seen = set()
        for event in (None if result.completed_event_published else output_lifecycle['completed_output'], output_lifecycle['cancelled_output'], output_lifecycle['event']):
            if event is not None:
                identity = (event['output_event_id'], event['event_type'], event['request_id'])
                if identity not in seen:
                    self._event_stream.append(event)
                    seen.add(identity)
        debug["runtime_voice_assists"] = {
            "brake_point_assist": self._brake_point_assist.snapshot(),
            "corner_gear_assist": self._corner_gear_assist.snapshot(),
            "attack_mode": self._attack_mode.snapshot(),
        }

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
        elif event_type == "failed":
            current_task_event = build_task_lifecycle_event(
                task_handle=event_task_payload, event_type="failed", status="failed",
            ).to_dict()
            current_task_event['metadata']['reason'] = result.lifecycle_event.metadata.get('reason')
        elif event_type in {"suppress", "silent"}:
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
                event_type=result.completed_output_event.event_type,
                status={"cancel": "cancelled", "failed": "failed", "complete": "completed"}[result.completed_output_event.event_type],
            ).to_dict()
        cancelled_task_event = None
        if result.cancelled_envelope is not None:
            cancelled_task_event = build_task_lifecycle_event(
                task_handle=result.cancelled_envelope.task_handle,
                event_type="cancel",
                status="cancelled",
                cancel_reason=result.cancelled_output_event.metadata.get("reason", "cancelled"),
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
            "radio_event_ms": int(time.time() * 1000),
            "radio_source_ms": envelope.interaction_input_event.get("created_at_ms"),
            "persona_id": job.persona_id,
            "voice_profile_id": job.voice_profile_id,
        }
        if job.metadata.get('stop_error_type'):
            merged_metadata['stop_error_type'] = job.metadata['stop_error_type']
        if job.metadata.get("stop_requested_at") is not None and event_type == "cancel":
            from .speech_clock import speech_time
            merged_metadata["stop_confirmed_ms"] = round((speech_time() - job.metadata["stop_requested_at"]) * 1000, 3)
        if "personality" in job.metadata:
            merged_metadata["personality"] = job.metadata["personality"]
        for field in ("render_voice", "render_delivery", "render_rate", "render_follow_rate"):
            if field in job.metadata:
                merged_metadata[field] = job.metadata[field]
        for field in ("pit_recommendation_id", "fuel_recommendation_id", "wing_levels", "wing_corner", "wing_compensation"):
            if field in job.metadata:
                merged_metadata[field] = job.metadata[field]
        if "attack_opportunity" in job.metadata:
            merged_metadata["attack_opportunity"] = job.metadata["attack_opportunity"]
        if "session_scope" in job.metadata:
            merged_metadata["session_scope"] = job.metadata["session_scope"]
        if job.metadata.get("cancel_reason"):
            merged_metadata["cancel_reason"] = job.metadata["cancel_reason"]
        if job.metadata.get('cancel_requested_by_request_id'):
            merged_metadata['cancel_requested_by_request_id'] = job.metadata['cancel_requested_by_request_id']
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



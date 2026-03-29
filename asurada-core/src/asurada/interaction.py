from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import SessionState, StrategyMessage


@dataclass
class SnapshotBinding:
    """Bind one interaction turn to a concrete normalized strategy snapshot."""

    snapshot_binding_id: str
    session_uid: str
    frame_identifier: int | None
    overall_frame_identifier: int | None
    session_time_s: float | None
    lap_number: int
    total_laps: int
    player_position: int
    track: str


@dataclass
class InteractionInputEvent:
    """Unified interaction input event shared by system turns and future ASR turns."""

    interaction_session_id: str
    turn_id: str
    request_id: str
    input_type: str
    intent_type: str
    source: str
    created_at_ms: int
    priority: int
    cancelable: bool
    snapshot_binding_id: str
    query_text: str
    snapshot_binding: SnapshotBinding
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutputLifecycleEvent:
    """Lifecycle event shared by current console output and future TTS pipeline."""

    output_session_id: str
    output_event_id: str
    event_type: str
    channel: str
    action_code: str
    priority: int
    cancelable: bool
    turn_id: str
    request_id: str
    snapshot_binding_id: str
    speak_text: str
    interrupted_output_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AsrStageEvent:
    """ASR stage envelope. Current system strategy flow marks this as not applicable."""

    interaction_session_id: str
    turn_id: str
    request_id: str
    input_type: str
    stage_status: str
    transcript_text: str
    confidence: float | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryNormalizationEvent:
    """Normalized query/intention envelope shared by future ASR and current system turns."""

    interaction_session_id: str
    turn_id: str
    request_id: str
    snapshot_binding_id: str
    stage_status: str
    normalized_query_text: str
    normalized_intent_type: str
    source_intent_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructuredQuerySchema:
    """Structured query schema shared by future voice/text/button interactions."""

    schema_version: str
    query_kind: str
    target_scope: str
    requested_fields: list[str]
    action_code_hint: str | None
    response_mode: str
    requires_confirmation: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryRoute:
    """Minimal routing contract for structured interaction queries."""

    route_type: str
    handler: str
    response_channel: str
    can_answer_from_snapshot: bool
    requires_confirmation: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfirmationPolicy:
    """Minimal confirmation and permission policy for voice/text interactions."""

    policy_version: str
    decision: str
    risk_level: str
    requires_confirmation: bool
    permission_scope: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskHandle:
    """Minimal task handle shared by future tool calls and long-running query execution."""

    task_id: str
    request_id: str
    turn_id: str
    task_type: str
    handler: str
    status: str
    cancelable: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskLifecycleEvent:
    """Lifecycle event for minimal logical task cancellation and completion."""

    task_id: str
    request_id: str
    turn_id: str
    event_type: str
    status: str
    cancel_reason: str | None
    cancelled_by_request_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyStageEvent:
    """Strategy decision stage envelope."""

    interaction_session_id: str
    turn_id: str
    request_id: str
    snapshot_binding_id: str
    stage_status: str
    session_mode: str
    primary_action_code: str
    final_message_count: int
    rule_candidate_count: int
    model_candidate_count: int
    confidence_level: str
    fallback_mode: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TtsStageEvent:
    """TTS/output stage envelope built from lifecycle events."""

    output_session_id: str
    output_event_id: str
    interaction_session_id: str
    turn_id: str
    request_id: str
    snapshot_binding_id: str
    stage_status: str
    event_type: str
    channel: str
    speak_text: str
    action_code: str
    interruptible: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_system_strategy_input_event(
    *,
    state: SessionState,
    primary_message: StrategyMessage | None,
    session_mode: str,
) -> InteractionInputEvent:
    """Build the minimal interaction envelope for one strategy-generated turn."""

    raw = state.raw
    frame_identifier = _optional_int(raw.get("frame_identifier"))
    overall_frame_identifier = _optional_int(raw.get("overall_frame_identifier"))
    frame_token = (
        overall_frame_identifier
        if overall_frame_identifier is not None
        else frame_identifier
    )
    frame_suffix = str(frame_token if frame_token is not None else "unknown")
    session_uid = str(state.session_uid)
    snapshot_binding_id = f"snap:{session_uid}:{frame_suffix}"
    interaction_session_id = f"runtime:{session_uid}"
    turn_id = f"turn:{frame_suffix}"
    request_id = f"req:strategy:{session_uid}:{frame_suffix}"
    top = primary_message or StrategyMessage(
        code="NONE",
        priority=0,
        title="无策略变化",
        detail="当前无高优先级动作需要输出。",
    )
    session_time_s = _optional_float(state.raw.get("session_time_s"))
    source_timestamp_ms = _optional_int(state.raw.get("source_timestamp_ms"))
    created_at_ms = source_timestamp_ms or 0

    snapshot_binding = SnapshotBinding(
        snapshot_binding_id=snapshot_binding_id,
        session_uid=session_uid,
        frame_identifier=frame_identifier,
        overall_frame_identifier=overall_frame_identifier,
        session_time_s=session_time_s,
        lap_number=state.lap_number,
        total_laps=state.total_laps,
        player_position=state.player.position,
        track=state.track,
    )
    return InteractionInputEvent(
        interaction_session_id=interaction_session_id,
        turn_id=turn_id,
        request_id=request_id,
        input_type="system_strategy",
        intent_type="strategy_broadcast",
        source="strategy_engine",
        created_at_ms=created_at_ms,
        priority=top.priority,
        cancelable=top.code != "SAFETY_CAR",
        snapshot_binding_id=snapshot_binding_id,
        query_text=f"{top.title}: {top.detail}",
        snapshot_binding=snapshot_binding,
        metadata={
            "strategy_code": top.code,
            "session_mode": session_mode,
            "timing_mode": state.raw.get("timing_mode"),
            "timing_support_level": state.raw.get("timing_support_level"),
        },
    )


def build_asr_stage_event(input_event: InteractionInputEvent) -> AsrStageEvent:
    """Build the ASR stage envelope for one interaction.

    For current system-generated strategy turns, ASR is explicitly marked as not applicable.
    """

    is_asr_input = str(input_event.input_type).startswith("asr")
    return AsrStageEvent(
        interaction_session_id=input_event.interaction_session_id,
        turn_id=input_event.turn_id,
        request_id=input_event.request_id,
        input_type=input_event.input_type,
        stage_status="completed" if is_asr_input else "not_applicable",
        transcript_text=input_event.query_text,
        confidence=None,
        metadata={
            "source": input_event.source,
        },
    )


def build_query_normalization_event(input_event: InteractionInputEvent) -> QueryNormalizationEvent:
    """Build the normalization stage envelope for one interaction."""

    normalized_query_text = " ".join(str(input_event.query_text).split())
    return QueryNormalizationEvent(
        interaction_session_id=input_event.interaction_session_id,
        turn_id=input_event.turn_id,
        request_id=input_event.request_id,
        snapshot_binding_id=input_event.snapshot_binding_id,
        stage_status="completed",
        normalized_query_text=normalized_query_text,
        normalized_intent_type=input_event.intent_type,
        source_intent_type=input_event.intent_type,
        metadata={
            "input_type": input_event.input_type,
            "source": input_event.source,
        },
    )


def build_structured_query_schema(input_event: InteractionInputEvent) -> StructuredQuerySchema:
    """Build the minimal structured query schema from one normalized interaction."""

    intent_type = str(input_event.intent_type or "unknown")
    query_kind = "strategy_broadcast" if intent_type == "strategy_broadcast" else "status_query"
    target_scope = "strategy" if intent_type == "strategy_broadcast" else "state_snapshot"
    requested_fields = (
        ["messages", "risk_profile", "session_route"]
        if intent_type == "strategy_broadcast"
        else ["player", "rivals", "raw"]
    )
    return StructuredQuerySchema(
        schema_version="v1",
        query_kind=query_kind,
        target_scope=target_scope,
        requested_fields=requested_fields,
        action_code_hint=str(input_event.metadata.get("strategy_code")) if input_event.metadata.get("strategy_code") else None,
        response_mode="broadcast" if intent_type == "strategy_broadcast" else "answer",
        requires_confirmation=False,
        metadata={
            "input_type": input_event.input_type,
            "intent_type": intent_type,
            "source": input_event.source,
        },
    )


def route_structured_query(schema: StructuredQuerySchema) -> QueryRoute:
    """Route a structured query to the minimal strategy/state handler."""

    if schema.query_kind == "strategy_broadcast":
        return QueryRoute(
            route_type="push_broadcast",
            handler="strategy_output_handler",
            response_channel="voice",
            can_answer_from_snapshot=True,
            requires_confirmation=schema.requires_confirmation,
            metadata={
                "target_scope": schema.target_scope,
                "requested_fields": schema.requested_fields,
            },
        )
    return QueryRoute(
        route_type="snapshot_answer",
        handler="strategy_snapshot_handler",
        response_channel="voice",
        can_answer_from_snapshot=True,
        requires_confirmation=schema.requires_confirmation,
        metadata={
            "target_scope": schema.target_scope,
            "requested_fields": schema.requested_fields,
        },
    )


def build_confirmation_policy(
    *,
    input_event: InteractionInputEvent,
    schema: StructuredQuerySchema,
    route: QueryRoute,
) -> ConfirmationPolicy:
    """Build minimal voice confirmation / permission rules.

    Current system strategy broadcast is auto-approved. Future action commands can escalate.
    """

    action_code = str(input_event.metadata.get("strategy_code") or "")
    high_risk_codes = {"BOX_NOW", "PIT_NOW", "OVERTAKE_NOW", "FULL_DEPLOY", "SAFETY_CAR"}
    if schema.query_kind == "strategy_broadcast":
        return ConfirmationPolicy(
            policy_version="v1",
            decision="auto_approve",
            risk_level="low",
            requires_confirmation=False,
            permission_scope="broadcast",
            reason="system_strategy_broadcast",
            metadata={
                "action_code_hint": action_code,
                "route_type": route.route_type,
            },
        )
    if action_code in high_risk_codes:
        return ConfirmationPolicy(
            policy_version="v1",
            decision="confirm_before_execute",
            risk_level="high",
            requires_confirmation=True,
            permission_scope="action_execution",
            reason="high_risk_action_code",
            metadata={
                "action_code_hint": action_code,
                "route_type": route.route_type,
            },
        )
    return ConfirmationPolicy(
        policy_version="v1",
        decision="direct_answer",
        risk_level="low",
        requires_confirmation=False,
        permission_scope="snapshot_answer",
        reason="low_risk_structured_query",
        metadata={
            "action_code_hint": action_code,
            "route_type": route.route_type,
        },
    )


def build_task_handle(
    *,
    input_event: InteractionInputEvent,
    route: QueryRoute,
    confirmation_policy: ConfirmationPolicy,
) -> TaskHandle:
    """Build the minimal task handle for one routed interaction."""

    task_id = f"task:{input_event.request_id}"
    return TaskHandle(
        task_id=task_id,
        request_id=input_event.request_id,
        turn_id=input_event.turn_id,
        task_type=route.route_type,
        handler=route.handler,
        status="pending",
        cancelable=confirmation_policy.decision != "confirm_before_execute",
        metadata={
            "response_channel": route.response_channel,
            "permission_scope": confirmation_policy.permission_scope,
        },
    )


def build_task_lifecycle_event(
    *,
    task_handle: dict[str, Any],
    event_type: str,
    status: str,
    cancel_reason: str | None = None,
    cancelled_by_request_id: str | None = None,
) -> TaskLifecycleEvent:
    """Build one minimal task lifecycle event."""

    return TaskLifecycleEvent(
        task_id=str(task_handle.get("task_id") or "task:unknown"),
        request_id=str(task_handle.get("request_id") or "req:unknown"),
        turn_id=str(task_handle.get("turn_id") or "turn:unknown"),
        event_type=event_type,
        status=status,
        cancel_reason=cancel_reason,
        cancelled_by_request_id=cancelled_by_request_id,
        metadata={
            "handler": task_handle.get("handler"),
            "task_type": task_handle.get("task_type"),
        },
    )


def build_strategy_stage_event(
    *,
    input_event: InteractionInputEvent,
    session_mode: str,
    primary_action_code: str,
    final_message_count: int,
    rule_candidate_count: int,
    model_candidate_count: int,
    confidence_level: str,
    fallback_mode: str,
) -> StrategyStageEvent:
    """Build the strategy stage envelope for one interaction."""

    return StrategyStageEvent(
        interaction_session_id=input_event.interaction_session_id,
        turn_id=input_event.turn_id,
        request_id=input_event.request_id,
        snapshot_binding_id=input_event.snapshot_binding_id,
        stage_status="completed",
        session_mode=session_mode,
        primary_action_code=primary_action_code,
        final_message_count=final_message_count,
        rule_candidate_count=rule_candidate_count,
        model_candidate_count=model_candidate_count,
        confidence_level=confidence_level,
        fallback_mode=fallback_mode,
        metadata={},
    )


def build_tts_stage_event(
    *,
    interaction_input_event: dict[str, Any],
    output_lifecycle_event: dict[str, Any],
) -> TtsStageEvent:
    """Build the TTS/output stage envelope from lifecycle events."""

    event_type = str(output_lifecycle_event.get("event_type") or "idle")
    return TtsStageEvent(
        output_session_id=str(output_lifecycle_event.get("output_session_id") or "voice-output:unknown"),
        output_event_id=str(output_lifecycle_event.get("output_event_id") or "out:unknown"),
        interaction_session_id=str(interaction_input_event.get("interaction_session_id") or "runtime:unknown"),
        turn_id=str(interaction_input_event.get("turn_id") or "turn:unknown"),
        request_id=str(interaction_input_event.get("request_id") or "req:unknown"),
        snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or "snap:unknown"),
        stage_status="completed" if event_type not in {"idle"} else "not_applicable",
        event_type=event_type,
        channel=str(output_lifecycle_event.get("channel") or "voice"),
        speak_text=str(output_lifecycle_event.get("speak_text") or ""),
        action_code=str(output_lifecycle_event.get("action_code") or "NONE"),
        interruptible=bool(output_lifecycle_event.get("cancelable", True)),
        metadata={
            "priority": output_lifecycle_event.get("priority"),
            "interrupted_output_event_id": output_lifecycle_event.get("interrupted_output_event_id"),
        },
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

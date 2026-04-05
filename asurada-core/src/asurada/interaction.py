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
class SpeechJob:
    """Unified speech job shared by proactive strategy broadcasts and query responses."""

    output_event_id: str
    interaction_session_id: str
    turn_id: str
    request_id: str
    snapshot_binding_id: str
    source_kind: str
    action_code: str
    priority: int
    speak_text: str
    cancelable: bool
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

    snapshot_binding = _build_snapshot_binding(
        state=state,
        snapshot_binding_id=snapshot_binding_id,
        frame_identifier=frame_identifier,
        overall_frame_identifier=overall_frame_identifier,
        session_time_s=session_time_s,
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


def build_snapshot_query_input_event(
    *,
    state: SessionState,
    query_kind: str,
    primary_message: StrategyMessage | None = None,
) -> InteractionInputEvent:
    """Build a structured snapshot-query interaction envelope for internal voice tests."""

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
    turn_id = f"turn:query:{query_kind}:{frame_suffix}"
    request_id = f"req:query:{query_kind}:{session_uid}:{frame_suffix}"
    session_time_s = _optional_float(raw.get("session_time_s"))
    created_at_ms = _optional_int(raw.get("source_timestamp_ms")) or 0
    snapshot_binding = _build_snapshot_binding(
        state=state,
        snapshot_binding_id=snapshot_binding_id,
        frame_identifier=frame_identifier,
        overall_frame_identifier=overall_frame_identifier,
        session_time_s=session_time_s,
    )
    return InteractionInputEvent(
        interaction_session_id=interaction_session_id,
        turn_id=turn_id,
        request_id=request_id,
        input_type="structured_query_stub",
        intent_type="status_query",
        source="output_coordinator",
        created_at_ms=created_at_ms,
        priority=95,
        cancelable=True,
        snapshot_binding_id=snapshot_binding_id,
        query_text=_query_prompt(query_kind),
        snapshot_binding=snapshot_binding,
        metadata={
            "query_kind": query_kind,
            "primary_action_code": primary_message.code if primary_message is not None else None,
        },
    )


def build_asr_stage_event(input_event: InteractionInputEvent) -> AsrStageEvent:
    """Build the ASR stage envelope for one interaction.

    For current system-generated strategy turns, ASR is explicitly marked as not applicable.
    """

    is_asr_input = str(input_event.input_type).startswith("asr")
    confidence = input_event.metadata.get("fast_intent_confidence")
    try:
        confidence = None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        confidence = None
    return AsrStageEvent(
        interaction_session_id=input_event.interaction_session_id,
        turn_id=input_event.turn_id,
        request_id=input_event.request_id,
        input_type=input_event.input_type,
        stage_status="completed" if is_asr_input else "not_applicable",
        transcript_text=input_event.query_text,
        confidence=confidence,
        metadata={
            "source": input_event.source,
            "lane": input_event.metadata.get("lane"),
            "matched_phrase": input_event.metadata.get("matched_phrase"),
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
    if intent_type == "strategy_broadcast":
        query_kind = "strategy_broadcast"
        target_scope = "strategy"
        requested_fields = ["messages", "risk_profile", "session_route"]
    else:
        query_kind = str(input_event.metadata.get("query_kind") or "status_query")
        target_scope = "strategy" if query_kind == "current_strategy" else "state_snapshot"
        requested_fields = _requested_fields_for_query_kind(query_kind)
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
    if schema.query_kind == "fuel_status":
        handler = "fuel_snapshot_handler"
    elif schema.query_kind == "rear_gap":
        handler = "rear_gap_snapshot_handler"
    elif schema.query_kind == "tyre_status":
        handler = "tyre_snapshot_handler"
    elif schema.query_kind == "current_strategy":
        handler = "strategy_snapshot_handler"
    elif schema.query_kind == "repeat_last":
        handler = "repeat_last_output_handler"
    elif schema.query_kind in {"stop", "cancel"}:
        handler = "output_control_handler"
    else:
        handler = "strategy_snapshot_handler"
    return QueryRoute(
        route_type="snapshot_answer",
        handler=handler,
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
    if event_type in {"enqueue", "replace_pending"}:
        stage_status = "queued"
    elif event_type == "idle":
        stage_status = "not_applicable"
    else:
        stage_status = "completed"
    return TtsStageEvent(
        output_session_id=str(output_lifecycle_event.get("output_session_id") or "voice-output:unknown"),
        output_event_id=str(output_lifecycle_event.get("output_event_id") or "out:unknown"),
        interaction_session_id=str(interaction_input_event.get("interaction_session_id") or "runtime:unknown"),
        turn_id=str(interaction_input_event.get("turn_id") or "turn:unknown"),
        request_id=str(interaction_input_event.get("request_id") or "req:unknown"),
        snapshot_binding_id=str(interaction_input_event.get("snapshot_binding_id") or "snap:unknown"),
        stage_status=stage_status,
        event_type=event_type,
        channel=str(output_lifecycle_event.get("channel") or "voice"),
        speak_text=str(output_lifecycle_event.get("speak_text") or ""),
        action_code=str(output_lifecycle_event.get("action_code") or "NONE"),
        interruptible=bool(output_lifecycle_event.get("cancelable", True)),
        metadata={
            "priority": output_lifecycle_event.get("priority"),
            "interrupted_output_event_id": output_lifecycle_event.get("interrupted_output_event_id"),
            "source_kind": output_lifecycle_event.get("metadata", {}).get("source_kind"),
        },
    )


def render_structured_query_response(
    *,
    state: SessionState,
    schema: StructuredQuerySchema,
    primary_message: StrategyMessage | None = None,
) -> tuple[str, str]:
    """Render the first-wave templated snapshot query response text."""

    if schema.query_kind == "fuel_status":
        return (
            f"当前燃油预计还可支撑 {state.player.fuel_laps_remaining:.1f} 圈，总圈数 {state.total_laps} 圈。",
            "QUERY_FUEL_STATUS",
        )
    if schema.query_kind == "rear_gap":
        if state.player.gap_behind_s is None:
            return ("当前后车时差缺失。", "QUERY_REAR_GAP")
        rear_name = state.rivals[0].name if state.rivals else "后车"
        return (f"后车 {rear_name} 在 {state.player.gap_behind_s:.3f} 秒之后。", "QUERY_REAR_GAP")
    if schema.query_kind == "tyre_status":
        tyre = state.player.tyre
        return (
            f"当前轮胎 {tyre.compound}，磨损 {tyre.wear_pct:.1f}%，胎龄 {tyre.age_laps} 圈。",
            "QUERY_TYRE_STATUS",
        )
    if schema.query_kind == "current_strategy":
        if primary_message is None:
            return ("当前没有高优先级主策略。", "QUERY_CURRENT_STRATEGY")
        return (f"当前主策略是 {primary_message.title}。{primary_message.detail}", "QUERY_CURRENT_STRATEGY")
    return ("当前查询类型还未接入模板回答。", "QUERY_SNAPSHOT_STATUS")


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


def _build_snapshot_binding(
    *,
    state: SessionState,
    snapshot_binding_id: str,
    frame_identifier: int | None,
    overall_frame_identifier: int | None,
    session_time_s: float | None,
) -> SnapshotBinding:
    return SnapshotBinding(
        snapshot_binding_id=snapshot_binding_id,
        session_uid=str(state.session_uid),
        frame_identifier=frame_identifier,
        overall_frame_identifier=overall_frame_identifier,
        session_time_s=session_time_s,
        lap_number=state.lap_number,
        total_laps=state.total_laps,
        player_position=state.player.position,
        track=state.track,
    )


def _query_prompt(query_kind: str) -> str:
    prompts = {
        "fuel_status": "当前燃油情况怎么样",
        "rear_gap": "后车距离多少",
        "tyre_status": "当前轮胎状态怎么样",
        "current_strategy": "当前主策略是什么",
        "repeat_last": "请重复上一条播报",
        "stop": "停止当前播报",
        "cancel": "取消当前操作",
    }
    return prompts.get(query_kind, "当前状态怎么样")


def _requested_fields_for_query_kind(query_kind: str) -> list[str]:
    if query_kind == "fuel_status":
        return ["player.fuel_laps_remaining", "total_laps", "raw.fuel_in_tank"]
    if query_kind == "rear_gap":
        return ["player.gap_behind_s", "rivals"]
    if query_kind == "tyre_status":
        return ["player.tyre"]
    if query_kind == "current_strategy":
        return ["messages", "session_route"]
    if query_kind in {"repeat_last", "stop", "cancel"}:
        return ["messages", "output_lifecycle", "task_lifecycle"]
    return ["player", "rivals", "raw"]

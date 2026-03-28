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
    session_time_s = _optional_float(raw.get("session_time_s"))
    source_timestamp_ms = _optional_int(raw.get("source_timestamp_ms"))
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
            "timing_mode": raw.get("timing_mode"),
            "timing_support_level": raw.get("timing_support_level"),
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

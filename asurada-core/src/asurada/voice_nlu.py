from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .asr_fast import FastIntentResult
from .interaction import (
    InteractionInputEvent,
    SnapshotBinding,
    StructuredQuerySchema,
    build_confirmation_policy,
    build_query_normalization_event,
    build_structured_query_schema,
    build_task_handle,
    route_structured_query,
)
from .models import SessionState
from .semantic_normalizer import SemanticIntentResult
from .voice_turn import VoiceTurn


@dataclass(frozen=True)
class VoiceQueryBundle:
    """Structured voice-query bundle aligned with the existing interaction contracts."""

    input_event: dict[str, Any]
    structured_query: dict[str, Any]
    query_route: dict[str, Any]
    confirmation_policy: dict[str, Any]
    task_handle: dict[str, Any]
    normalization_event: dict[str, Any]
    fast_intent: dict[str, Any]
    voice_turn: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_voice_query_bundle(
    *,
    state: SessionState,
    voice_turn: VoiceTurn,
    fast_intent: FastIntentResult,
    semantic_intent: SemanticIntentResult | None = None,
) -> VoiceQueryBundle:
    """Map one completed voice turn into the existing interaction contracts."""

    resolved_query_kind = semantic_intent.query_kind if semantic_intent is not None else fast_intent.query_kind
    if resolved_query_kind is None:
        raise ValueError("semantic or fast intent result must contain a matched query_kind")

    input_event = build_voice_query_input_event(
        state=state,
        voice_turn=voice_turn,
        fast_intent=fast_intent,
        semantic_intent=semantic_intent,
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
    normalization_event = build_query_normalization_event(input_event)
    return VoiceQueryBundle(
        input_event=input_event.to_dict(),
        structured_query=structured_query.to_dict(),
        query_route=query_route.to_dict(),
        confirmation_policy=confirmation_policy.to_dict(),
        task_handle=task_handle.to_dict(),
        normalization_event=normalization_event.to_dict(),
        fast_intent=fast_intent.to_dict(),
        voice_turn=voice_turn.to_dict(),
    )


def build_voice_query_input_event(
    *,
    state: SessionState,
    voice_turn: VoiceTurn,
    fast_intent: FastIntentResult,
    semantic_intent: SemanticIntentResult | None = None,
) -> InteractionInputEvent:
    raw = state.raw
    frame_identifier = _optional_int(raw.get("frame_identifier"))
    overall_frame_identifier = _optional_int(raw.get("overall_frame_identifier"))
    frame_token = overall_frame_identifier if overall_frame_identifier is not None else frame_identifier
    frame_suffix = str(frame_token if frame_token is not None else "unknown")
    session_uid = str(state.session_uid)
    snapshot_binding_id = f"snap:{session_uid}:{frame_suffix}"
    interaction_session_id = f"runtime:{session_uid}"
    turn_id = f"{voice_turn.turn_id}:{frame_suffix}"
    request_id = f"req:voice:{fast_intent.query_kind}:{session_uid}:{voice_turn.turn_id}"
    session_time_s = _optional_float(raw.get("session_time_s"))
    source_timestamp_ms = _optional_int(raw.get("source_timestamp_ms")) or voice_turn.ended_at_ms

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
    resolved_query_kind = semantic_intent.query_kind if semantic_intent is not None else fast_intent.query_kind
    normalized_query_text = (
        semantic_intent.normalized_query_text if semantic_intent is not None else fast_intent.transcript_text
    )
    request_id = f"req:voice:{resolved_query_kind}:{session_uid}:{voice_turn.turn_id}"
    return InteractionInputEvent(
        interaction_session_id=interaction_session_id,
        turn_id=turn_id,
        request_id=request_id,
        input_type="asr_fast_query",
        intent_type="status_query",
        source="voice_fast_lane",
        created_at_ms=source_timestamp_ms,
        priority=90,
        cancelable=True,
        snapshot_binding_id=snapshot_binding_id,
        query_text=normalized_query_text,
        snapshot_binding=snapshot_binding,
        metadata={
            "query_kind": resolved_query_kind,
            "voice_turn_id": voice_turn.turn_id,
            "fast_intent_confidence": semantic_intent.confidence if semantic_intent is not None else fast_intent.confidence,
            "matched_phrase": fast_intent.matched_phrase,
            "lane": fast_intent.lane,
            "semantic_status": semantic_intent.status if semantic_intent is not None else None,
            "semantic_reason": semantic_intent.reason if semantic_intent is not None else None,
            "response_style": semantic_intent.response_style if semantic_intent is not None else "structured",
            "semantic_metadata": semantic_intent.metadata if semantic_intent is not None else {},
        },
    )


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

"""Shared training/runtime temporal and track preview features."""
from __future__ import annotations
from typing import Any

PREVIEW_OFFSETS_M = (120.0, 280.0)

def optional_float(value: Any) -> float | None:
    return None if value is None else float(value)



def preview_segments(*, track_profile, lap_distance_m: float, offsets: list[float]) -> tuple[str | None, str | None, str]:
    """Preview the next one or two semantic segments from the current lap distance."""

    if track_profile is None:
        return None, None, ""
    next_segment = track_profile.next_segment(lap_distance_m)
    classifications = [track_profile.classify(lap_distance_m + offset) for offset in offsets]
    combined = " > ".join(item.zone_name for item in classifications if item.zone_name)
    return (
        next_segment.zone_name,
        next_segment.usage,
        combined,
    )



def closing_rate_from_recent_history(
    *,
    recent_states: list[Any],
    current_gap: float | None,
    current_session_time_s: float | None,
    gap_side: str,
) -> float | None:
    """Estimate closing rate from a short official-gap window instead of a single-frame delta.

    备注:
    官方 gap 在逐帧上会出现长段重复值，单帧差分几乎全是 0。
    这里回看最近几帧，找最早的有效官方 gap 作为参考点，计算短窗口斜率。
    """

    if current_gap is None or current_session_time_s is None or len(recent_states) < 2:
        return None

    current_session_time_s = float(current_session_time_s)
    for candidate in reversed(recent_states[:-1]):
        candidate_session_time_s = optional_float(candidate.raw.get("session_time_s"))
        if candidate_session_time_s is None or candidate_session_time_s >= current_session_time_s:
            continue
        candidate_gap = candidate.player.gap_ahead_s if gap_side == "ahead" else candidate.player.gap_behind_s
        if candidate_gap is None:
            continue
        delta_t = current_session_time_s - candidate_session_time_s
        if delta_t <= 0:
            continue
        return (float(candidate_gap) - float(current_gap)) / delta_t
    return None

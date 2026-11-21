"""Shared deterministic constants and scalar helpers for pit planning."""
from __future__ import annotations

from .models import SessionState


_COMPOUND_TARGET_LIFE = {
    "C1": 28.0,
    "C2": 24.0,
    "C3": 19.0,
    "C4": 14.0,
    "C5": 10.0,
    "Intermediate": 16.0,
    "Wet": 12.0,
}


_COMPOUND_BASE_RISK = {
    "C1": 8.0,
    "C2": 12.0,
    "C3": 18.0,
    "C4": 24.0,
    "C5": 30.0,
    "Intermediate": 18.0,
    "Wet": 24.0,
}


_WEATHER_NAMES = {
    0: "Clear",
    1: "LightCloud",
    2: "Overcast",
    3: "LightRain",
    4: "HeavyRain",
    5: "Storm",
}


_DRY_WEATHER = {"Clear", "LightCloud", "Overcast"}


_WET_WEATHER = {"LightRain", "HeavyRain", "Storm"}


ACTUAL_COMPOUNDS = {
    21: "C0",
    22: "C6",
    16: "C5",
    17: "C4",
    18: "C3",
    19: "C2",
    20: "C1",
    7: "Intermediate",
    8: "Wet",
}


_DRY_COMPOUND_BY_STINT = (
    (8, "C5"),
    (14, "C4"),
    (22, "C3"),
    (30, "C2"),
)


_DRY_COMPOUND_ORDER = ["C6", "C5", "C4", "C3", "C2", "C1", "C0"]


_TRACK_COMPOUND_BIAS: dict[str, dict[str, float]] = {
    "shanghai": {"C1": 0.5, "C2": 1.5, "C3": 3.0, "C4": 1.0, "C5": -2.0},
    "suzuka": {"C1": 4.0, "C2": 2.5, "C3": 0.5, "C4": -1.5, "C5": -4.5},
}


def _used_completed_dry_compounds(*, state: SessionState, current_compound: str) -> set[str]:
    used_dry_compounds = {current_compound} if current_compound in _DRY_COMPOUND_ORDER else set()
    session_history = state.raw.get("session_history") or {}
    if session_history.get("car_index") != state.player.car_index:
        return used_dry_compounds
    for stint in (session_history.get("tyre_stints_history_data") or [])[:session_history.get("num_tyre_stints", 0)]:
        end_lap = int(stint.get("end_lap", 0) or 0)
        if end_lap <= 0 or end_lap >= 255 or end_lap > state.lap_number:
            continue
        code = stint.get("tyre_actual_compound")
        if not isinstance(code, int):
            continue
        compound_name = ACTUAL_COMPOUNDS.get(code)
        if compound_name in _DRY_COMPOUND_ORDER:
            used_dry_compounds.add(compound_name)
    return used_dry_compounds


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)

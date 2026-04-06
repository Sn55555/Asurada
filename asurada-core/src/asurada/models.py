from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TyreState:
    """Minimal tyre state kept on the hot path."""

    compound: str
    wear_pct: float
    age_laps: int
    surface_temperature_c: list[int] = field(default_factory=list)
    inner_temperature_c: list[int] = field(default_factory=list)


@dataclass
class DriverState:
    """Normalized per-driver state used by strategy and replay layers."""

    car_index: int
    name: str
    position: int
    lap: int
    gap_ahead_s: float | None
    gap_behind_s: float | None
    fuel_laps_remaining: float
    ers_pct: float
    drs_available: bool
    tyre: TyreState
    speed_kph: float
    status_tags: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    """Single normalized frame consumed by the strategy engine."""

    session_uid: str
    track: str
    lap_number: int
    total_laps: int
    weather: str
    safety_car: str
    player: DriverState
    rivals: list[DriverState]
    source_timestamp_ms: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyMessage:
    """Final user-facing message after arbitration."""

    code: str
    priority: int
    title: str
    detail: str


@dataclass
class StateAssessment:
    """Discrete state labels produced before numeric risk scoring."""

    fuel_state: str
    tyre_state: str
    ers_state: str
    race_state: str
    attack_state: str
    defend_state: str
    dynamics_state: str


@dataclass
class RiskProfile:
    """Numeric risk/opportunity scores used for candidate ordering."""

    fuel_risk: int
    tyre_risk: int
    ers_risk: int
    race_control_risk: int
    dynamics_risk: int
    attack_opportunity: int
    defend_risk: int


@dataclass
class ContextProfile:
    """Short-window context features derived from recent frames and track model."""

    recent_unstable_ratio: float
    recent_front_overload_ratio: float
    driving_mode: str
    track_zone: str
    track_segment: str
    track_usage: str
    tyre_age_factor: int
    brake_phase_factor: int
    throttle_phase_factor: int
    steering_phase_factor: int


@dataclass
class StrategyCandidate:
    """Intermediate candidate before final arbitration."""

    code: str
    priority: int
    title: str
    detail: str
    layer: str


@dataclass
class StrategyDecision:
    """Final strategy output plus debug payload for inspection."""

    messages: list[StrategyMessage]
    debug: dict[str, Any] = field(default_factory=dict)

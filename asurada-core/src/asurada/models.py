from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .personality_runtime import PersonalitySnapshot


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
    team_id: int | None = None
    race_number: int | None = None
    gap_source: str | None = None
    gap_confidence: str | None = None
    gap_source_ahead: str | None = None
    gap_source_behind: str | None = None
    gap_confidence_ahead: str | None = None
    gap_confidence_behind: str | None = None
    estimated_gap_source: str | None = None
    estimated_gap_confidence: str | None = None
    pit_status: str | None = None
    tyre_damage_pct: float | None = None
    engine_damage_pct: int | None = None
    aero_damage_pct: int | None = None
    lap_distance_m: float | None = None
    world_position_x: float | None = None
    world_position_y: float | None = None
    world_position_z: float | None = None


@dataclass
class SessionState:
    """Single normalized frame consumed by the strategy engine."""

    session_uid: str
    track: str
    lap_number: int
    total_laps: int
    weather: str
    safety_car: str | None
    player: DriverState
    rivals: list[DriverState]
    source_timestamp_ms: int
    raw: dict[str, Any] = field(default_factory=dict)
    session_epoch: int = 0
    session_epoch_explicit: bool = False
    assessment: AssessmentResult | None = None
    decision_record: DecisionRecord | None = None
    session_event: dict[str, Any] | None = None
    personality: PersonalitySnapshot | None = None


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
    corner_overtake_class: str = "general"
    attack_setup_method: str = "none"
    attack_commit_method: str = "none"
    next_track_segment: str = "UNKNOWN"
    next_track_usage: str = "UNKNOWN"
    history_window_version: str = "source-time-weighted-v1"
    history_coverage_ms: float = 0.0
    input_quality: dict[str, Any] = field(default_factory=dict)
    gap_closing_rate_behind: float | None = None
    next_two_segments: str = ""


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
    record: DecisionRecord | None = None


@dataclass(frozen=True)
class AssessmentResult:
    snapshot_id: str
    rule_version: str
    labels: StateAssessment
    fuel: dict[str, Any]
    thresholds: dict[str, float]


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    snapshot_id: str
    session_uid: str
    session_epoch: int
    source_timestamp_ms: int
    assessment: AssessmentResult
    actions: tuple[StrategyMessage, ...]
    candidates: tuple[dict[str, Any], ...]
    arbitration: dict[str, Any]
    contract_version: str = "decision-v1"
    model_admission: dict[str, Any] = field(default_factory=dict)
    identity_version: str = "legacy"

"""Serializable pit-window and long-horizon planning result contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PitWindowSupportState:
    enabled: bool
    lap_life_remaining_est: float | None
    remaining_required_stops: int
    compound_rule_state: str
    pit_window_open_prob: float
    compound_risk_score: float
    rejoin_traffic_penalty: float
    estimated_rejoin_position_loss: float
    undercut_defence_score: float
    pit_loss_now_score: float
    pit_loss_under_control_state: float
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.compound_rule_state == "unknown":
            payload["remaining_required_stops"] = None
        return payload


@dataclass
class LongHorizonCandidate:
    code: str
    target_lap: int | None
    recommended_compound: str | None
    recommended_set_index: int | None
    recommended_set_available: bool
    total_score: float
    components: dict[str, float]
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LongHorizonStrategyState:
    enabled: bool
    session_mode: str
    recommended_pit_lap: int | None
    pit_window_start_lap: int | None
    pit_window_end_lap: int | None
    recommended_compound: str | None
    recommended_set_index: int | None
    recommended_set_available: bool
    lap_life_remaining_est: float | None
    remaining_required_stops: int
    compound_rule_state: str
    pit_window_open_prob: float
    stint_risk_score: float
    compound_risk_score: float
    strategy_confidence: float
    aggression_bias: float
    rationale: list[str] = field(default_factory=list)
    candidates: list[LongHorizonCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.compound_rule_state == "unknown":
            payload["remaining_required_stops"] = None
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload

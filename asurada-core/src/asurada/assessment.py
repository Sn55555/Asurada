"""Shared domain facts. Presentation and inference consume the same verdict."""
from __future__ import annotations

from .race_control import race_control_active, normalize_race_control

from dataclasses import asdict, dataclass
import math
import hashlib
from decimal import Decimal
import json
from typing import Any
from .models import SessionState, AssessmentResult, StateAssessment
from .config import StrategyThresholds

DOMAIN_RULE_VERSION = 'domain-v6'


def _nonnegative(value: Any) -> float | None:
    # Normalized telemetry must contain numbers, never bool or numeric text.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def valid_percentage(value: Any) -> float | None:
    number = _nonnegative(value)
    return number if number is not None and number <= 100 else None


@dataclass(frozen=True)
class FuelAssessment:
    verdict: str
    source: str
    quality: str
    remaining_race_laps: int | None
    estimated_fuel_laps: float | None
    margin_laps: float | None
    tank_ratio: float | None
    rule_version: str = 'fuel-v3'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        if self.margin_laps is not None:
            verdict = '燃油已经偏紧，需要省油。' if self.verdict == 'critical' else '燃油预计可覆盖剩余赛程。'
            return (f'{verdict} 当前预计可跑 {self.estimated_fuel_laps:.1f} 圈，'
                    f'剩余赛程 {self.remaining_race_laps} 圈，余量差 {self.margin_laps:+.1f} 圈。')
        if self.tank_ratio is not None:
            verdict = '油箱已空，需要立即处理。' if self.verdict == 'critical' else '油箱占比不能单独判断是否够跑。'
            return f'{verdict} 当前油箱剩余 {self.tank_ratio * 100:.1f}%，终盘覆盖暂不能可靠判断。'
        return '燃油数据不足，暂不能可靠判断是否需要省油或能否覆盖剩余赛程。'


def assess_fuel(state: SessionState) -> FuelAssessment:
    source = str(state.raw.get('fuel_laps_remaining_source', 'unknown'))
    remaining = max(state.total_laps - max(state.lap_number - 1, 0), 0) if state.total_laps > 0 else None
    estimate = _nonnegative(state.player.fuel_laps_remaining)
    tank = _nonnegative(state.raw.get('fuel_in_tank'))
    capacity = _nonnegative(state.raw.get('fuel_capacity'))
    ratio = tank / capacity if tank is not None and capacity and tank <= capacity else None
    if tank == 0:
        return FuelAssessment('critical', 'tank_ratio', 'observed', remaining, None, None, ratio)
    if source == 'derived_from_sample_consumption' and state.lap_number > 1 and estimate is not None and remaining is not None:
        margin = estimate - remaining
        return FuelAssessment('critical' if margin <= .3 else 'stable', source, 'estimated', remaining, estimate, margin, ratio)
    if ratio is not None:
        return FuelAssessment('critical' if tank == 0 else 'unavailable', 'tank_ratio', 'partial', remaining, None, None, ratio)
    return FuelAssessment('unavailable', source, 'unavailable', remaining, None, None, None)


def snapshot_id(state: SessionState) -> str:
    payload = {"session_uid": state.session_uid, "epoch": state.session_epoch,
               "timestamp": state.source_timestamp_ms, "track": state.track,
               "lap": state.lap_number, "total": state.total_laps,
               "weather": state.weather, "safety_car": state.safety_car,
               "player": asdict(state.player), "rivals": [asdict(item) for item in state.rivals], "raw": state.raw}
    def canonical(value: Any) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            # Preserve large integers exactly while equating 247 and 247.0.
            number = Decimal(str(value))
            if number == 0:
                number = Decimal(0)
            return ["number", str(number.normalize())]
        if isinstance(value, dict):
            return ["object", {str(key): canonical(item) for key, item in value.items()}]
        if isinstance(value, (list, tuple)):
            return ["array", [canonical(item) for item in value]]
        return ["scalar", value]
    return hashlib.sha256(json.dumps(canonical(payload), sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def assess_domain(state: SessionState, thresholds: StrategyThresholds | None = None) -> AssessmentResult:
    binding = snapshot_id(state)
    cached = state.assessment
    if cached is not None and cached.rule_version == DOMAIN_RULE_VERSION and cached.snapshot_id == binding and (thresholds is None or cached.thresholds == asdict(thresholds)):
        return cached
    if thresholds is None:
        thresholds = StrategyThresholds(**cached.thresholds) if cached is not None else StrategyThresholds()
    player = state.player
    fuel = assess_fuel(state)
    wear = valid_percentage(player.tyre.wear_pct)
    ers = valid_percentage(player.ers_pct)
    ahead, behind = _nonnegative(player.gap_ahead_s), _nonnegative(player.gap_behind_s)
    labels = StateAssessment(
        fuel_state=fuel.verdict,
        tyre_state="unavailable" if wear is None else "box_now" if wear >= thresholds.tyre_wear_box else "manage" if wear >= thresholds.tyre_wear_warn else "stable",
        ers_state="unavailable" if ers is None else "low" if ers <= thresholds.ers_low_pct else "stable",
        race_state="unavailable" if normalize_race_control(state.safety_car) is None else "controlled" if race_control_active(state.safety_car) else "green",
        attack_state="unavailable" if ahead is None else "available" if player.drs_available and ahead <= thresholds.rival_gap_attack else "closed",
        defend_state="unavailable" if behind is None else "urgent" if behind <= thresholds.rival_gap_defend else "clear",
        dynamics_state="unstable" if "unstable" in player.status_tags else "unavailable" if "unavailable" in player.status_tags else "stable",
    )
    state.assessment = AssessmentResult(binding, DOMAIN_RULE_VERSION, labels, fuel.to_dict(), asdict(thresholds))
    return state.assessment

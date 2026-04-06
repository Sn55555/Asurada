from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import SessionState, StrategyDecision, StrategyMessage


STRATEGY_ENGLISH_COPY: dict[str, tuple[str, str]] = {
    "NONE": ("Standby", "No active advisory"),
    "DEFEND_WINDOW": ("Defend", "Rear pressure high"),
    "ATTACK_WINDOW": ("Attack", "Attack window open"),
    "LOW_FUEL": ("Fuel Save", "Fuel margin low"),
    "DYNAMICS_UNSTABLE": ("Stabilize", "Car balance unstable"),
    "FRONT_LOAD": ("Front Load", "Front axle under load"),
    "SAFETY_CAR": ("Safety Car", "Pace controlled"),
    "VIRTUAL_SAFETY_CAR": ("VSC", "Pace controlled"),
    "PIT_WINDOW": ("Pit Window", "Pit timing open"),
    "OVERTAKE": ("Overtake", "Passing opportunity"),
}


@dataclass
class GapPayload:
    ahead_s: float | None
    behind_s: float | None
    ahead_source: str
    behind_source: str
    front_rival_name: str | None
    rear_rival_name: str | None
    front_rival_position: int | None
    rear_rival_position: int | None


@dataclass
class DashboardPayload:
    payload_version: str
    timestamp_ms: int
    source_timestamp_ms: int
    session: dict[str, Any]
    car: dict[str, Any]
    tyres: dict[str, Any]
    damage: dict[str, Any]
    gaps: GapPayload
    strategy: dict[str, Any]
    timing: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gaps"] = asdict(self.gaps)
        return payload


def build_dashboard_payload(state: SessionState, decision: StrategyDecision) -> dict[str, Any]:
    raw = state.raw
    primary_message = decision.messages[0] if decision.messages else None
    strategy_code = primary_message.code if primary_message else "NONE"
    strategy_title, strategy_detail = _english_strategy_copy(primary_message)
    payload = DashboardPayload(
        payload_version="v1",
        timestamp_ms=int(raw.get("runtime_timing", {}).get("output_finished_at_ms") or state.source_timestamp_ms),
        source_timestamp_ms=int(state.source_timestamp_ms),
        session={
            "track": state.track,
            "lap_number": state.lap_number,
            "total_laps": state.total_laps,
            "position": state.player.position,
            "weather": state.weather,
            "safety_car": state.safety_car,
        },
        car={
            "speed_kph": round(state.player.speed_kph, 1),
            "gear": _int_or_none(raw.get("gear")),
            "rpm": _int_or_none(raw.get("rpm")),
            "drs_open": bool(state.player.drs_available),
            "ers_pct": round(state.player.ers_pct, 2),
            "fuel_in_tank": _float_or_none(raw.get("fuel_in_tank")),
            "fuel_laps_remaining": round(state.player.fuel_laps_remaining, 2),
        },
        tyres={
            "compound": state.player.tyre.compound,
            "age_laps": state.player.tyre.age_laps,
            "wear_pct_avg": round(state.player.tyre.wear_pct, 2),
            "wear_pct_corners": [_float_or_none(item) for item in raw.get("tyres_wear_pct", [])],
            "surface_temperature_c": [int(item) for item in state.player.tyre.surface_temperature_c],
            "inner_temperature_c": [int(item) for item in state.player.tyre.inner_temperature_c],
            "surface_temperature_avg_c": _float_or_none(raw.get("tyres_surface_temperature_avg_c")),
            "inner_temperature_avg_c": _float_or_none(raw.get("tyres_inner_temperature_avg_c")),
        },
        damage={
            "wing_damage_pct": dict(raw.get("wing_damage_pct", {})),
            "floor_damage_pct": _int_or_none(raw.get("floor_damage_pct")),
            "diffuser_damage_pct": _int_or_none(raw.get("diffuser_damage_pct")),
            "sidepod_damage_pct": _int_or_none(raw.get("sidepod_damage_pct")),
            "gearbox_damage_pct": _int_or_none(raw.get("gearbox_damage_pct")),
            "engine_damage_pct": _int_or_none(raw.get("engine_damage_pct")),
            "engine_components_damage_pct": dict(raw.get("engine_components_damage_pct", {})),
            "engine_blown": bool(raw.get("engine_blown", False)),
            "engine_seized": bool(raw.get("engine_seized", False)),
            "body_damage_pct": _aggregate_body_damage(raw),
            "powertrain_damage_pct": _aggregate_powertrain_damage(raw),
        },
        gaps=GapPayload(
            ahead_s=_gap_value(raw.get("official_gap_ahead_s"), raw.get("estimated_gap_ahead_s")),
            behind_s=_gap_value(raw.get("official_gap_behind_s"), raw.get("estimated_gap_behind_s")),
            ahead_source=_gap_source(raw.get("official_gap_ahead_s"), raw.get("estimated_gap_ahead_s")),
            behind_source=_gap_source(raw.get("official_gap_behind_s"), raw.get("estimated_gap_behind_s")),
            front_rival_name=raw.get("front_rival_name"),
            rear_rival_name=raw.get("rear_rival_name"),
            front_rival_position=_int_or_none(raw.get("front_rival_position")),
            rear_rival_position=_int_or_none(raw.get("rear_rival_position")),
        ),
        strategy={
            "primary_action": strategy_code,
            "title": strategy_title,
            "detail": strategy_detail,
            "priority": primary_message.priority if primary_message else 0,
            "ordered_actions": _ordered_action_codes(decision.messages),
        },
        timing=dict(raw.get("runtime_timing", {})),
    )
    return payload.to_dict()


def placeholder_dashboard_payload() -> dict[str, Any]:
    return {
        "payload_version": "v1",
        "timestamp_ms": 0,
        "source_timestamp_ms": 0,
        "session": {"track": "Standby", "lap_number": 0, "total_laps": 0, "position": 0, "weather": "N/A", "safety_car": "NONE"},
        "car": {"speed_kph": 0, "gear": 0, "rpm": 0, "drs_open": False, "ers_pct": 0, "fuel_in_tank": None, "fuel_laps_remaining": 0},
        "tyres": {
            "compound": "N/A",
            "age_laps": 0,
            "wear_pct_avg": 0,
            "wear_pct_corners": [0, 0, 0, 0],
            "surface_temperature_c": [0, 0, 0, 0],
            "inner_temperature_c": [0, 0, 0, 0],
            "surface_temperature_avg_c": 0,
            "inner_temperature_avg_c": 0,
        },
        "damage": {
            "wing_damage_pct": {"front_left": 0, "front_right": 0, "rear": 0},
            "floor_damage_pct": 0,
            "diffuser_damage_pct": 0,
            "sidepod_damage_pct": 0,
            "gearbox_damage_pct": 0,
            "engine_damage_pct": 0,
            "engine_components_damage_pct": {},
            "engine_blown": False,
            "engine_seized": False,
            "body_damage_pct": 0,
            "powertrain_damage_pct": 0,
        },
        "gaps": {
            "ahead_s": None,
            "behind_s": None,
            "ahead_source": "missing",
            "behind_source": "missing",
            "front_rival_name": None,
            "rear_rival_name": None,
            "front_rival_position": None,
            "rear_rival_position": None,
        },
        "strategy": {"primary_action": "NONE", "title": "Standby", "detail": "", "priority": 0, "ordered_actions": []},
        "timing": {},
    }


def _ordered_action_codes(messages: list[StrategyMessage]) -> list[str]:
    return [message.code for message in messages]


def _english_strategy_copy(message: StrategyMessage | None) -> tuple[str, str]:
    if message is None:
        return STRATEGY_ENGLISH_COPY["NONE"]
    mapped = STRATEGY_ENGLISH_COPY.get(message.code)
    if mapped is not None:
        return mapped
    title = message.code.replace("_", " ").title()
    detail = title
    return title, detail


def _gap_value(official_value: Any, estimated_value: Any) -> float | None:
    if official_value is not None:
        return round(float(official_value), 3)
    if estimated_value is not None:
        return round(float(estimated_value), 3)
    return None


def _gap_source(official_value: Any, estimated_value: Any) -> str:
    if official_value is not None:
        return "official"
    if estimated_value is not None:
        return "estimated"
    return "missing"


def _aggregate_body_damage(raw: dict[str, Any]) -> int:
    wing = raw.get("wing_damage_pct", {}) or {}
    values = [
        _int_or_zero(wing.get("front_left")),
        _int_or_zero(wing.get("front_right")),
        _int_or_zero(wing.get("rear")),
        _int_or_zero(raw.get("floor_damage_pct")),
        _int_or_zero(raw.get("diffuser_damage_pct")),
        _int_or_zero(raw.get("sidepod_damage_pct")),
    ]
    return int(round(max(values) if values else 0))


def _aggregate_powertrain_damage(raw: dict[str, Any]) -> int:
    values = [
        _int_or_zero(raw.get("gearbox_damage_pct")),
        _int_or_zero(raw.get("engine_damage_pct")),
    ]
    component_map = raw.get("engine_components_damage_pct", {}) or {}
    values.extend(_int_or_zero(value) for value in component_map.values())
    return int(round(max(values) if values else 0))


def _float_or_none(value: Any) -> float | None:
    return None if value is None else round(float(value), 3)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _int_or_zero(value: Any) -> int:
    return 0 if value is None else int(value)

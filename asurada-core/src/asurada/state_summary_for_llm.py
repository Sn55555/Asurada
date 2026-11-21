from __future__ import annotations

from .race_control import normalize_race_control

from dataclasses import asdict, dataclass, field
from typing import Any

from .assessment import assess_fuel, assess_domain, snapshot_id, valid_percentage
from .conversation_context import ConversationContext
from .models import SessionState, StrategyMessage
from .runtime_context import RuntimeContextDetector


@dataclass(frozen=True)
class LlmStateSummary:
    summary_version: str
    state_snapshot: dict[str, Any]
    strategy_snapshot: dict[str, Any]
    conversation_snapshot: dict[str, Any]
    capability_snapshot: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_state_summary_for_llm(
    *,
    state: SessionState,
    primary_message: StrategyMessage | None,
    conversation_context: ConversationContext,
    capability_snapshot: dict[str, Any] | None = None,
) -> LlmStateSummary:
    conversation_context.bind(state)
    runtime_context = RuntimeContextDetector().detect(state=state)
    player = state.player
    front_rival = _closest_rival(state, player.position - 1)
    rear_rival = _closest_rival(state, player.position + 1)
    state_snapshot = {
        "session_uid": state.session_uid,
        "session_epoch": state.session_epoch,
        "track": state.track,
        "lap_number": state.lap_number,
        "total_laps": state.total_laps,
        "weather": state.weather,
        "safety_car": normalize_race_control(state.safety_car),
        "player_position": player.position,
        "player_name": player.name,
        "gap_ahead_s": player.gap_ahead_s,
        "gap_behind_s": player.gap_behind_s,
        "drs_available": player.drs_available,
        "ers_pct": valid_percentage(player.ers_pct),
        "fuel_laps_remaining": player.fuel_laps_remaining,
        "speed_kph": player.speed_kph,
        "tyre": {
            "compound": player.tyre.compound,
            "wear_pct": valid_percentage(player.tyre.wear_pct),
            "age_laps": player.tyre.age_laps,
            "surface_temperature_c": list(player.tyre.surface_temperature_c),
            "inner_temperature_c": list(player.tyre.inner_temperature_c),
        },
        "damage": {
            "wing_damage_pct": state.raw.get("wing_damage_pct"),
            "floor_damage_pct": state.raw.get("floor_damage_pct"),
            "diffuser_damage_pct": state.raw.get("diffuser_damage_pct"),
            "sidepod_damage_pct": state.raw.get("sidepod_damage_pct"),
            "gearbox_damage_pct": state.raw.get("gearbox_damage_pct"),
            "engine_damage_pct": state.raw.get("engine_damage_pct"),
            "engine_components_damage_pct": state.raw.get("engine_components_damage_pct"),
            "engine_blown": state.raw.get("engine_blown"),
            "engine_seized": state.raw.get("engine_seized"),
        },
        "recent_position_trend": _position_trend_summary(state),
        "dynamics": _dynamics_summary(state),
        "pit": {
            "pit_status": state.raw.get("pit_status"),
            "num_pit_stops": state.raw.get("num_pit_stops"),
            "pit_lane_timer_active": state.raw.get("pit_lane_timer_active"),
            "pit_stop_timer_ms": state.raw.get("pit_stop_timer_ms"),
        },
        "penalties": {
            "total_warnings": state.raw.get("total_warnings"),
            "corner_cutting_warnings": state.raw.get("corner_cutting_warnings"),
            "num_unserved_drive_through_pens": state.raw.get("num_unserved_drive_through_pens"),
            "num_unserved_stop_go_pens": state.raw.get("num_unserved_stop_go_pens"),
            "pit_stop_should_serve_pen": state.raw.get("pit_stop_should_serve_pen"),
        },
        "front_rival": _driver_summary(front_rival) if front_rival is not None else None,
        "rear_rival": _driver_summary(rear_rival) if rear_rival is not None else None,
    }
    state_snapshot["assessment"] = asdict(assess_domain(state)) if runtime_context.racing_active else None
    state_snapshot["fuel_assessment"] = assess_fuel(state).to_dict() if runtime_context.racing_active else None
    state_snapshot["runtime_context"] = runtime_context.to_dict()
    if not runtime_context.racing_active:
        state_snapshot = _mask_non_racing_state_snapshot(state_snapshot)
    strategy_snapshot = {
        "primary_message": None
        if primary_message is None or not runtime_context.racing_active
        else {
            "code": primary_message.code,
            "priority": primary_message.priority,
            "title": primary_message.title,
            "detail": primary_message.detail,
        }
    }
    record = state.decision_record
    strategy_snapshot["decision_record"] = asdict(record) if runtime_context.racing_active and record is not None and record.snapshot_id == snapshot_id(state) else None
    return LlmStateSummary(
        summary_version="v1",
        state_snapshot=state_snapshot,
        strategy_snapshot=strategy_snapshot,
        conversation_snapshot=conversation_context.snapshot(include_racing=runtime_context.racing_active),
        capability_snapshot=capability_snapshot or {},
        metadata={
            "source_timestamp_ms": runtime_context.metadata["source_timestamp_ms"],
            "runtime_context": runtime_context.to_dict(),
        },
    )


def _driver_summary(driver: Any) -> dict[str, Any]:
    return {
        "name": getattr(driver, "name", None),
        "team_id": getattr(driver, "team_id", None),
        "race_number": getattr(driver, "race_number", None),
        "position": getattr(driver, "position", None),
        "gap_ahead_s": getattr(driver, "gap_ahead_s", None),
        "gap_behind_s": getattr(driver, "gap_behind_s", None),
        "gap_source": getattr(driver, "gap_source", None),
        "gap_confidence": getattr(driver, "gap_confidence", None),
        "gap_source_ahead": getattr(driver, "gap_source_ahead", None),
        "gap_source_behind": getattr(driver, "gap_source_behind", None),
        "gap_confidence_ahead": getattr(driver, "gap_confidence_ahead", None),
        "gap_confidence_behind": getattr(driver, "gap_confidence_behind", None),
        "estimated_gap_source": getattr(driver, "estimated_gap_source", None),
        "estimated_gap_confidence": getattr(driver, "estimated_gap_confidence", None),
        "drs_available": getattr(driver, "drs_available", None),
        "ers_pct": valid_percentage(getattr(driver, "ers_pct", None)),
        "pit_status": getattr(driver, "pit_status", None),
        "tyre": {
            "compound": getattr(getattr(driver, "tyre", None), "compound", None),
            "wear_pct": valid_percentage(getattr(getattr(driver, "tyre", None), "wear_pct", None)),
            "age_laps": getattr(getattr(driver, "tyre", None), "age_laps", None),
        },
        "tyre_damage_pct": getattr(driver, "tyre_damage_pct", None),
        "engine_damage_pct": getattr(driver, "engine_damage_pct", None),
        "aero_damage_pct": getattr(driver, "aero_damage_pct", None),
        "speed_kph": getattr(driver, "speed_kph", None),
        "lap_distance_m": getattr(driver, "lap_distance_m", None),
    }


def _position_trend_summary(state: SessionState) -> dict[str, Any] | None:
    lap_positions = (state.raw.get("lap_positions") or {}).get("player_lap_positions") or []
    if not isinstance(lap_positions, list):
        return None
    valid_rows = [
        row for row in lap_positions
        if isinstance(row, dict) and isinstance(row.get("lap_number"), int) and row.get("position") is not None
    ]
    if len(valid_rows) < 2:
        return None
    recent = valid_rows[-3:]
    start = recent[0]
    end = recent[-1]
    start_position = int(start["position"])
    end_position = int(end["position"])
    return {
        "start_lap": int(start["lap_number"]),
        "end_lap": int(end["lap_number"]),
        "start_position": start_position,
        "end_position": end_position,
        "net_gain": start_position - end_position,
        "positions": [int(item["position"]) for item in recent],
    }


def _max_abs(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    normalized = []
    for item in values:
        try:
            normalized.append(abs(float(item)))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return None
    return max(normalized)


def _dynamics_summary(state: SessionState) -> dict[str, Any]:
    raw = state.raw
    angular_velocity = raw.get("angular_velocity") or {}
    angular_acceleration = raw.get("angular_acceleration") or {}
    front_roll_angle = raw.get("front_roll_angle")
    rear_roll_angle = raw.get("rear_roll_angle")
    roll_balance = None
    try:
        if front_roll_angle is not None and rear_roll_angle is not None:
            roll_balance = abs(float(front_roll_angle) - float(rear_roll_angle))
    except (TypeError, ValueError):
        roll_balance = None
    return {
        "max_wheel_slip_ratio": _max_abs(raw.get("wheel_slip_ratio")),
        "max_wheel_slip_angle": _max_abs(raw.get("wheel_slip_angle")),
        "max_wheel_lat_force": _max_abs(raw.get("wheel_lat_force")),
        "max_wheel_long_force": _max_abs(raw.get("wheel_long_force")),
        "max_wheel_vert_force": _max_abs(raw.get("wheel_vert_force")),
        "front_aero_height": raw.get("front_aero_height"),
        "rear_aero_height": raw.get("rear_aero_height"),
        "yaw_rate": (angular_velocity or {}).get("yaw"),
        "pitch_rate": (angular_velocity or {}).get("pitch"),
        "roll_rate": (angular_velocity or {}).get("roll"),
        "yaw_accel": (angular_acceleration or {}).get("yaw"),
        "pitch_accel": (angular_acceleration or {}).get("pitch"),
        "roll_accel": (angular_acceleration or {}).get("roll"),
        "front_roll_angle": front_roll_angle,
        "rear_roll_angle": rear_roll_angle,
        "roll_balance": roll_balance,
        "chassis_yaw": raw.get("chassis_yaw"),
        "chassis_pitch": raw.get("chassis_pitch"),
        "max_wheel_camber_abs": _max_abs(raw.get("wheel_camber")),
        "max_wheel_camber_gain_abs": _max_abs(raw.get("wheel_camber_gain")),
    }


def _closest_rival(state: SessionState, target_position: int) -> Any | None:
    if target_position <= 0:
        return None
    for rival in state.rivals:
        if rival.position == target_position:
            return rival
    return None


def _mask_non_racing_state_snapshot(state_snapshot: dict[str, Any]) -> dict[str, Any]:
    last_known = {
        "track": state_snapshot.get("track"),
        "lap_number": state_snapshot.get("lap_number"),
        "total_laps": state_snapshot.get("total_laps"),
        "player_position": state_snapshot.get("player_position"),
    }
    masked = dict(state_snapshot)
    masked.update(
        {
            "track": "Standby",
            "lap_number": 0,
            "total_laps": 0,
            "weather": "N/A",
            "safety_car": None,
            "player_position": None,
            "gap_ahead_s": None,
            "gap_behind_s": None,
            "drs_available": None,
            "ers_pct": None,
            "fuel_laps_remaining": None,
            "speed_kph": None,
            "tyre": {
                "compound": None,
                "wear_pct": None,
                "age_laps": None,
                "surface_temperature_c": [],
                "inner_temperature_c": [],
            },
            "damage": {
                "wing_damage_pct": None,
                "floor_damage_pct": None,
                "diffuser_damage_pct": None,
                "sidepod_damage_pct": None,
                "gearbox_damage_pct": None,
                "engine_damage_pct": None,
                "engine_components_damage_pct": None,
                "engine_blown": None,
                "engine_seized": None,
            },
            "recent_position_trend": None,
            "dynamics": None,
            "pit": {
                "pit_status": None,
                "num_pit_stops": None,
                "pit_lane_timer_active": None,
                "pit_stop_timer_ms": None,
            },
            "penalties": {
                "total_warnings": None,
                "corner_cutting_warnings": None,
                "num_unserved_drive_through_pens": None,
                "num_unserved_stop_go_pens": None,
                "pit_stop_should_serve_pen": None,
            },
            "front_rival": None,
            "rear_rival": None,
            "last_known_race_snapshot": last_known,
        }
    )
    return masked

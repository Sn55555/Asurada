from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
    runtime_context = RuntimeContextDetector().detect(state=state)
    player = state.player
    state_snapshot = {
        "session_uid": state.session_uid,
        "track": state.track,
        "lap_number": state.lap_number,
        "total_laps": state.total_laps,
        "weather": state.weather,
        "safety_car": state.safety_car,
        "player_position": player.position,
        "player_name": player.name,
        "gap_ahead_s": player.gap_ahead_s,
        "gap_behind_s": player.gap_behind_s,
        "drs_available": player.drs_available,
        "ers_pct": player.ers_pct,
        "fuel_laps_remaining": player.fuel_laps_remaining,
        "speed_kph": player.speed_kph,
        "tyre": {
            "compound": player.tyre.compound,
            "wear_pct": player.tyre.wear_pct,
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
            "engine_blown": state.raw.get("engine_blown"),
            "engine_seized": state.raw.get("engine_seized"),
        },
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
        "front_rival": _driver_summary(state.rivals[0]) if state.rivals else None,
    }
    state_snapshot["runtime_context"] = runtime_context.to_dict()
    if not runtime_context.racing_active:
        state_snapshot = _mask_non_racing_state_snapshot(state_snapshot)
    strategy_snapshot = {
        "primary_message": None
        if primary_message is None
        else {
            "code": primary_message.code,
            "priority": primary_message.priority,
            "title": primary_message.title,
            "detail": primary_message.detail,
        }
    }
    return LlmStateSummary(
        summary_version="v1",
        state_snapshot=state_snapshot,
        strategy_snapshot=strategy_snapshot,
        conversation_snapshot=conversation_context.snapshot(),
        capability_snapshot=capability_snapshot or {},
        metadata={
            "source_timestamp_ms": state.source_timestamp_ms,
            "runtime_context": runtime_context.to_dict(),
        },
    )


def _driver_summary(driver: Any) -> dict[str, Any]:
    return {
        "name": getattr(driver, "name", None),
        "position": getattr(driver, "position", None),
        "gap_ahead_s": getattr(driver, "gap_ahead_s", None),
        "gap_behind_s": getattr(driver, "gap_behind_s", None),
        "drs_available": getattr(driver, "drs_available", None),
        "ers_pct": getattr(driver, "ers_pct", None),
        "speed_kph": getattr(driver, "speed_kph", None),
    }


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
            "safety_car": "NONE",
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
                "engine_blown": None,
                "engine_seized": None,
            },
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
            "last_known_race_snapshot": last_known,
        }
    )
    return masked

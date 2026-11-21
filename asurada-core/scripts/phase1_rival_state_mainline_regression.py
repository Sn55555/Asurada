from __future__ import annotations

from regression_support import emit_result, runtime_clock

import json

from asurada.conversation_context import ConversationContext
from asurada.decode import decode_snapshot
from asurada.models import StrategyMessage
from asurada.state_summary_for_llm import build_state_summary_for_llm


@runtime_clock(1778800000000)
def run_phase1_rival_state_mainline_regression() -> dict[str, object]:
    snapshot = {
        "session_uid": "session-rival-mainline",
        "track": "Suzuka",
        "lap_number": 21,
        "total_laps": 53,
        "weather": "LightCloud",
        "safety_car": "NONE",
        "source_timestamp_ms": 1_778_800_000_000,
        "player": {
            "car_index": 0,
            "name": "Leclerc",
            "team_id": 0,
            "race_number": 16,
            "position": 4,
            "lap": 21,
            "lap_distance_m": 3184.2,
            "gap_ahead_s": 1.284,
            "gap_behind_s": 0.944,
            "gap_source": "official_lapdata_adjacent",
            "gap_confidence": "high",
            "gap_source_ahead": "official_lapdata_adjacent",
            "gap_source_behind": "official_lapdata_adjacent",
            "gap_confidence_ahead": "high",
            "gap_confidence_behind": "high",
            "estimated_gap_source": None,
            "estimated_gap_confidence": None,
            "fuel_laps_remaining": 10.6,
            "ers_pct": 61.0,
            "drs_available": False,
            "pit_status": "NONE",
            "tyre": {
                "compound": "Medium",
                "wear_pct": 38.0,
                "age_laps": 12,
                "surface_temperature_c": [96, 97, 95, 95],
                "inner_temperature_c": [90, 91, 89, 89],
            },
            "tyre_damage_pct": 11.5,
            "engine_damage_pct": 7,
            "aero_damage_pct": 6,
            "speed_kph": 267.0,
            "world_position_x": 102.4,
            "world_position_y": 0.8,
            "world_position_z": -38.2,
            "status_tags": ["defend_window"],
        },
        "rivals": [
            {
                "car_index": 2,
                "name": "Hamilton",
                "team_id": 1,
                "race_number": 44,
                "position": 3,
                "lap": 21,
                "lap_distance_m": 3198.9,
                "gap_ahead_s": 0.821,
                "gap_behind_s": 1.284,
                "gap_source": "official_lapdata_adjacent",
                "gap_confidence": "high",
                "gap_source_ahead": "official_lapdata_adjacent",
                "gap_source_behind": "official_lapdata_adjacent",
                "gap_confidence_ahead": "high",
                "gap_confidence_behind": "high",
                "estimated_gap_source": None,
                "estimated_gap_confidence": None,
                "fuel_laps_remaining": 10.8,
                "ers_pct": 54.0,
                "drs_available": False,
                "pit_status": "NONE",
                "tyre": {
                    "compound": "Hard",
                    "wear_pct": 33.5,
                    "age_laps": 17,
                },
                "tyre_damage_pct": 9.5,
                "engine_damage_pct": 6,
                "aero_damage_pct": 3,
                "speed_kph": 268.0,
                "world_position_x": 107.2,
                "world_position_y": 0.8,
                "world_position_z": -42.3,
                "status_tags": [],
            },
            {
                "car_index": 1,
                "name": "Russell",
                "team_id": 3,
                "race_number": 63,
                "position": 5,
                "lap": 21,
                "lap_distance_m": 3172.8,
                "gap_ahead_s": 0.944,
                "gap_behind_s": 1.102,
                "gap_source": "official_lapdata_adjacent",
                "gap_confidence": "high",
                "gap_source_ahead": "official_lapdata_adjacent",
                "gap_source_behind": "official_lapdata_adjacent",
                "gap_confidence_ahead": "high",
                "gap_confidence_behind": "high",
                "estimated_gap_source": "estimated_total_distance_same_lap",
                "estimated_gap_confidence": "medium",
                "fuel_laps_remaining": 10.1,
                "ers_pct": 58.0,
                "drs_available": True,
                "pit_status": "NONE",
                "tyre": {
                    "compound": "Medium",
                    "wear_pct": 41.5,
                    "age_laps": 13,
                },
                "tyre_damage_pct": 13.5,
                "engine_damage_pct": 9,
                "aero_damage_pct": 4,
                "speed_kph": 265.0,
                "world_position_x": 96.1,
                "world_position_y": 0.8,
                "world_position_z": -31.7,
                "status_tags": [],
            },
        ],
        "raw": {
            "pit_status": "NONE",
            "num_pit_stops": 1,
            "total_warnings": 1,
            "corner_cutting_warnings": 1,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
            "wing_damage_pct": {"front_left": 4, "front_right": 5, "rear": 6},
            "floor_damage_pct": 4,
            "diffuser_damage_pct": 3,
            "sidepod_damage_pct": 2,
            "gearbox_damage_pct": 5,
            "engine_damage_pct": 7,
            "engine_blown": False,
            "engine_seized": False,
        },
    }
    state = decode_snapshot(snapshot)
    summary = build_state_summary_for_llm(
        state=state,
        primary_message=StrategyMessage(
            code="DEFEND_WINDOW",
            priority=92,
            title="防守窗口",
            detail="后车已接近 DRS 线。",
        ),
        conversation_context=ConversationContext(),
        capability_snapshot={},
    )
    rear_rival = next(item for item in state.rivals if item.position == 5)
    front_rival_summary = (summary.state_snapshot or {}).get("front_rival") or {}
    rear_rival_summary = (summary.state_snapshot or {}).get("rear_rival") or {}
    checks = {
        "rear_rival_preserved": rear_rival.team_id == 3 and rear_rival.race_number == 63,
        "rear_gap_quality_preserved": rear_rival.gap_source == "official_lapdata_adjacent"
        and rear_rival.gap_confidence == "high",
        "rear_estimated_gap_preserved": rear_rival.estimated_gap_source == "estimated_total_distance_same_lap"
        and rear_rival.estimated_gap_confidence == "medium",
        "rear_damage_preserved": rear_rival.tyre_damage_pct == 13.5
        and rear_rival.engine_damage_pct == 9
        and rear_rival.aero_damage_pct == 4,
        "rear_position_preserved": rear_rival.lap_distance_m == 3172.8 and rear_rival.world_position_z == -31.7,
        "llm_summary_front_rival_is_actual_front": front_rival_summary.get("name") == "Hamilton"
        and front_rival_summary.get("position") == 3,
        "llm_summary_rear_rival_is_actual_rear": rear_rival_summary.get("name") == "Russell"
        and rear_rival_summary.get("position") == 5
        and rear_rival_summary.get("gap_confidence") == "high"
        and rear_rival_summary.get("pit_status") == "NONE"
        and (rear_rival_summary.get("tyre") or {}).get("wear_pct") == 41.5,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "rear_rival": {
                "team_id": rear_rival.team_id,
                "race_number": rear_rival.race_number,
                "pit_status": rear_rival.pit_status,
                "gap_source": rear_rival.gap_source,
                "gap_confidence": rear_rival.gap_confidence,
                "estimated_gap_source": rear_rival.estimated_gap_source,
                "estimated_gap_confidence": rear_rival.estimated_gap_confidence,
                "tyre_damage_pct": rear_rival.tyre_damage_pct,
                "engine_damage_pct": rear_rival.engine_damage_pct,
                "aero_damage_pct": rear_rival.aero_damage_pct,
                "lap_distance_m": rear_rival.lap_distance_m,
                "world_position_z": rear_rival.world_position_z,
            },
            "front_rival_summary": front_rival_summary,
            "rear_rival_summary": rear_rival_summary,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_state_mainline_regression())

from __future__ import annotations

from regression_support import emit_result, runtime_clock

import json

from asurada.conversation_context import ConversationContext
from asurada.models import DriverState, SessionState, TyreState
from asurada.state_summary_for_llm import build_state_summary_for_llm


@runtime_clock(1778950000000)
def run_phase1_llm_summary_auxiliary_fields_regression() -> dict[str, object]:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=12,
        gap_ahead_s=0.8,
        gap_behind_s=1.2,
        fuel_laps_remaining=16.0,
        ers_pct=64.0,
        drs_available=True,
        tyre=TyreState(compound="Medium", wear_pct=31.0, age_laps=8),
        speed_kph=281.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=3,
        lap=12,
        gap_ahead_s=1.9,
        gap_behind_s=0.8,
        fuel_laps_remaining=15.0,
        ers_pct=60.0,
        drs_available=False,
        tyre=TyreState(compound="Hard", wear_pct=28.0, age_laps=12),
        speed_kph=279.0,
        status_tags=[],
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=5,
        lap=12,
        gap_ahead_s=1.2,
        gap_behind_s=1.8,
        fuel_laps_remaining=15.5,
        ers_pct=62.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=30.0, age_laps=8),
        speed_kph=280.0,
        status_tags=[],
    )
    state = SessionState(
        session_uid="session-llm-summary-aux-fields",
        track="Suzuka",
        lap_number=12,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_950_000_000,
        raw={
            "wing_damage_pct": {"front_left": 6, "front_right": 4, "rear": 2},
            "floor_damage_pct": 8,
            "diffuser_damage_pct": 5,
            "sidepod_damage_pct": 3,
            "gearbox_damage_pct": 11,
            "engine_damage_pct": 23,
            "engine_components_damage_pct": {
                "mguh": 18,
                "energy_store": 12,
                "control_electronics": 14,
                "ice": 36,
                "mguk": 29,
                "turbo_charger": 20,
            },
            "lap_positions": {
                "player_lap_positions": [
                    {"lap_index": 9, "lap_number": 10, "position": 6},
                    {"lap_index": 10, "lap_number": 11, "position": 5},
                    {"lap_index": 11, "lap_number": 12, "position": 4},
                ]
            },
            "wheel_slip_ratio": [0.05, 0.06, 0.11, 0.08],
            "wheel_slip_angle": [0.03, 0.06, 0.12, 0.09],
            "wheel_lat_force": [3.1, 3.3, 4.2, 3.8],
            "wheel_long_force": [1.4, 1.5, 1.9, 1.6],
            "wheel_vert_force": [4.8, 4.9, 5.2, 5.0],
            "angular_velocity": {"yaw": 0.82, "pitch": 0.11, "roll": 0.19},
            "angular_acceleration": {"yaw": 2.6, "pitch": 0.4, "roll": 0.7},
            "front_aero_height": 31.7,
            "rear_aero_height": 34.6,
            "front_roll_angle": 0.54,
            "rear_roll_angle": 1.63,
            "chassis_yaw": 0.21,
            "chassis_pitch": 0.08,
            "wheel_camber": [3.2, 3.1, 2.7, 2.8],
            "wheel_camber_gain": [0.24, 0.27, 0.39, 0.35],
            "pit_status": "NONE",
            "num_pit_stops": 0,
            "pit_lane_timer_active": False,
            "pit_stop_timer_ms": 0,
            "total_warnings": 0,
            "corner_cutting_warnings": 0,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
        },
    )
    summary = build_state_summary_for_llm(
        state=state,
        primary_message=None,
        conversation_context=ConversationContext(),
        capability_snapshot={},
    ).to_dict()
    snapshot = summary["state_snapshot"]
    checks = {
        "engine_components_in_damage_summary": snapshot["damage"]["engine_components_damage_pct"]["ice"] == 36,
        "position_trend_added": snapshot["recent_position_trend"]["net_gain"] == 2,
        "position_trend_positions_present": snapshot["recent_position_trend"]["positions"] == [6, 5, 4],
        "dynamics_yaw_accel_present": snapshot["dynamics"]["yaw_accel"] == 2.6,
        "dynamics_roll_balance_present": abs(snapshot["dynamics"]["roll_balance"] - 1.09) < 1e-6,
        "dynamics_lat_force_present": snapshot["dynamics"]["max_wheel_lat_force"] == 4.2,
        "dynamics_camber_gain_present": snapshot["dynamics"]["max_wheel_camber_gain_abs"] == 0.39,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": snapshot,
    }


if __name__ == "__main__":
    emit_result(run_phase1_llm_summary_auxiliary_fields_regression())

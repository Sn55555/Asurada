from __future__ import annotations

from regression_support import emit_result

import json

from asurada.models import DriverState, SessionState, TyreState
from asurada.response_composer import compose_structured_query_response


def _build_state() -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=20,
        gap_ahead_s=1.5,
        gap_behind_s=1.4,
        fuel_laps_remaining=11.0,
        ers_pct=57.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=45.0, age_laps=11),
        speed_kph=274.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=20,
        gap_ahead_s=1.8,
        gap_behind_s=1.5,
        fuel_laps_remaining=11.5,
        ers_pct=60.0,
        drs_available=False,
        tyre=TyreState(compound="Hard", wear_pct=33.0, age_laps=15),
        speed_kph=272.0,
        status_tags=[],
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=20,
        gap_ahead_s=1.4,
        gap_behind_s=1.9,
        fuel_laps_remaining=10.8,
        ers_pct=61.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=39.0, age_laps=11),
        speed_kph=275.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="session-motionex-response",
        track="Suzuka",
        lap_number=20,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_960_000_000,
        raw={
            "wheel_slip_angle": [0.05, 0.08, 0.13, 0.11],
            "wheel_slip_ratio": [0.06, 0.08, 0.12, 0.10],
            "front_aero_height": 32.0,
            "rear_aero_height": 35.2,
            "angular_velocity": {"yaw": 0.92, "pitch": 0.15, "roll": 0.22},
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
            "pit_status": "NONE",
        },
    )


def run_phase1_motionex_response_regression() -> dict[str, object]:
    state = _build_state()
    main_risk_text, _ = compose_structured_query_response(state=state, query_kind="main_risk_summary")
    next_focus_text, _ = compose_structured_query_response(state=state, query_kind="next_lap_focus")
    why_not_attack_text, _ = compose_structured_query_response(state=state, query_kind="why_not_attack")
    overall_text, _ = compose_structured_query_response(state=state, query_kind="overall_situation")

    accel_state = _build_state()
    accel_state.raw.update(
        {
            "wheel_slip_angle": [0.03, 0.04, 0.05, 0.04],
            "wheel_slip_ratio": [0.05, 0.05, 0.06, 0.05],
            "angular_velocity": {"yaw": 0.42, "pitch": 0.09, "roll": 0.13},
            "angular_acceleration": {"yaw": 2.8, "pitch": 0.7, "roll": 0.8},
            "front_roll_angle": 0.42,
            "rear_roll_angle": 0.61,
            "wheel_lat_force": [2.8, 3.1, 2.9, 3.0],
            "wheel_camber_gain": [0.14, 0.12, 0.16, 0.15],
        }
    )
    overall_accel_text, _ = compose_structured_query_response(state=accel_state, query_kind="overall_situation")
    checks = {
        "main_risk_uses_dynamics_clause": "侧滑角峰值" in main_risk_text,
        "next_focus_uses_dynamics_clause": "把车辆姿态稳住" in next_focus_text,
        "why_not_attack_uses_dynamics_clause": "先把车稳住" in why_not_attack_text,
        "overall_uses_dynamics_clause": "车身姿态还不够干净" in overall_text,
        "overall_uses_yaw_accel_clause": "偏航角加速度约 2.800" in overall_accel_text,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "main_risk_text": main_risk_text,
            "next_focus_text": next_focus_text,
            "why_not_attack_text": why_not_attack_text,
            "overall_text": overall_text,
            "overall_accel_text": overall_accel_text,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_motionex_response_regression())

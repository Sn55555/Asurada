from __future__ import annotations

from regression_support import emit_result

import json

from asurada.config import AppConfig
from asurada.models import ContextProfile, DriverState, RiskProfile, SessionState, StateAssessment, TyreState
from asurada.strategy import StrategyEngine


def run_phase1_motionex_strategy_detail_regression() -> dict[str, object]:
    config = AppConfig()
    engine = StrategyEngine(config.thresholds)

    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=18,
        gap_ahead_s=1.2,
        gap_behind_s=1.1,
        fuel_laps_remaining=12.0,
        ers_pct=68.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=36.0, age_laps=10),
        speed_kph=275.0,
        status_tags=["unstable"],
    )
    state = SessionState(
        session_uid="session-motionex-strategy-detail",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_778_970_000_000,
        raw={
            "wheel_slip_angle": [0.05, 0.07, 0.14, 0.11],
            "wheel_slip_ratio": [0.06, 0.07, 0.12, 0.09],
            "front_aero_height": 31.8,
            "rear_aero_height": 35.1,
            "angular_velocity": {"yaw": 0.91, "pitch": 0.13, "roll": 0.18},
        },
    )
    unstable_candidates = engine._build_candidates(
        state,
        StateAssessment(
            fuel_state="stable",
            tyre_state="stable",
            ers_state="stable",
            race_state="green",
            attack_state="available",
            defend_state="clear",
            dynamics_state="unstable",
        ),
        RiskProfile(
            fuel_risk=10,
            tyre_risk=10,
            ers_risk=10,
            race_control_risk=10,
            dynamics_risk=88,
            attack_opportunity=20,
            defend_risk=20,
        ),
        ContextProfile(
            recent_unstable_ratio=0.42,
            recent_front_overload_ratio=0.15,
            driving_mode="push",
            track_zone="apex_rotation",
            track_segment="mid",
            track_usage="attack",
            tyre_age_factor=7,
            brake_phase_factor=1,
            throttle_phase_factor=2,
            steering_phase_factor=1,
        ),
    )
    unstable_detail = next(item.detail for item in unstable_candidates if item.code == "DYNAMICS_UNSTABLE")

    unstable_accel_state = SessionState(
        session_uid="session-motionex-unstable-accel",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_778_970_050_000,
        raw={
            "wheel_slip_angle": [0.03, 0.04, 0.05, 0.04],
            "wheel_slip_ratio": [0.05, 0.06, 0.07, 0.05],
            "front_aero_height": 31.6,
            "rear_aero_height": 33.8,
            "angular_velocity": {"yaw": 0.41, "pitch": 0.08, "roll": 0.12},
            "angular_acceleration": {"yaw": 2.7, "pitch": 0.4, "roll": 0.6},
            "front_roll_angle": 0.42,
            "rear_roll_angle": 0.88,
        },
    )
    unstable_accel_candidates = engine._build_candidates(
        unstable_accel_state,
        StateAssessment(
            fuel_state="stable",
            tyre_state="stable",
            ers_state="stable",
            race_state="green",
            attack_state="available",
            defend_state="clear",
            dynamics_state="unstable",
        ),
        RiskProfile(
            fuel_risk=10,
            tyre_risk=10,
            ers_risk=10,
            race_control_risk=10,
            dynamics_risk=82,
            attack_opportunity=20,
            defend_risk=20,
        ),
        ContextProfile(
            recent_unstable_ratio=0.36,
            recent_front_overload_ratio=0.14,
            driving_mode="push",
            track_zone="apex_rotation",
            track_segment="mid",
            track_usage="attack",
            tyre_age_factor=7,
            brake_phase_factor=1,
            throttle_phase_factor=2,
            steering_phase_factor=1,
        ),
    )
    unstable_accel_detail = next(item.detail for item in unstable_accel_candidates if item.code == "DYNAMICS_UNSTABLE")

    front_load_state = SessionState(
        session_uid="session-motionex-front-load",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_778_970_100_000,
        raw={
            "wheel_slip_angle": [0.04, 0.05, 0.07, 0.06],
            "wheel_slip_ratio": [0.12, 0.11, 0.08, 0.07],
            "wheel_lat_force": [4.2, 4.4, 3.9, 4.1],
            "front_aero_height": 31.4,
            "rear_aero_height": 34.4,
            "angular_velocity": {"yaw": 0.42, "pitch": 0.09, "roll": 0.14},
        },
    )
    front_load_candidates = engine._build_candidates(
        front_load_state,
        StateAssessment(
            fuel_state="stable",
            tyre_state="stable",
            ers_state="stable",
            race_state="green",
            attack_state="available",
            defend_state="clear",
            dynamics_state="front_overload",
        ),
        RiskProfile(
            fuel_risk=10,
            tyre_risk=10,
            ers_risk=10,
            race_control_risk=10,
            dynamics_risk=80,
            attack_opportunity=20,
            defend_risk=20,
        ),
        ContextProfile(
            recent_unstable_ratio=0.12,
            recent_front_overload_ratio=0.38,
            driving_mode="push",
            track_zone="high_load_management",
            track_segment="entry",
            track_usage="attack",
            tyre_age_factor=7,
            brake_phase_factor=1,
            throttle_phase_factor=2,
            steering_phase_factor=1,
        ),
    )
    front_load_codes = {item.code for item in front_load_candidates}
    front_load_state.raw["tyres_damage_pct"] = [30, 35, 31, 39]
    front_load_state.raw["tyres_wear_pct"] = [30.0, 35.0, 31.0, 34.0]
    front_load_state.player.status_tags = ["front_tyre_overload"]
    new_decision = engine.evaluate(front_load_state).record
    damage = next(item for item in new_decision.actions if item.code == "TYRE_DAMAGE")

    front_load_state.assessment = None
    front_load_state.player.status_tags = ["unstable", "front_tyre_overload"]
    urgent = engine.evaluate(front_load_state)

    checks = {
        "unstable_detail_uses_slip_angle": "侧滑角峰值" in unstable_detail,
        "unstable_detail_uses_yaw_accel": "偏航角加速度约 2.700" in unstable_accel_detail,
        "short_front_load_signal_is_observation_only": (
            "FRONT_LOAD" not in front_load_codes and new_decision.assessment.labels.dynamics_state == "stable"),
        "wheel_damage_uses_f1_wheel_order": damage.title == "轮胎受损。右前轮，百分之三十九。",
        "wheel_damage_does_not_override_instability": (
            urgent.messages[0].code == "DYNAMICS_UNSTABLE"
            and all(item.code != "TYRE_DAMAGE" for item in urgent.messages)),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "unstable_detail": unstable_detail,
            "unstable_accel_detail": unstable_accel_detail,
            "tyre_damage_title": damage.title,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_motionex_strategy_detail_regression())

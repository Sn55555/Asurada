from __future__ import annotations

from regression_support import emit_result

import json

from asurada.models import ContextProfile, DriverState, SessionState, TyreState
from asurada.model_runtime import build_runtime_feature_row


def run_phase1_rival_runtime_feature_regression() -> dict[str, object]:
    tyre = TyreState(compound="Medium", wear_pct=32.0, age_laps=11)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=22,
        gap_ahead_s=0.884,
        gap_behind_s=1.041,
        fuel_laps_remaining=10.4,
        ers_pct=59.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=271.0,
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=22,
        gap_ahead_s=1.104,
        gap_behind_s=0.884,
        gap_confidence="high",
        pit_status="IN_PIT_AREA",
        fuel_laps_remaining=10.0,
        ers_pct=47.0,
        drs_available=False,
        tyre=TyreState(compound="Hard", wear_pct=35.0, age_laps=18),
        engine_damage_pct=12,
        aero_damage_pct=8,
        speed_kph=266.0,
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=22,
        gap_ahead_s=1.041,
        gap_behind_s=1.626,
        gap_confidence="medium",
        pit_status="NONE",
        fuel_laps_remaining=9.9,
        ers_pct=63.0,
        drs_available=True,
        tyre=TyreState(compound="Medium", wear_pct=41.0, age_laps=13),
        engine_damage_pct=38,
        aero_damage_pct=14,
        speed_kph=274.0,
    )
    state = SessionState(
        session_uid="session-rival-runtime",
        track="Suzuka",
        lap_number=22,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_910_000_000,
        raw={
            "session_time_s": 1400.5,
            "throttle": 0.92,
            "brake": 0.0,
            "steer": -0.08,
            "official_gap_ahead_s": 0.884,
            "official_gap_behind_s": 1.041,
            "fuel_in_tank": 16.2,
            "fuel_capacity": 30.0,
            "raw_fuel_laps_remaining": 10.2,
            "derived_fuel_laps_remaining": 10.4,
            "fuel_laps_remaining_source": "derived_status",
            "ers_store_energy": 2500000.0,
            "ers_deploy_mode": "MEDIUM",
            "g_force_lateral": 2.8,
            "g_force_longitudinal": 0.4,
            "g_force_vertical": 0.1,
            "yaw": 0.02,
            "pitch": -0.01,
            "roll": 0.0,
            "wheel_slip_ratio": [0.01, 0.02, 0.03, 0.02],
            "timing_mode": "official_lapdata_adjacent",
            "session_type": "R",
        },
    )
    context = ContextProfile(
        track_zone="S1",
        track_segment="entry",
        track_usage="attack",
        driving_mode="push",
        recent_unstable_ratio=0.12,
        recent_front_overload_ratio=0.08,
        tyre_age_factor=1.1,
        brake_phase_factor=1,
        throttle_phase_factor=2,
        steering_phase_factor=1,
    )
    row = build_runtime_feature_row(state=state, context=context)
    checks = {
        "front_rival_gap_confidence": row.get("front_rival_gap_confidence") == "high",
        "rear_rival_gap_confidence": row.get("rear_rival_gap_confidence") == "medium",
        "front_rival_pit_status": row.get("front_rival_pit_status") == "IN_PIT_AREA",
        "rear_rival_pit_status": row.get("rear_rival_pit_status") == "NONE",
        "front_rival_damage": row.get("front_rival_engine_damage_pct") == 12 and row.get("front_rival_aero_damage_pct") == 8,
        "rear_rival_damage": row.get("rear_rival_engine_damage_pct") == 38 and row.get("rear_rival_aero_damage_pct") == 14,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "front_rival_gap_confidence": row.get("front_rival_gap_confidence"),
            "rear_rival_gap_confidence": row.get("rear_rival_gap_confidence"),
            "front_rival_pit_status": row.get("front_rival_pit_status"),
            "rear_rival_pit_status": row.get("rear_rival_pit_status"),
            "front_rival_engine_damage_pct": row.get("front_rival_engine_damage_pct"),
            "rear_rival_engine_damage_pct": row.get("rear_rival_engine_damage_pct"),
            "front_rival_aero_damage_pct": row.get("front_rival_aero_damage_pct"),
            "rear_rival_aero_damage_pct": row.get("rear_rival_aero_damage_pct"),
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_runtime_feature_regression())

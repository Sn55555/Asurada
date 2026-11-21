from __future__ import annotations

from regression_support import emit_result

import json

from asurada.config import AppConfig
from asurada.models import ContextProfile, DriverState, RiskProfile, SessionState, StateAssessment, TyreState
from asurada.strategy import StrategyEngine


def run_phase1_rival_strategy_detail_regression() -> dict[str, object]:
    config = AppConfig()
    engine = StrategyEngine(config.thresholds)

    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=18,
        gap_ahead_s=0.8,
        gap_behind_s=0.9,
        fuel_laps_remaining=12.0,
        ers_pct=70.0,
        drs_available=True,
        tyre=TyreState(compound="Medium", wear_pct=28.0, age_laps=9),
        speed_kph=279.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=18,
        gap_ahead_s=1.6,
        gap_behind_s=0.8,
        gap_confidence_behind="medium",
        fuel_laps_remaining=12.0,
        ers_pct=50.0,
        drs_available=False,
        pit_status="IN_PIT_AREA",
        tyre=TyreState(compound="Hard", wear_pct=34.0, age_laps=17),
        speed_kph=272.0,
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=18,
        gap_ahead_s=0.9,
        gap_behind_s=1.7,
        gap_confidence_ahead="medium",
        fuel_laps_remaining=11.5,
        ers_pct=61.0,
        drs_available=True,
        pit_status="NONE",
        tyre=TyreState(compound="Medium", wear_pct=39.0, age_laps=12),
        engine_damage_pct=42,
        speed_kph=280.0,
    )
    state = SessionState(
        session_uid="session-rival-strategy-detail",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_920_000_000,
        raw={
            "lap_distance_m": 3020.0,
            "throttle": 0.88,
            "brake": 0.02,
            "steer": 0.04,
            "fuel_laps_remaining_source": "derived_from_sample_consumption",
            "fuel_in_tank": 18.0,
            "fuel_capacity": 30.0,
            "session_type": "R",
        },
    )
    candidates = engine._build_candidates(
        state,
        StateAssessment(
            fuel_state="stable",
            tyre_state="stable",
            ers_state="stable",
            race_state="green",
            attack_state="available",
            defend_state="urgent",
            dynamics_state="stable",
        ),
        RiskProfile(
            fuel_risk=10,
            tyre_risk=10,
            ers_risk=10,
            race_control_risk=10,
            dynamics_risk=10,
            attack_opportunity=80,
            defend_risk=86,
        ),
        ContextProfile(
            recent_unstable_ratio=0.0,
            recent_front_overload_ratio=0.0,
            driving_mode="push",
            track_zone="S1",
            track_segment="entry",
            track_usage="attack",
            tyre_age_factor=8,
            brake_phase_factor=1,
            throttle_phase_factor=2,
            steering_phase_factor=1,
        ),
    )
    messages = {item.code: item.detail for item in candidates}
    attack_detail = messages.get("ATTACK_WINDOW", "")
    defend_detail = messages.get("DEFEND_WINDOW", "")
    checks = {
        "attack_uses_front_pit_context": "Norris" in attack_detail and "IN_PIT_AREA" in attack_detail,
        "defend_uses_rear_drs_context": "Russell" in defend_detail and "DRS" in defend_detail,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "attack_detail": attack_detail,
            "defend_detail": defend_detail,
            "codes": [item.code for item in candidates],
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_strategy_detail_regression())

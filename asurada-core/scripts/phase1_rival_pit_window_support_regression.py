from __future__ import annotations

from regression_support import emit_result

import json

from asurada.long_horizon import PitWindowSupport
from asurada.models import ContextProfile, DriverState, SessionState, TyreState
from asurada.session_router import SessionRoute


def _build_state(*, front_pit_status: str = "NONE", rear_drs: bool = False, rear_engine_damage_pct: int = 0) -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=22,
        gap_ahead_s=1.4,
        gap_behind_s=1.1,
        fuel_laps_remaining=15.0,
        ers_pct=66.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=61.0, age_laps=14),
        speed_kph=271.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=22,
        gap_ahead_s=1.9,
        gap_behind_s=1.4,
        fuel_laps_remaining=14.0,
        ers_pct=54.0,
        drs_available=False,
        gap_confidence_behind="high",
        pit_status=front_pit_status,
        tyre=TyreState(compound="Hard", wear_pct=40.0, age_laps=18),
        speed_kph=269.0,
        status_tags=[],
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=22,
        gap_ahead_s=1.1,
        gap_behind_s=1.8,
        fuel_laps_remaining=13.5,
        ers_pct=61.0,
        drs_available=rear_drs,
        gap_confidence_ahead="high",
        pit_status="NONE",
        tyre=TyreState(compound="Medium", wear_pct=44.0, age_laps=12),
        engine_damage_pct=rear_engine_damage_pct,
        speed_kph=273.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="session-rival-pit-window-support",
        track="Suzuka",
        lap_number=22,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_920_100_000,
        raw={
            "session_type": "FeatureRaceLike(16)",
            "grid_position": 6,
            "pit_status": "NONE",
            "pit_lane_timer_active": False,
            "official_gap_ahead_s": 1.4,
            "official_gap_behind_s": 1.1,
            "official_gap_confidence_ahead": "high",
            "official_gap_confidence_behind": "high",
            "num_pit_stops": 0,
            "session_history": {},
        },
    )


def run_phase1_rival_pit_window_support_regression() -> dict[str, object]:
    support = PitWindowSupport()
    route = SessionRoute(
        session_mode="race",
        allowed_action_codes={"NONE", "BOX_WINDOW", "TYRE_MANAGE"},
        allow_timing_actions=True,
        allow_race_resource_actions=True,
        route_reason="feature_race_fixture",
    )
    context = ContextProfile(
        recent_unstable_ratio=0.0,
        recent_front_overload_ratio=0.0,
        driving_mode="push",
        track_zone="S2",
        track_segment="mid",
        track_usage="attack",
        tyre_age_factor=12,
        brake_phase_factor=1,
        throttle_phase_factor=2,
        steering_phase_factor=1,
    )
    base = support.evaluate(
        session_route=route,
        state=_build_state(),
        context=context,
        resource_models={"fuel_risk": {"score": 20.0}},
        rival_pressure_models={"rear_pressure": {"score": 60.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.24}, "future_grip_drop_score": {"score": 2.2}},
    )
    front_pit = support.evaluate(
        session_route=route,
        state=_build_state(front_pit_status="IN_PIT_AREA"),
        context=context,
        resource_models={"fuel_risk": {"score": 20.0}},
        rival_pressure_models={"rear_pressure": {"score": 60.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.24}, "future_grip_drop_score": {"score": 2.2}},
    )
    rear_drs = support.evaluate(
        session_route=route,
        state=_build_state(rear_drs=True),
        context=context,
        resource_models={"fuel_risk": {"score": 20.0}},
        rival_pressure_models={"rear_pressure": {"score": 60.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.24}, "future_grip_drop_score": {"score": 2.2}},
    )
    rear_damage = support.evaluate(
        session_route=route,
        state=_build_state(rear_engine_damage_pct=45),
        context=context,
        resource_models={"fuel_risk": {"score": 20.0}},
        rival_pressure_models={"rear_pressure": {"score": 60.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.24}, "future_grip_drop_score": {"score": 2.2}},
    )

    checks = {
        "front_pit_reduces_undercut_defence": front_pit.undercut_defence_score < base.undercut_defence_score,
        "front_pit_rationale_mentions_window_shift": any("跟进" in item and "Norris" in item for item in front_pit.rationale),
        "rear_drs_increases_rejoin_penalty": rear_drs.rejoin_traffic_penalty > base.rejoin_traffic_penalty,
        "rear_drs_increases_window_probability": rear_drs.pit_window_open_prob > base.pit_window_open_prob,
        "rear_drs_rationale_mentions_direct_pressure": any("DRS" in item and "Russell" in item for item in rear_drs.rationale),
        "rear_damage_reduces_rejoin_penalty": rear_damage.rejoin_traffic_penalty < base.rejoin_traffic_penalty,
        "rear_damage_rationale_mentions_relief": any("自然回落" in item and "Russell" in item for item in rear_damage.rationale),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "base": base.to_dict(),
            "front_pit": front_pit.to_dict(),
            "rear_drs": rear_drs.to_dict(),
            "rear_damage": rear_damage.to_dict(),
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_pit_window_support_regression())

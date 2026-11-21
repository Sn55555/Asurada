from __future__ import annotations

from regression_support import emit_result

import json

from asurada.long_horizon import LongHorizonStrategyBaseline, PitWindowSupport
from asurada.models import ContextProfile, DriverState, SessionState, TyreState
from asurada.session_router import SessionRoute


def _build_state(
    *,
    forecast_samples: list[dict[str, object]] | None = None,
    history_laps: int = 20,
    history_stints: int = 1,
) -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=20,
        gap_ahead_s=1.8,
        gap_behind_s=1.4,
        fuel_laps_remaining=16.0,
        ers_pct=62.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=57.0, age_laps=13),
        speed_kph=268.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=20,
        gap_ahead_s=2.0,
        gap_behind_s=1.8,
        fuel_laps_remaining=15.0,
        ers_pct=55.0,
        drs_available=False,
        gap_confidence_behind="high",
        tyre=TyreState(compound="Hard", wear_pct=36.0, age_laps=18),
        speed_kph=267.0,
        status_tags=[],
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=20,
        gap_ahead_s=1.4,
        gap_behind_s=1.7,
        fuel_laps_remaining=14.0,
        ers_pct=60.0,
        drs_available=False,
        gap_confidence_ahead="high",
        tyre=TyreState(compound="Medium", wear_pct=40.0, age_laps=12),
        speed_kph=270.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="session-long-horizon-forecast-history",
        track="Suzuka",
        lap_number=20,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_930_000_000,
        raw={
            "session_type": "FeatureRaceLike(16)",
            "grid_position": 6,
            "pit_status": "NONE",
            "pit_lane_timer_active": False,
            "official_gap_ahead_s": 1.8,
            "official_gap_behind_s": 1.4,
            "official_gap_confidence_ahead": "high",
            "official_gap_confidence_behind": "high",
            "num_pit_stops": 0,
            "weather_forecast_samples": forecast_samples or [],
            "session_history_summary": {
                "car_index": 0,
                "num_laps": history_laps,
                "num_tyre_stints": history_stints,
                "best_lap_time_lap_num": 12,
                "best_sector1_lap_num": 10,
                "best_sector2_lap_num": 12,
                "best_sector3_lap_num": 12,
            },
            "session_history": {
                "tyre_stints_history_data": [
                    {"end_lap": 11, "tyre_visual_compound": 18},
                ]
                if history_stints > 0
                else []
            },
        },
    )


def run_phase1_long_horizon_forecast_history_regression() -> dict[str, object]:
    support_layer = PitWindowSupport()
    planner = LongHorizonStrategyBaseline()
    context = ContextProfile(
        recent_unstable_ratio=0.0,
        recent_front_overload_ratio=0.0,
        driving_mode="push",
        track_zone="S2",
        track_segment="mid",
        track_usage="attack",
        tyre_age_factor=10,
        brake_phase_factor=1,
        throttle_phase_factor=2,
        steering_phase_factor=1,
    )
    route = SessionRoute(
        session_mode="race",
        allowed_action_codes={"NONE", "BOX_WINDOW", "TYRE_MANAGE"},
        allow_timing_actions=True,
        allow_race_resource_actions=True,
        route_reason="feature_race",
    )

    base_state = _build_state()
    rain_state = _build_state(
        forecast_samples=[
            {
                "sample_index": 0,
                "session_type": 16,
                "time_offset_minutes": 5,
                "weather": 3,
                "track_temperature_c": 28,
                "track_temperature_change": -1,
                "air_temperature_c": 21,
                "air_temperature_change": -1,
                "rain_percentage": 58,
            }
        ]
    )
    sparse_history_state = _build_state(history_laps=3, history_stints=0)

    base_support = support_layer.evaluate(
        session_route=route,
        state=base_state,
        context=context,
        resource_models={"fuel_risk": {"score": 18.0}},
        rival_pressure_models={"rear_pressure": {"score": 48.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.18}, "future_grip_drop_score": {"score": 1.8}},
    )
    rain_support = support_layer.evaluate(
        session_route=route,
        state=rain_state,
        context=context,
        resource_models={"fuel_risk": {"score": 18.0}},
        rival_pressure_models={"rear_pressure": {"score": 48.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.18}, "future_grip_drop_score": {"score": 1.8}},
    )
    rich_plan = planner.plan(
        state=base_state,
        session_route=route,
        support=base_support,
        resource_models={"fuel_risk": {"score": 18.0}},
        rival_pressure_models={"rear_pressure": {"score": 48.0}},
    )
    sparse_support = support_layer.evaluate(
        session_route=route,
        state=sparse_history_state,
        context=context,
        resource_models={"fuel_risk": {"score": 18.0}},
        rival_pressure_models={"rear_pressure": {"score": 48.0}},
        tyre_degradation_trend_models={"future_tyre_wear_delta": {"score": 0.18}, "future_grip_drop_score": {"score": 1.8}},
    )
    sparse_plan = planner.plan(
        state=sparse_history_state,
        session_route=route,
        support=sparse_support,
        resource_models={"fuel_risk": {"score": 18.0}},
        rival_pressure_models={"rear_pressure": {"score": 48.0}},
    )

    checks = {
        "rain_forecast_increases_pit_window_prob": rain_support.pit_window_open_prob > base_support.pit_window_open_prob,
        "rain_forecast_rationale_mentions_rain_window": any("降雨窗口" in item for item in rain_support.rationale),
        "rich_history_increases_strategy_confidence": rich_plan.strategy_confidence > sparse_plan.strategy_confidence,
        "sparse_history_rationale_mentions_low_coverage": any("覆盖偏薄" in item for item in sparse_plan.rationale),
        "rich_history_rationale_mentions_stints": any("tyre stint" in item for item in rich_plan.rationale),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "base_support": base_support.to_dict(),
            "rain_support": rain_support.to_dict(),
            "rich_plan": rich_plan.to_dict(),
            "sparse_plan": sparse_plan.to_dict(),
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_long_horizon_forecast_history_regression())

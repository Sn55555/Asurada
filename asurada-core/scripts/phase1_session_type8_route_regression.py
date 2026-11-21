from __future__ import annotations

from regression_support import emit_result

import json

from asurada.config import AppConfig
from asurada.models import DriverState, SessionState, TyreState
from asurada.session_router import SessionModeRouter
from asurada.strategy import StrategyEngine


def _make_state() -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=1,
        lap=3,
        gap_ahead_s=None,
        gap_behind_s=None,
        fuel_laps_remaining=8.0,
        ers_pct=52.0,
        drs_available=False,
        tyre=TyreState(compound="Soft", wear_pct=28.0, age_laps=3),
        speed_kph=0.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="session-type8-route",
        track="Shanghai",
        lap_number=3,
        total_laps=3,
        weather="Clear",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_780_000_000_000,
        raw={
            "session_type": "ShortResultLike(8)",
            "timing_mode": "result_like",
            "timing_support_level": "disabled",
            "official_gap_ahead_s": None,
            "official_gap_behind_s": None,
            "estimated_gap_ahead_s": 0.844,
            "estimated_gap_behind_s": 1.102,
            "fuel_in_tank": 9.0,
            "fuel_capacity": 110.0,
            "derived_fuel_laps_remaining": 8.0,
            "raw_fuel_laps_remaining": 0.0,
            "fuel_laps_remaining_source": "derived_from_sample_consumption",
            "pit_status": "NONE",
            "throttle": 0.0,
            "brake": 0.0,
            "steer": 0.0,
            "g_force_lateral": 0.0,
            "g_force_longitudinal": 0.0,
        },
    )


def run_phase1_session_type8_route_regression() -> dict[str, object]:
    state = _make_state()
    router = SessionModeRouter()
    route = router.resolve(state)
    decision = StrategyEngine(AppConfig().thresholds).evaluate(state, [state])
    session_route_debug = decision.debug.get("session_route") or {}
    pit_window_support = decision.debug.get("pit_window_support") or {}
    long_horizon_strategy = decision.debug.get("long_horizon_strategy") or {}
    checks = {
        "router_timing_mode_result_like": route.session_mode.endswith(":result_like"),
        "router_disables_timing_actions": route.allow_timing_actions is False,
        "router_disables_race_resource_actions": route.allow_race_resource_actions is False,
        "router_reason_result_like": route.route_reason == "result_like_non_actionable",
        "strategy_debug_route_matches": session_route_debug.get("route_reason") == "result_like_non_actionable",
        "pit_window_support_disabled": pit_window_support.get("enabled") is False,
        "long_horizon_disabled": long_horizon_strategy.get("enabled") is False,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "route": {
                "session_mode": route.session_mode,
                "allow_timing_actions": route.allow_timing_actions,
                "allow_race_resource_actions": route.allow_race_resource_actions,
                "route_reason": route.route_reason,
                "allowed_action_codes": sorted(route.allowed_action_codes),
            },
            "session_route_debug": session_route_debug,
            "pit_window_support": pit_window_support,
            "long_horizon_strategy": long_horizon_strategy,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_session_type8_route_regression())

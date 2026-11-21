from __future__ import annotations

from regression_support import emit_result

import json

from asurada.models import DriverState, SessionState, TyreState
from asurada.response_composer import compose_structured_query_response


def _build_state() -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=6,
        lap=18,
        gap_ahead_s=1.3,
        gap_behind_s=0.9,
        fuel_laps_remaining=12.0,
        ers_pct=58.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=42.0, age_laps=10),
        speed_kph=276.0,
        status_tags=[],
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=5,
        lap=18,
        gap_ahead_s=1.9,
        gap_behind_s=1.3,
        fuel_laps_remaining=12.0,
        ers_pct=62.0,
        drs_available=False,
        tyre=TyreState(compound="Hard", wear_pct=34.0, age_laps=16),
        speed_kph=274.0,
        status_tags=[],
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=7,
        lap=18,
        gap_ahead_s=0.9,
        gap_behind_s=1.8,
        fuel_laps_remaining=11.0,
        ers_pct=65.0,
        drs_available=False,
        tyre=TyreState(compound="Medium", wear_pct=38.0, age_laps=10),
        speed_kph=277.0,
        status_tags=[],
    )
    return SessionState(
        session_uid="session-position-trend-response",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_940_000_000,
        raw={
            "lap_positions": {
                "player_lap_positions": [
                    {"lap_index": 15, "lap_number": 16, "position": 4},
                    {"lap_index": 16, "lap_number": 17, "position": 5},
                    {"lap_index": 17, "lap_number": 18, "position": 6},
                ]
            },
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
            "pit_status": "NONE",
        },
    )


def run_phase1_position_trend_response_regression() -> dict[str, object]:
    state = _build_state()
    next_focus_text, _ = compose_structured_query_response(state=state, query_kind="next_lap_focus")
    why_defend_text, _ = compose_structured_query_response(state=state, query_kind="why_defend")
    why_not_attack_text, _ = compose_structured_query_response(state=state, query_kind="why_not_attack")
    overall_text, _ = compose_structured_query_response(state=state, query_kind="overall_situation")
    checks = {
        "next_focus_uses_position_drop": "从 P4 掉到 P6" in next_focus_text,
        "why_defend_uses_position_drop": "从 P4 回落到 P6" in why_defend_text,
        "why_not_attack_uses_position_drop": "从 P4 掉到 P6" in why_not_attack_text,
        "overall_situation_mentions_position_trend": "从第 16 圈到第 18 圈回落了 2 位" in overall_text,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "next_focus_text": next_focus_text,
            "why_defend_text": why_defend_text,
            "why_not_attack_text": why_not_attack_text,
            "overall_text": overall_text,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_position_trend_response_regression())

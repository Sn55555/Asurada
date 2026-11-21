from __future__ import annotations

from regression_support import emit_result

import json

from asurada.models import DriverState, SessionState, TyreState
from asurada.response_composer import compose_structured_query_response


def _build_state(
    *,
    rear_drs: bool,
    rear_engine_damage_pct: int | None,
    rear_pit_status: str,
    front_pit_status: str,
    gap_behind_s: float,
) -> SessionState:
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=18,
        gap_ahead_s=0.92,
        gap_behind_s=gap_behind_s,
        fuel_laps_remaining=11.8,
        ers_pct=62.0,
        drs_available=True,
        tyre=TyreState(compound="Medium", wear_pct=29.0, age_laps=9),
        speed_kph=278.0,
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        position=4,
        lap=18,
        gap_ahead_s=1.52,
        gap_behind_s=0.92,
        gap_confidence_behind="medium",
        fuel_laps_remaining=11.2,
        ers_pct=51.0,
        drs_available=False,
        pit_status=front_pit_status,
        tyre=TyreState(compound="Hard", wear_pct=37.0, age_laps=16),
        speed_kph=273.0,
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        position=6,
        lap=18,
        gap_ahead_s=gap_behind_s,
        gap_behind_s=1.58,
        gap_confidence_ahead="medium",
        fuel_laps_remaining=11.0,
        ers_pct=63.0,
        drs_available=rear_drs,
        pit_status=rear_pit_status,
        tyre=TyreState(compound="Medium", wear_pct=39.0, age_laps=12),
        engine_damage_pct=rear_engine_damage_pct,
        speed_kph=279.0,
    )
    return SessionState(
        session_uid="session-rival-risk-summary",
        track="Suzuka",
        lap_number=18,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_930_000_000,
        raw={
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
        },
    )


def run_phase1_rival_risk_summary_regression() -> dict[str, object]:
    drs_pressure_state = _build_state(
        rear_drs=True,
        rear_engine_damage_pct=8,
        rear_pit_status="NONE",
        front_pit_status="NONE",
        gap_behind_s=0.96,
    )
    self_relief_state = _build_state(
        rear_drs=False,
        rear_engine_damage_pct=42,
        rear_pit_status="NONE",
        front_pit_status="IN_PIT_AREA",
        gap_behind_s=1.36,
    )

    main_risk_drs, _ = compose_structured_query_response(state=drs_pressure_state, query_kind="main_risk_summary")
    next_focus_drs, _ = compose_structured_query_response(state=drs_pressure_state, query_kind="next_lap_focus")
    relief_text, _ = compose_structured_query_response(state=self_relief_state, query_kind="rear_pressure_relief_outlook")
    tradeoff_text, _ = compose_structured_query_response(state=self_relief_state, query_kind="attack_defend_tradeoff")
    checks = {
        "main_risk_uses_rear_drs": "Russell" in main_risk_drs and "DRS" in main_risk_drs,
        "next_focus_uses_rear_drs": "DRS" in next_focus_drs and "Russell" in next_focus_drs,
        "pressure_relief_uses_rear_damage": "发动机损伤已经到 42%" in relief_text,
        "tradeoff_uses_front_pit_context": "Norris" in tradeoff_text
        and ("IN_PIT_AREA" in tradeoff_text or "窗口自然变化" in tradeoff_text),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "main_risk_drs": main_risk_drs,
            "next_focus_drs": next_focus_drs,
            "pressure_relief_text": relief_text,
            "tradeoff_text": tradeoff_text,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_risk_summary_regression())

from __future__ import annotations

from regression_support import emit_result

import json

from asurada.models import DriverState, SessionState, TyreState
from asurada.response_composer import compose_structured_query_response


def _build_state() -> SessionState:
    player_tyre = TyreState(compound="Medium", wear_pct=31.0, age_laps=10)
    front_tyre = TyreState(compound="Hard", wear_pct=44.0, age_laps=18)
    rear_tyre = TyreState(compound="Medium", wear_pct=39.0, age_laps=12)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        team_id=0,
        race_number=16,
        position=5,
        lap=20,
        gap_ahead_s=1.084,
        gap_behind_s=0.912,
        gap_source="official_lapdata_adjacent",
        gap_confidence="high",
        gap_source_ahead="official_lapdata_adjacent",
        gap_source_behind="official_lapdata_adjacent",
        gap_confidence_ahead="high",
        gap_confidence_behind="high",
        fuel_laps_remaining=12.4,
        ers_pct=57.0,
        drs_available=False,
        pit_status="NONE",
        tyre=player_tyre,
        speed_kph=274.0,
    )
    front_rival = DriverState(
        car_index=1,
        name="Norris",
        team_id=1,
        race_number=4,
        position=4,
        lap=20,
        gap_ahead_s=2.201,
        gap_behind_s=1.084,
        gap_source="official_lapdata_adjacent",
        gap_confidence="medium",
        gap_source_ahead="official_lapdata_adjacent",
        gap_source_behind="official_lapdata_adjacent",
        gap_confidence_ahead="high",
        gap_confidence_behind="medium",
        fuel_laps_remaining=12.0,
        ers_pct=49.0,
        drs_available=False,
        pit_status="IN_PIT_AREA",
        tyre=front_tyre,
        tyre_damage_pct=21.5,
        engine_damage_pct=8,
        aero_damage_pct=6,
        speed_kph=269.0,
    )
    rear_rival = DriverState(
        car_index=2,
        name="Russell",
        team_id=3,
        race_number=63,
        position=6,
        lap=20,
        gap_ahead_s=0.912,
        gap_behind_s=1.441,
        gap_source="official_lapdata_adjacent",
        gap_confidence="medium",
        gap_source_ahead="official_lapdata_adjacent",
        gap_source_behind="estimated_total_distance_same_lap",
        gap_confidence_ahead="high",
        gap_confidence_behind="medium",
        fuel_laps_remaining=11.8,
        ers_pct=61.0,
        drs_available=True,
        pit_status="NONE",
        tyre=rear_tyre,
        tyre_damage_pct=13.2,
        engine_damage_pct=41,
        aero_damage_pct=9,
        speed_kph=276.0,
    )
    return SessionState(
        session_uid="session-rival-structured",
        track="Suzuka",
        lap_number=20,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rear_rival, front_rival],
        source_timestamp_ms=1_778_900_000_000,
        raw={},
    )


def run_phase1_rival_structured_response_regression() -> dict[str, object]:
    state = _build_state()
    front_gap_text, front_gap_code = compose_structured_query_response(state=state, query_kind="front_gap")
    rear_gap_text, rear_gap_code = compose_structured_query_response(state=state, query_kind="rear_gap")
    rear_drs_text, rear_drs_code = compose_structured_query_response(state=state, query_kind="rear_rival_drs_status")
    overall_text, overall_code = compose_structured_query_response(state=state, query_kind="overall_situation")
    checks = {
        "front_gap_uses_front_rival": front_gap_code == "QUERY_FRONT_GAP"
        and "Norris" in front_gap_text
        and "Russell" not in front_gap_text,
        "front_gap_includes_front_pit_context": "进站流程" in front_gap_text or "IN_PIT_AREA" in front_gap_text,
        "rear_gap_uses_rear_rival": rear_gap_code == "QUERY_REAR_GAP"
        and "Russell" in rear_gap_text
        and "Norris" not in rear_gap_text,
        "rear_gap_includes_damage_or_gap_hint": "发动机损伤约 41%" in rear_gap_text or "中可信度估算" in rear_gap_text,
        "rear_drs_uses_rear_rival": rear_drs_code == "QUERY_REAR_RIVAL_DRS_STATUS" and "Russell" in rear_drs_text,
        "overall_includes_front_and_rear_context": overall_code == "QUERY_OVERALL_SITUATION"
        and "前车 Norris" in overall_text
        and "后车 Russell" in overall_text,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "front_gap_text": front_gap_text,
            "rear_gap_text": rear_gap_text,
            "rear_drs_text": rear_drs_text,
            "overall_text": overall_text,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase1_rival_structured_response_regression())

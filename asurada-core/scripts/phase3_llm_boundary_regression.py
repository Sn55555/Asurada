from __future__ import annotations

import json
from typing import Any

from asurada.conversation_context import ConversationContext
from asurada.llm_response_schema import coerce_llm_response, validate_llm_response
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.state_summary_for_llm import build_state_summary_for_llm


def _make_state() -> SessionState:
    tyre = TyreState(
        compound="Medium",
        wear_pct=31.0,
        age_laps=9,
        surface_temperature_c=[98, 100, 97, 99],
        inner_temperature_c=[90, 92, 91, 90],
    )
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=18,
        gap_ahead_s=0.882,
        gap_behind_s=0.744,
        fuel_laps_remaining=9.4,
        ers_pct=57.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=286.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=5,
        lap=18,
        gap_ahead_s=0.744,
        gap_behind_s=None,
        fuel_laps_remaining=9.0,
        ers_pct=48.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=284.0,
    )
    return SessionState(
        session_uid="session-llm-summary",
        track="Austria",
        lap_number=18,
        total_laps=36,
        weather="Overcast",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_500_000_000,
        raw={
            "pit_status": "NONE",
            "num_pit_stops": 1,
            "pit_lane_timer_active": False,
            "pit_stop_timer_ms": 0,
            "total_warnings": 1,
            "corner_cutting_warnings": 0,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
            "wing_damage_pct": {"front_left": 6, "front_right": 8, "rear": 0},
            "floor_damage_pct": 4,
            "diffuser_damage_pct": 2,
            "sidepod_damage_pct": 0,
            "gearbox_damage_pct": 3,
            "engine_damage_pct": 7,
            "engine_blown": False,
            "engine_seized": False,
        },
    )


def run_phase3_llm_boundary_regression() -> dict[str, Any]:
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已经贴近 DRS 线。",
    )
    context = ConversationContext()
    context.observe_strategy_message(primary_message, state=state)
    context.observe_user_query(
        request_id="req:test:1",
        transcript_text="整体形势怎么样",
        query_kind="overall_situation",
        timestamp_ms=state.source_timestamp_ms,
        metadata={"reason": "semantic_normalized"},
    )
    context.observe_response(
        request_id="req:test:1",
        query_kind="overall_situation",
        action_code="QUERY_OVERALL_SITUATION",
        speak_text="当前整体先以防守为主。",
        timestamp_ms=state.source_timestamp_ms + 10,
        metadata={"event_type": "start"},
    )

    summary = build_state_summary_for_llm(
        state=state,
        primary_message=primary_message,
        conversation_context=context,
        capability_snapshot={
            "llm_allowed_domains": ["overall_situation", "why_not_attack"],
            "llm_disallowed_domains": ["fuel_status", "rear_gap", "stop"],
        },
    )
    valid_payload = {
        "status": "answerable",
        "answer_text": "当前整体先以防守为主，因为后车已经贴近 DRS 线。",
        "confidence": 0.83,
        "reason_fields": ["primary_message", "gap_behind_s"],
        "requires_confirmation": False,
        "metadata": {"lane": "explainer"},
    }
    invalid_payload = {
        "status": "answerable",
        "answer_text": "bad",
        "confidence": 3.2,
    }

    valid_check = validate_llm_response(valid_payload)
    invalid_check = validate_llm_response(invalid_payload)
    coerced = coerce_llm_response(valid_payload)

    checks = {
        "summary_contains_strategy": summary.strategy_snapshot.get("primary_message", {}).get("code") == "DEFEND_WINDOW",
        "summary_contains_state": summary.state_snapshot.get("track") == "Austria"
        and summary.state_snapshot.get("tyre", {}).get("wear_pct") == 31.0,
        "summary_contains_conversation": (summary.conversation_snapshot.get("last_user_query") or {}).get("query_kind") == "overall_situation",
        "valid_payload_passes": valid_check == (True, "valid"),
        "invalid_payload_rejected": invalid_check == (False, "confidence_out_of_range"),
        "coerce_builds_dataclass": coerced.status == "answerable" and coerced.confidence == 0.83,
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "summary": summary.to_dict(),
            "valid_check": {"ok": valid_check[0], "reason": valid_check[1]},
            "invalid_check": {"ok": invalid_check[0], "reason": invalid_check[1]},
            "coerced": coerced.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_llm_boundary_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

import json
import time
from typing import Any

from asurada.conversation_context import ConversationContext
from asurada.llm_explainer import (
    LlmExplainer,
    NullLlmExplainerBackend,
    build_llm_explainer_request,
)
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.transcript_router import TranscriptRouteDecision


class SuccessBackend:
    name = "success_backend"

    def explain(self, request):  # type: ignore[no-untyped-def]
        return {
            "status": "answerable",
            "answer_text": "当前整体先以防守为主，因为后车已经贴近 DRS 线。",
            "confidence": 0.87,
            "reason_fields": ["primary_message", "gap_behind_s"],
            "requires_confirmation": False,
            "metadata": {"lane": "explainer"},
        }


class TimeoutBackend:
    name = "timeout_backend"

    def explain(self, request):  # type: ignore[no-untyped-def]
        time.sleep(0.08)
        return {
            "status": "answerable",
            "answer_text": "late",
            "confidence": 0.9,
            "reason_fields": [],
            "requires_confirmation": False,
            "metadata": {},
        }


class ErrorBackend:
    name = "error_backend"

    def explain(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("backend exploded")


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=26.0, age_laps=7)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=14,
        gap_ahead_s=1.044,
        gap_behind_s=0.812,
        fuel_laps_remaining=10.2,
        ers_pct=58.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=278.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=6,
        lap=14,
        gap_ahead_s=0.812,
        gap_behind_s=None,
        fuel_laps_remaining=9.8,
        ers_pct=47.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=276.0,
    )
    return SessionState(
        session_uid="session-llm-explainer",
        track="Austria",
        lap_number=14,
        total_laps=36,
        weather="Overcast",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_600_000_000,
        raw={"session_time_s": 1220.4},
    )


def run_phase3_llm_explainer_regression() -> dict[str, Any]:
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
        request_id="req:test:explainer",
        transcript_text="整体形势怎么样",
        query_kind="overall_situation",
        timestamp_ms=state.source_timestamp_ms,
        metadata={"reason": "semantic_normalized"},
    )

    route_decision = TranscriptRouteDecision(
        status="routed",
        lane="explainer",
        query_kind="overall_situation",
        llm_sidecar_eligible=True,
        should_call_core=True,
        should_call_llm_sidecar=False,
        reason="explainer_query",
        metadata={"capability_check": {"allowed": True}},
    )
    request = build_llm_explainer_request(
        interaction_session_id="runtime:test",
        turn_id="turn:test",
        request_id="req:test:explainer",
        normalized_query_text="整体形势怎么样",
        route_decision=route_decision,
        state=state,
        primary_message=primary_message,
        conversation_context=context,
        timeout_ms=40,
    )

    success = LlmExplainer(backend=SuccessBackend()).run(request=request)
    timeout = LlmExplainer(backend=TimeoutBackend()).run(request=request)
    error = LlmExplainer(backend=ErrorBackend()).run(request=request)
    disabled = LlmExplainer(backend=NullLlmExplainerBackend()).run(request=request)

    checks = {
        "request_built": request.query_kind == "overall_situation"
        and request.state_summary.get("strategy_snapshot", {}).get("primary_message", {}).get("code") == "DEFEND_WINDOW"
        and request.metadata.get("persona_id") == "asurada_default",
        "success_completed": success.status == "completed"
        and (success.response or {}).get("status") == "answerable",
        "timeout_falls_back": timeout.status == "fallback" and timeout.fallback_reason == "llm_timeout",
        "error_falls_back": error.status == "fallback" and error.fallback_reason == "llm_error",
        "null_backend_is_supported": disabled.status == "completed"
        and (disabled.response or {}).get("status") == "unsupported",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "request": request.to_dict(),
            "success": success.to_dict(),
            "timeout": timeout.to_dict(),
            "error": error.to_dict(),
            "disabled": disabled.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_llm_explainer_regression(), ensure_ascii=False, indent=2))

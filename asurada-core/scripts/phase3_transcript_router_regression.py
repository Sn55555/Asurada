from __future__ import annotations

import json
import time
from typing import Any

from asurada.asr_fast import FastIntentResult
from asurada.models import DriverState, SessionState, TyreState
from asurada.semantic_normalizer import SemanticIntentResult
from asurada.transcript_router import TranscriptRouter


def _semantic(query_kind: str | None, *, text: str, status: str = "matched", reason: str = "semantic_normalized") -> SemanticIntentResult:
    return SemanticIntentResult(
        status=status,
        query_kind=query_kind,
        normalized_query_text=text,
        response_style="structured",
        confidence=0.88,
        reason=reason,
        metadata={},
    )


def _fast(text: str, *, query_kind: str | None = None, status: str = "matched") -> FastIntentResult:
    return FastIntentResult(
        lane="fast_intent",
        status=status,
        transcript_text=text,
        normalized_text=text,
        query_kind=query_kind,
        confidence=0.88,
        matched_phrase=text,
        metadata={},
    )


def _state(*, source_timestamp_ms: int, track: str = "Austria", lap_number: int = 12, total_laps: int = 36) -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=24.0, age_laps=7)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=lap_number,
        gap_ahead_s=1.2,
        gap_behind_s=0.8,
        fuel_laps_remaining=10.0,
        ers_pct=60.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=270.0,
    )
    return SessionState(
        session_uid="session-router-regression",
        track=track,
        lap_number=lap_number,
        total_laps=total_laps,
        weather="Clear",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=source_timestamp_ms,
        raw={"source_timestamp_ms": source_timestamp_ms},
    )


def run_phase3_transcript_router_regression() -> dict[str, Any]:
    router = TranscriptRouter()
    fresh_state = _state(source_timestamp_ms=int(time.time() * 1000))
    stale_state = _state(source_timestamp_ms=0)

    structured = router.route(
        state=fresh_state,
        fast_intent=_fast("后车差距", query_kind="rear_gap"),
        semantic_intent=_semantic("rear_gap", text="后车差距"),
    )
    explainer = router.route(
        state=fresh_state,
        fast_intent=_fast("整体形势怎么样", query_kind="overall_situation"),
        semantic_intent=_semantic("overall_situation", text="整体形势怎么样"),
    )
    open_fallback = router.route(
        state=fresh_state,
        fast_intent=_fast("这一圈大概会怎么发展", status="fallback"),
        semantic_intent=_semantic("open_fallback", text="这一圈大概会怎么发展", reason="open_fallback"),
    )
    disallowed = router.route(
        state=fresh_state,
        fast_intent=_fast("现在帮我决定要不要进站", status="fallback"),
        semantic_intent=_semantic("pit_status", text="现在帮我决定要不要进站"),
    )
    control = router.route(
        state=fresh_state,
        fast_intent=_fast("取消", query_kind="cancel"),
        semantic_intent=_semantic("cancel", text="取消"),
    )
    unmatched = router.route(
        state=fresh_state,
        fast_intent=_fast("", status="fallback"),
        semantic_intent=_semantic(None, text="", status="fallback", reason="semantic_unmatched"),
    )
    companion = router.route(
        state=stale_state,
        fast_intent=_fast("你是谁", status="fallback"),
        semantic_intent=_semantic("open_fallback", text="你是谁", reason="open_fallback"),
    )
    companion_racing_query = router.route(
        state=stale_state,
        fast_intent=_fast("后车差距", query_kind="rear_gap"),
        semantic_intent=_semantic("rear_gap", text="后车差距"),
    )

    checks = {
        "structured_lane": structured.status == "routed"
        and structured.lane == "structured"
        and not structured.llm_sidecar_eligible,
        "explainer_lane": explainer.status == "routed"
        and explainer.lane == "explainer"
        and explainer.llm_sidecar_eligible,
        "open_fallback_is_explainer_candidate": open_fallback.status == "routed"
        and open_fallback.lane == "explainer"
        and open_fallback.llm_sidecar_eligible,
        "disallowed_domain_rejected": disallowed.status == "reject"
        and disallowed.reason == "disallowed_domain",
        "control_lane": control.status == "routed"
        and control.lane == "control"
        and not control.llm_sidecar_eligible,
        "semantic_unmatched_rejected": unmatched.status == "reject"
        and unmatched.reason == "semantic_unmatched",
        "companion_lane_for_stale_state": companion.status == "routed"
        and companion.lane == "companion"
        and companion.should_call_llm_sidecar
        and not companion.should_call_core,
        "companion_overrides_structured_when_not_racing": companion_racing_query.status == "routed"
        and companion_racing_query.lane == "companion"
        and companion_racing_query.query_kind == "rear_gap",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "structured": structured.to_dict(),
            "explainer": explainer.to_dict(),
            "open_fallback": open_fallback.to_dict(),
            "disallowed": disallowed.to_dict(),
            "control": control.to_dict(),
            "unmatched": unmatched.to_dict(),
            "companion": companion.to_dict(),
            "companion_racing_query": companion_racing_query.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_transcript_router_regression(), ensure_ascii=False, indent=2))

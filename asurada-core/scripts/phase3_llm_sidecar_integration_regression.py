from __future__ import annotations

import json
import time
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.llm_explainer import LlmExplainer
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.persona_registry import get_default_persona
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


class SuccessBackend:
    name = "success_llm"

    def explain(self, request):  # type: ignore[no-untyped-def]
        return {
            "status": "answerable",
            "answer_text": "好的，当前整体先守住后车，再处理处罚窗口",
            "confidence": 0.82,
            "reason_fields": ["rear_pressure", "penalty_window"],
            "requires_confirmation": False,
            "metadata": {"request_id": request.request_id},
        }


class TimeoutBackend:
    name = "timeout_llm"

    def explain(self, request):  # type: ignore[no-untyped-def]
        time.sleep(max(request.timeout_ms / 1000.0, 0.05) + 0.1)
        return {
            "status": "answerable",
            "answer_text": "不应返回",
            "confidence": 1.0,
            "reason_fields": [],
            "requires_confirmation": False,
            "metadata": {},
        }


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=38.0, age_laps=12)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=18,
        gap_ahead_s=1.284,
        gap_behind_s=0.944,
        fuel_laps_remaining=10.6,
        ers_pct=61.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=267.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=5,
        lap=18,
        gap_ahead_s=0.944,
        gap_behind_s=None,
        fuel_laps_remaining=10.1,
        ers_pct=58.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=265.0,
    )
    return SessionState(
        session_uid="session-llm-sidecar",
        track="Austria",
        lap_number=18,
        total_laps=36,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_200_000_000,
        raw={
            "frame_identifier": 420,
            "overall_frame_identifier": 2420,
            "session_time_s": 1320.5,
            "source_timestamp_ms": 1_777_200_000_000,
            "pit_status": "NONE",
            "num_pit_stops": 1,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 1,
            "pit_stop_should_serve_pen": True,
            "total_warnings": 1,
            "corner_cutting_warnings": 1,
        },
    )


def _make_turn(transcript_text: str, turn_id: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id=turn_id,
        started_at_ms=1_777_200_000_100,
        ended_at_ms=1_777_200_000_420,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def run_phase3_llm_sidecar_integration_regression() -> dict[str, Any]:
    default_persona = get_default_persona()
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )

    success_output = ConsoleVoiceOutput(backend=NullSpeechBackend())
    success_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        llm_explainer=LlmExplainer(backend=SuccessBackend()),
        enable_llm_sidecar=True,
        llm_timeout_ms=900,
    )
    success_result = success_coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("整体形势怎么样", "voice-turn:llm:success"),
        voice_output=success_output,
        primary_message=primary_message,
        render=False,
    )

    timeout_output = ConsoleVoiceOutput(backend=NullSpeechBackend())
    timeout_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        llm_explainer=LlmExplainer(backend=TimeoutBackend(), default_timeout_ms=100),
        enable_llm_sidecar=True,
        llm_timeout_ms=100,
    )
    timeout_result = timeout_coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("为什么现在不进攻", "voice-turn:llm:timeout"),
        voice_output=timeout_output,
        primary_message=primary_message,
        render=False,
    )

    success_event = (((success_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {})
    success_llm = (((success_result.output_debug or {}).get("voice_pipeline_log") or {}).get("llm_sidecar") or {})
    timeout_event = (((timeout_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {})
    timeout_llm = (((timeout_result.output_debug or {}).get("voice_pipeline_log") or {}).get("llm_sidecar") or {})
    success_active = (((success_result.output_debug or {}).get("output_lifecycle") or {}).get("active_output") or {})

    checks = {
        "success_lane_explainer": (success_result.route_decision or {}).get("lane") == "explainer",
        "success_override_used": success_event.get("speak_text") == "当前整体先守住后车，再处理处罚窗口。",
        "success_llm_logged": success_llm.get("used") is True and success_llm.get("backend_name") == "success_llm",
        "success_persona_propagated": success_event.get("metadata", {}).get("persona_id") == default_persona.persona_id
        and success_event.get("metadata", {}).get("voice_profile_id") == default_persona.voice_profile_id
        and success_active.get("persona_id") == default_persona.persona_id
        and success_active.get("voice_profile_id") == default_persona.voice_profile_id,
        "timeout_falls_back_to_core": timeout_event.get("action_code") == "QUERY_WHY_NOT_ATTACK"
        and "现在没有给出进攻窗口" in str(timeout_event.get("speak_text") or ""),
        "timeout_llm_logged": timeout_llm.get("used") is False and timeout_llm.get("fallback_reason") == "llm_timeout",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "success_result": success_result.to_dict(),
            "timeout_result": timeout_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_llm_sidecar_integration_regression(), ensure_ascii=False, indent=2))

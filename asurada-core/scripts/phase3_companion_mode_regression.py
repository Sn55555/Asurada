from __future__ import annotations

import json
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.llm_explainer import LlmExplainer
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


class CompanionBackend:
    name = "companion_backend"

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def explain(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request.to_dict())
        return {
            "status": "answerable",
            "answer_text": "我在。现在没有实时比赛数据，不过可以先陪你聊天。",
            "confidence": 0.88,
            "reason_fields": ["companion_mode"],
            "requires_confirmation": False,
            "metadata": {"interaction_mode": request.interaction_mode},
        }


class CompanionTimeoutRetryBackend:
    name = "companion_timeout_retry_backend"

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def explain(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request.to_dict())
        if int(request.timeout_ms or 0) < 3200:
            import time

            time.sleep(max(request.timeout_ms / 1000.0, 0.01) + 0.15)
        return {
            "status": "answerable",
            "answer_text": "可以，想聊日常、电影、游戏或者赛车之外的话题都行。",
            "confidence": 0.84,
            "reason_fields": ["companion_retry"],
            "requires_confirmation": False,
            "metadata": {"interaction_mode": request.interaction_mode},
        }


def _make_state(*, source_timestamp_ms: int) -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=24.0, age_laps=6)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=12,
        gap_ahead_s=1.1,
        gap_behind_s=0.9,
        fuel_laps_remaining=10.4,
        ers_pct=58.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=274.0,
    )
    return SessionState(
        session_uid="session-companion-regression",
        track="Austria",
        lap_number=12,
        total_laps=36,
        weather="Clear",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=source_timestamp_ms,
        raw={
            "frame_identifier": 220,
            "overall_frame_identifier": 1220,
            "session_time_s": 820.1,
            "source_timestamp_ms": source_timestamp_ms,
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


def run_phase3_companion_mode_regression() -> dict[str, Any]:
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )
    backend = CompanionBackend()
    retry_backend = CompanionTimeoutRetryBackend()
    coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        llm_explainer=LlmExplainer(backend=backend),
        enable_llm_sidecar=True,
        llm_timeout_ms=900,
    )
    voice_output = ConsoleVoiceOutput(backend=NullSpeechBackend())

    companion_result = coordinator.process_completed_turn(
        state=_make_state(source_timestamp_ms=0),
        turn=_make_turn("你是谁", "voice-turn:companion"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    racing_result = coordinator.process_completed_turn(
        state=_make_state(source_timestamp_ms=1_777_200_000_000),
        turn=_make_turn("后车差距", "voice-turn:racing"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    retry_output = ConsoleVoiceOutput(backend=NullSpeechBackend())
    retry_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        llm_explainer=LlmExplainer(backend=retry_backend, default_timeout_ms=900),
        enable_llm_sidecar=True,
        llm_timeout_ms=900,
    )
    retry_result = retry_coordinator.process_completed_turn(
        state=_make_state(source_timestamp_ms=0),
        turn=_make_turn("你能陪我聊什么", "voice-turn:companion:retry"),
        voice_output=retry_output,
        primary_message=primary_message,
        render=False,
    )

    companion_event = (((companion_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {})
    companion_llm = (((companion_result.output_debug or {}).get("voice_pipeline_log") or {}).get("llm_sidecar") or {})
    companion_request = backend.requests[0] if backend.requests else {}
    retry_event = (((retry_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {})
    retry_request_timeouts = [int((req.get("timeout_ms") or 0)) for req in retry_backend.requests]

    checks = {
        "companion_lane": (companion_result.route_decision or {}).get("lane") == "companion",
        "companion_action_code": companion_event.get("action_code") == "QUERY_COMPANION_CHAT",
        "companion_llm_used": companion_llm.get("used") is True and companion_llm.get("backend_name") == "companion_backend",
        "companion_request_mode": companion_request.get("interaction_mode") == "companion_chat",
        "companion_runtime_context": (
            ((companion_request.get("state_summary") or {}).get("state_snapshot") or {})
            .get("runtime_context", {})
            .get("racing_active")
            is False
        ),
        "racing_state_stays_structured": (racing_result.route_decision or {}).get("lane") == "structured",
        "companion_timeout_retry_succeeds": "赛车之外的话题都行" in str(retry_event.get("speak_text") or ""),
        "companion_timeout_retry_attempted_twice": retry_request_timeouts == [900, 3200],
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "companion_result": companion_result.to_dict(),
            "racing_result": racing_result.to_dict(),
            "companion_request": companion_request,
            "retry_result": retry_result.to_dict(),
            "retry_request_timeouts": retry_request_timeouts,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_companion_mode_regression(), ensure_ascii=False, indent=2))

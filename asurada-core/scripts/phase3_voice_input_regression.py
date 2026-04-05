from __future__ import annotations

import json
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=15.0, age_laps=4)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=8,
        gap_ahead_s=0.714,
        gap_behind_s=1.102,
        fuel_laps_remaining=11.8,
        ers_pct=63.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=281.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=6,
        lap=8,
        gap_ahead_s=1.102,
        gap_behind_s=None,
        fuel_laps_remaining=11.2,
        ers_pct=49.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=279.0,
    )
    return SessionState(
        session_uid="session-voice-e2e",
        track="Suzuka",
        lap_number=8,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_100_000_000,
        raw={
            "frame_identifier": 188,
            "overall_frame_identifier": 1188,
            "session_time_s": 588.204,
            "source_timestamp_ms": 1_777_100_000_000,
        },
    )


def _make_turn(transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id="voice-turn:e2e",
        started_at_ms=1_777_100_000_200,
        ended_at_ms=1_777_100_000_560,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def run_phase3_voice_input_regression() -> dict[str, Any]:
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )
    coordinator = VoiceInputCoordinator(fast_intent_asr=KeywordFastIntentASR())
    voice_output = ConsoleVoiceOutput(backend=NullSpeechBackend())

    rear_gap_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("后车差距"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    cancel_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("取消"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    fallback_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("帮我解释一下刚才为什么没有进站"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )

    rear_gap_debug = rear_gap_result.output_debug or {}
    output_event = ((rear_gap_debug.get("output_lifecycle") or {}).get("event") or {})
    asr_stage = ((rear_gap_debug.get("voice_pipeline_log") or {}).get("asr") or {})

    checks = {
        "spoken_status": rear_gap_result.status == "spoken",
        "asr_fast_input_type": (rear_gap_debug.get("interaction_input_event") or {}).get("input_type") == "asr_fast_query",
        "rear_gap_start_event": output_event.get("event_type") == "start" and output_event.get("action_code") == "QUERY_REAR_GAP",
        "asr_stage_completed": asr_stage.get("stage_status") == "completed",
        "query_route_voice": (rear_gap_debug.get("query_route") or {}).get("response_channel") == "voice",
        "control_query_recognized": cancel_result.status == "control_unwired"
        and (cancel_result.bundle or {}).get("structured_query", {}).get("query_kind") == "cancel",
        "fallback_unmatched": fallback_result.status == "fallback",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "rear_gap_result": rear_gap_result.to_dict(),
            "cancel_result": cancel_result.to_dict(),
            "fallback_result": fallback_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_input_regression(), ensure_ascii=False, indent=2))

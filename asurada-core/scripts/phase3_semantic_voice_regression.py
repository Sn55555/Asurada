from __future__ import annotations

import json
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.conversation_context import ConversationContext
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.semantic_normalizer import SemanticNormalizer
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=28.0, age_laps=8)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=12,
        gap_ahead_s=1.284,
        gap_behind_s=0.944,
        fuel_laps_remaining=10.6,
        ers_pct=61.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=273.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=6,
        lap=12,
        gap_ahead_s=0.944,
        gap_behind_s=None,
        fuel_laps_remaining=10.2,
        ers_pct=47.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=271.0,
    )
    return SessionState(
        session_uid="session-semantic-voice",
        track="Suzuka",
        lap_number=12,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_300_000_000,
        raw={
            "frame_identifier": 312,
            "overall_frame_identifier": 1312,
            "session_time_s": 812.12,
            "source_timestamp_ms": 1_777_300_000_000,
            "pit_status": "NONE",
            "num_pit_stops": 1,
            "pit_lane_timer_active": False,
            "pit_stop_timer_ms": 0,
            "total_warnings": 3,
            "corner_cutting_warnings": 1,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 1,
            "pit_stop_should_serve_pen": True,
        },
    )


def _make_turn(turn_id: str, transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id=turn_id,
        started_at_ms=1_777_300_000_100,
        ended_at_ms=1_777_300_000_480,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def run_phase3_semantic_voice_regression() -> dict[str, Any]:
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )
    coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        semantic_normalizer=SemanticNormalizer(),
        conversation_context=ConversationContext(),
    )
    voice_output = ConsoleVoiceOutput(backend=NullSpeechBackend())

    natural_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:natural", "后面那个现在贴多近"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    followup_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:followup", "现在呢"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    explain_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:explain", "为什么现在不进攻"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    pit_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:pit", "现在进站情况怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    why_not_pit_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:why-pit", "为什么现在没有进站"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    weather_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:weather", "现在天气怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    penalty_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:penalty", "现在有处罚吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    unsupported_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:unsupported", "整体形势怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )

    natural_event = ((natural_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    followup_event = ((followup_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    explain_event = ((explain_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})

    checks = {
        "natural_language_maps_rear_gap": natural_result.status == "spoken"
        and (natural_result.bundle or {}).get("structured_query", {}).get("query_kind") == "rear_gap",
        "followup_uses_context": followup_result.status == "spoken"
        and (followup_result.bundle or {}).get("structured_query", {}).get("query_kind") == "rear_gap",
        "explanation_query_maps": explain_result.status == "spoken"
        and (explain_result.bundle or {}).get("structured_query", {}).get("query_kind") == "why_not_attack",
        "explanation_response_mentions_reason": "因为" in str(explain_event.get("speak_text") or ""),
        "natural_response_is_conclusion_first": "后车已经进直接防守窗口" in str(natural_event.get("speak_text") or "")
        or "后车正在逼近" in str(natural_event.get("speak_text") or "")
        or "后车暂时还没进直接防守窗口" in str(natural_event.get("speak_text") or ""),
        "pit_status_maps": pit_result.status == "spoken"
        and (pit_result.bundle or {}).get("structured_query", {}).get("query_kind") == "pit_status",
        "why_not_pit_maps": why_not_pit_result.status == "spoken"
        and (why_not_pit_result.bundle or {}).get("structured_query", {}).get("query_kind") == "why_not_pit",
        "weather_status_maps": weather_result.status == "spoken"
        and (weather_result.bundle or {}).get("structured_query", {}).get("query_kind") == "weather_status",
        "penalty_status_maps": penalty_result.status == "spoken"
        and (penalty_result.bundle or {}).get("structured_query", {}).get("query_kind") == "penalty_status",
        "unsupported_topic_uses_open_fallback": unsupported_result.status == "spoken"
        and (unsupported_result.bundle or {}).get("structured_query", {}).get("query_kind") == "open_fallback",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "natural_result": natural_result.to_dict(),
            "followup_result": followup_result.to_dict(),
            "explain_result": explain_result.to_dict(),
            "pit_result": pit_result.to_dict(),
            "why_not_pit_result": why_not_pit_result.to_dict(),
            "weather_result": weather_result.to_dict(),
            "penalty_result": penalty_result.to_dict(),
            "unsupported_result": unsupported_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_semantic_voice_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

import json

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.models import DriverState, SessionState, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput, NullSpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn
from asurada.wake_word import WakeWordGate


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
        session_uid="session-wake-word",
        track="Suzuka",
        lap_number=8,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_300_000_000,
        raw={
            "frame_identifier": 188,
            "overall_frame_identifier": 1188,
            "session_time_s": 588.204,
            "source_timestamp_ms": 1_777_300_000_000,
        },
    )


def _make_turn(transcript_text: str, *, ended_at_ms: int, transcript_hint: str | None = None) -> VoiceTurn:
    metadata = {"transcript_text": transcript_text}
    if transcript_hint is not None:
        metadata["transcript_hint"] = transcript_hint
    return VoiceTurn(
        turn_id=f"voice-turn:wake:{ended_at_ms}",
        started_at_ms=ended_at_ms - 320,
        ended_at_ms=ended_at_ms,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="macos_speech",
        completion_reason="recognized",
        metadata=metadata,
    )


def run_phase3_wake_word_regression() -> dict[str, object]:
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )
    coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        wake_word_gate=WakeWordGate(enabled=True, phrases=("阿斯拉达", "asurada"), activation_window_ms=8_000),
    )
    alias_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        wake_word_gate=WakeWordGate(enabled=True, phrases=("阿斯拉达", "asurada"), activation_window_ms=8_000),
    )
    partial_hint_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        wake_word_gate=WakeWordGate(enabled=True, phrases=("阿斯拉达", "asurada"), activation_window_ms=8_000),
    )
    preview_gate = WakeWordGate(enabled=True, phrases=("阿斯拉达", "asurada"), activation_window_ms=8_000)
    preview_arm_coordinator = VoiceInputCoordinator(
        fast_intent_asr=KeywordFastIntentASR(),
        wake_word_gate=WakeWordGate(enabled=True, phrases=("阿斯拉达", "asurada"), activation_window_ms=8_000),
    )
    voice_output = ConsoleVoiceOutput(backend=NullSpeechBackend())

    ignored = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("后车差距", ended_at_ms=1_777_300_000_500),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    wake_only = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("阿斯拉达", ended_at_ms=1_777_300_002_000),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    active_window = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("整体形势怎么样", ended_at_ms=1_777_300_004_000),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    inline_query = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("阿斯拉达 后车差距", ended_at_ms=1_777_300_020_000),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    expired = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("现在最该注意什么", ended_at_ms=1_777_300_040_500),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    alias_inline_query = alias_coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("饿死拉倒陪我聊天", ended_at_ms=1_777_300_024_000),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    partial_hint_query = partial_hint_coordinator.process_completed_turn(
        state=state,
        turn=_make_turn(
            "后车差距",
            ended_at_ms=1_777_300_026_000,
            transcript_hint="饿死拉倒后车差距",
        ),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    preview_arm_gate = preview_arm_coordinator.wake_word_gate
    preview_arm_gate.arm_from_preview(
        timestamp_ms=1_777_300_028_000,
        matched_phrase="阿斯拉达",
    )
    preview_armed_query = preview_arm_coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("后车差距", ended_at_ms=1_777_300_028_500),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )

    active_window_event = ((active_window.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    inline_event = ((inline_query.output_debug or {}).get("output_lifecycle") or {}).get("event", {})

    checks = {
        "missing_wake_ignored": ignored.status == "ignored",
        "wake_only_arms": wake_only.status == "wake_armed",
        "active_window_allows_follow_up": active_window.status == "spoken"
        and (((active_window.bundle or {}).get("structured_query") or {}).get("query_kind") == "overall_situation"),
        "active_window_metadata_present": (((active_window.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("reason") == "wake_window_active",
        "inline_wake_strips_prefix": inline_query.status == "spoken"
        and inline_event.get("action_code") == "QUERY_REAR_GAP"
        and (((inline_query.voice_turn or {}).get("metadata") or {}).get("transcript_text") == "后车差距"),
        "alias_inline_wake_matches": alias_inline_query.status == "spoken"
        and ((((alias_inline_query.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("matched_phrase") == "阿斯拉达")
        and (((alias_inline_query.voice_turn or {}).get("metadata") or {}).get("transcript_text") == "陪我聊天"),
        "preview_alias_matches": preview_gate.preview_match("饿死拉倒后车差距") == ("阿斯拉达", "后车差距"),
        "preview_arm_allows_follow_up": preview_armed_query.status == "spoken"
        and ((((preview_armed_query.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("status") == "active_window")
        and (((((preview_armed_query.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("metadata") or {}).get("activation_source") == "partial_preview"),
        "partial_hint_wake_matches": partial_hint_query.status == "spoken"
        and ((((partial_hint_query.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("matched_phrase") == "阿斯拉达")
        and (((((partial_hint_query.voice_turn or {}).get("metadata") or {}).get("wake_word") or {}).get("metadata") or {}).get("matched_source") == "transcript_hint")
        and (((partial_hint_query.voice_turn or {}).get("metadata") or {}).get("transcript_text") == "后车差距"),
        "expired_window_ignored": expired.status == "ignored",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "ignored": ignored.to_dict(),
            "wake_only": wake_only.to_dict(),
            "active_window": active_window.to_dict(),
            "inline_query": inline_query.to_dict(),
            "alias_inline_query": alias_inline_query.to_dict(),
            "preview_armed_query": preview_armed_query.to_dict(),
            "partial_hint_query": partial_hint_query.to_dict(),
            "expired": expired.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_wake_word_regression(), ensure_ascii=False, indent=2))

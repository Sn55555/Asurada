from __future__ import annotations

import json
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.models import DriverState, SessionState, TyreState
from asurada.voice_nlu import build_voice_query_bundle
from asurada.voice_turn import VoiceTurn


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=18.0, age_laps=6)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=4,
        lap=7,
        gap_ahead_s=0.842,
        gap_behind_s=1.314,
        fuel_laps_remaining=12.4,
        ers_pct=57.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=287.0,
    )
    return SessionState(
        session_uid="session-fast-intent",
        track="Suzuka",
        lap_number=7,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_777_000_000_000,
        raw={
            "frame_identifier": 77,
            "overall_frame_identifier": 1077,
            "session_time_s": 432.118,
            "source_timestamp_ms": 1_777_000_000_000,
        },
    )


def _make_turn(*, transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id="voice-turn:test",
        started_at_ms=1_777_000_000_100,
        ended_at_ms=1_777_000_000_420,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def run_phase3_fast_intent_regression() -> dict[str, Any]:
    recognizer = KeywordFastIntentASR()
    state = _make_state()

    rear_gap_turn = _make_turn(transcript_text="后车差距")
    rear_gap_result = recognizer.recognize_turn(rear_gap_turn)
    rear_gap_bundle = build_voice_query_bundle(
        state=state,
        voice_turn=rear_gap_turn,
        fast_intent=rear_gap_result,
    )

    cancel_turn = _make_turn(transcript_text="取消")
    cancel_result = recognizer.recognize_turn(cancel_turn)

    fallback_turn = _make_turn(transcript_text="帮我解释为什么刚才那圈不进站")
    fallback_result = recognizer.recognize_turn(fallback_turn)

    checks = {
        "rear_gap_matches": rear_gap_result.query_kind == "rear_gap" and rear_gap_result.status == "matched",
        "rear_gap_bundle_routes": rear_gap_bundle.structured_query["query_kind"] == "rear_gap"
        and rear_gap_bundle.query_route["handler"] == "rear_gap_snapshot_handler",
        "asr_fast_input_type": rear_gap_bundle.input_event["input_type"] == "asr_fast_query",
        "cancel_maps_to_control_query": cancel_result.query_kind == "cancel",
        "fallback_unmatched": fallback_result.status == "fallback" and fallback_result.query_kind is None,
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "rear_gap_result": rear_gap_result.to_dict(),
            "rear_gap_bundle": rear_gap_bundle.to_dict(),
            "cancel_result": cancel_result.to_dict(),
            "fallback_result": fallback_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_fast_intent_regression(), ensure_ascii=False, indent=2))

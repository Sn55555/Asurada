from __future__ import annotations

from dataclasses import asdict
from typing import Any

from asurada.audio_io import AudioChunk, AudioFormat
from asurada.vad import EnergyVadBackend, VoiceActivityDetector
from asurada.voice_turn import VoiceTurnManager


def _make_chunk(*, sequence_id: int, timestamp_ms: int, amplitude: int, duration_ms: int = 40) -> AudioChunk:
    frame_count = int((16_000 * duration_ms) / 1000)
    sample = int(max(min(amplitude, 32_767), -32_768)).to_bytes(2, byteorder="little", signed=True)
    pcm = sample * frame_count
    return AudioChunk(
        sequence_id=sequence_id,
        timestamp_ms=timestamp_ms,
        pcm_s16le=pcm,
        audio_format=AudioFormat(),
    )


def run_phase3_audio_regression() -> dict[str, Any]:
    vad = VoiceActivityDetector(
        backend=EnergyVadBackend(rms_threshold=900),
        start_trigger_count=2,
        end_silence_ms=120,
    )
    manager = VoiceTurnManager(require_ptt=True, max_turn_ms=2_000)

    checks: dict[str, bool] = {}

    ignored_events, ignored_turn = manager.ingest_chunk(
        chunk=_make_chunk(sequence_id=1, timestamp_ms=0, amplitude=0),
        vad_decision=vad.process_chunk(_make_chunk(sequence_id=1, timestamp_ms=0, amplitude=0))[0],
        vad_activity=vad.process_chunk(_make_chunk(sequence_id=1, timestamp_ms=0, amplitude=0))[1],
    )
    checks["ignore_without_ptt"] = ignored_turn is None and ignored_events[0].event_type == "chunk_ignored"

    arm_events = manager.set_ptt_pressed(True, timestamp_ms=100)
    checks["ptt_arms"] = bool(arm_events) and arm_events[0].event_type == "ptt_armed"

    speech_start_seen = False
    completed_turn = None
    buffered_chunk_events = 0
    sequence_id = 10
    for timestamp_ms, amplitude in [
        (120, 1200),
        (160, 1200),
        (200, 1500),
        (240, 1500),
        (280, 0),
        (320, 0),
        (360, 0),
    ]:
        chunk = _make_chunk(sequence_id=sequence_id, timestamp_ms=timestamp_ms, amplitude=amplitude)
        decision, activity = vad.process_chunk(chunk)
        events, maybe_turn = manager.ingest_chunk(chunk=chunk, vad_decision=decision, vad_activity=activity)
        sequence_id += 1
        speech_start_seen = speech_start_seen or any(event.event_type == "turn_started" for event in events)
        buffered_chunk_events += len([event for event in events if event.event_type == "turn_chunk"])
        if maybe_turn is not None:
            completed_turn = maybe_turn

    checks["speech_starts_after_hysteresis"] = speech_start_seen
    checks["buffers_chunks"] = buffered_chunk_events >= 3
    checks["vad_completes_turn"] = completed_turn is not None and completed_turn.completion_reason == "vad_speech_end"

    release_events = manager.set_ptt_pressed(False, timestamp_ms=400)
    checks["ptt_release_without_active_turn"] = bool(release_events) and release_events[0].event_type == "ptt_released"

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "completed_turn": completed_turn.to_dict() if completed_turn is not None else None,
            "release_events": [asdict(event) for event in release_events],
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_phase3_audio_regression(), ensure_ascii=False, indent=2))

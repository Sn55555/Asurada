from __future__ import annotations

import json
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.asr_fast import KeywordFastIntentASR
from asurada.interaction import SpeechJob
from asurada.models import DriverState, SessionState, StrategyDecision, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput
from asurada.tts_backends import SpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


class StickySpeechBackend(SpeechBackend):
    def start(self, job: SpeechJob) -> dict[str, Any]:
        return {"active": True, "job": job.action_code}

    def is_active(self, handle: dict[str, Any] | None) -> bool:
        return bool(handle and handle.get("active"))

    def stop(self, handle: dict[str, Any] | None) -> None:
        if handle is not None:
            handle["active"] = False


def _make_state() -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=12.0, age_laps=6)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=5,
        lap=10,
        gap_ahead_s=0.608,
        gap_behind_s=0.944,
        fuel_laps_remaining=9.6,
        ers_pct=57.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=276.0,
    )
    rival = DriverState(
        car_index=1,
        name="Russell",
        position=6,
        lap=10,
        gap_ahead_s=0.944,
        gap_behind_s=None,
        fuel_laps_remaining=9.1,
        ers_pct=42.0,
        drs_available=False,
        tyre=tyre,
        speed_kph=274.0,
    )
    return SessionState(
        session_uid="session-voice-control",
        track="Suzuka",
        lap_number=10,
        total_laps=53,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[rival],
        source_timestamp_ms=1_777_200_000_000,
        raw={
            "frame_identifier": 240,
            "overall_frame_identifier": 1240,
            "session_time_s": 680.12,
            "source_timestamp_ms": 1_777_200_000_000,
        },
    )


def _make_turn(turn_id: str, transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id=turn_id,
        started_at_ms=1_777_200_000_000,
        ended_at_ms=1_777_200_000_420,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def _seed_active_broadcast(voice_output: ConsoleVoiceOutput) -> dict[str, Any]:
    decision = StrategyDecision(
        messages=[
            StrategyMessage(
                code="DEFEND_WINDOW",
                priority=92,
                title="防守窗口",
                detail="后车已接近 DRS 线。",
            )
        ],
        debug={
            "interaction_input_event": {
                "interaction_session_id": "runtime:session-voice-control",
                "turn_id": "turn:seed",
                "request_id": "req:seed",
                "snapshot_binding_id": "snap:seed",
            },
            "task_handle": {
                "task_id": "task:req:seed",
                "request_id": "req:seed",
                "turn_id": "turn:seed",
                "task_type": "push_broadcast",
                "handler": "strategy_output_handler",
            },
            "arbiter_v2": {
                "output": {
                    "final_voice_action": {
                        "priority": 92,
                        "speak_text": "防守窗口",
                    }
                }
            },
        },
    )
    return voice_output.emit(decision, render=False)


def run_phase3_voice_control_regression() -> dict[str, Any]:
    state = _make_state()
    primary_message = StrategyMessage(
        code="DEFEND_WINDOW",
        priority=92,
        title="防守窗口",
        detail="后车已接近 DRS 线。",
    )
    coordinator = VoiceInputCoordinator(fast_intent_asr=KeywordFastIntentASR())

    repeat_output = ConsoleVoiceOutput(backend=StickySpeechBackend())
    _seed_active_broadcast(repeat_output)
    repeat_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:repeat", "重复"),
        voice_output=repeat_output,
        primary_message=primary_message,
        render=False,
    )

    stop_output = ConsoleVoiceOutput(backend=StickySpeechBackend())
    _seed_active_broadcast(stop_output)
    stop_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:stop", "停止"),
        voice_output=stop_output,
        primary_message=primary_message,
        render=False,
    )

    cancel_output = ConsoleVoiceOutput(backend=StickySpeechBackend())
    _seed_active_broadcast(cancel_output)
    rear_gap_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:rear-gap", "后车差距"),
        voice_output=cancel_output,
        primary_message=primary_message,
        render=False,
    )
    cancel_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:cancel", "取消"),
        voice_output=cancel_output,
        primary_message=primary_message,
        render=False,
    )

    repeat_event = ((repeat_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    stop_event = ((stop_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    cancel_event = ((cancel_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})

    checks = {
        "repeat_executes": repeat_result.status == "control_executed"
        and repeat_event.get("event_type") in {"enqueue", "replace_pending"},
        "repeat_uses_repeat_code": repeat_event.get("action_code") == "QUERY_REPEAT_LAST",
        "stop_cancels_active": stop_result.status == "control_executed"
        and stop_event.get("event_type") == "cancel",
        "stop_clears_active_output": ((stop_result.output_debug or {}).get("output_lifecycle") or {}).get("active_output") is None,
        "cancel_cancels_pending": cancel_result.status == "control_executed"
        and cancel_event.get("event_type") == "cancel",
        "cancel_keeps_active_output": ((cancel_result.output_debug or {}).get("output_lifecycle") or {}).get("active_output") is not None,
        "cancel_clears_pending_output": ((cancel_result.output_debug or {}).get("output_lifecycle") or {}).get("pending_output") is None,
        "seeded_pending_exists": ((rear_gap_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {}).get("event_type") == "enqueue",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "repeat_result": repeat_result.to_dict(),
            "stop_result": stop_result.to_dict(),
            "rear_gap_result": rear_gap_result.to_dict(),
            "cancel_result": cancel_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_control_regression(), ensure_ascii=False, indent=2))

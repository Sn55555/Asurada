from __future__ import annotations

from regression_support import ImmediateSpeechBackend, emit_result

import json
import os
import tempfile

from asurada.audio_io import AudioFormat
from asurada.corner_gear_assist import CornerGearAssistController
from asurada.models import DriverState, SessionState, StrategyDecision, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


def _make_state(*, lap_number: int = 5, lap_distance_m: float = 3200.0, track: str = "Shanghai") -> SessionState:
    tyre = TyreState(compound="Medium", wear_pct=18.0, age_laps=8)
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=2,
        lap=lap_number,
        gap_ahead_s=0.7,
        gap_behind_s=1.0,
        fuel_laps_remaining=11.0,
        ers_pct=58.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=265.0,
        lap_distance_m=lap_distance_m,
    )
    return SessionState(
        session_uid="session-corner-gear-assist",
        track=track,
        lap_number=lap_number,
        total_laps=56,
        weather="LightCloud",
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_777_600_000_000,
        raw={
            "frame_identifier": 512,
            "overall_frame_identifier": 1512,
            "session_time_s": 1024.0,
            "source_timestamp_ms": 1_777_600_000_000,
            "lap_distance_m": lap_distance_m,
            "track_length_m": 5438.675,
        },
    )


def _make_turn(turn_id: str, transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id=turn_id,
        started_at_ms=1_777_600_000_100,
        ended_at_ms=1_777_600_000_400,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata={"transcript_text": transcript_text},
    )


def _make_decision() -> StrategyDecision:
    return StrategyDecision(
        messages=[StrategyMessage(code="NONE", priority=0, title="无策略变化", detail="")],
        debug={
            "interaction_input_event": {
                "interaction_session_id": "runtime:session-corner-gear-assist",
                "turn_id": "turn:runtime",
                "request_id": "req:runtime",
                "snapshot_binding_id": "snap:runtime",
            },
            "task_handle": {
                "task_id": "task:req:runtime",
                "request_id": "req:runtime",
                "turn_id": "turn:runtime",
                "task_type": "push_broadcast",
                "handler": "strategy_output_handler",
            },
            "arbiter_v2": {"output": {"final_voice_action": {}}},
        },
    )


def run_phase3_voice_corner_gear_assist_regression() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="asurada-corner-gear-assist-") as temp_dir:
        state_path = os.path.join(temp_dir, "corner_gear_assist_state.json")
        previous_state_path = os.environ.get("ASURADA_CORNER_GEAR_ASSIST_STATE_PATH")
        os.environ["ASURADA_CORNER_GEAR_ASSIST_STATE_PATH"] = state_path
        try:
            coordinator = VoiceInputCoordinator()
            control_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            runtime_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            armed_state = _make_state(lap_distance_m=3200.0)

            enable_result = coordinator.process_completed_turn(
                state=armed_state,
                turn=_make_turn("voice-turn:enable-corner-gear", "开启每个弯道入弯档位语音建议"),
                voice_output=control_output,
                primary_message=None,
                render=False,
            )
            status_result = coordinator.process_completed_turn(
                state=armed_state,
                turn=_make_turn("voice-turn:status-corner-gear", "入弯档位语音建议现在开了吗"),
                voice_output=control_output,
                primary_message=None,
                render=False,
            )

            shared_snapshot = runtime_output._corner_gear_assist.snapshot()
            first_debug = runtime_output.emit(_make_decision(), state=_make_state(lap_number=5, lap_distance_m=4720.0), render=False)
            duplicate_debug = runtime_output.emit(_make_decision(), state=_make_state(lap_number=5, lap_distance_m=4740.0), render=False)
            next_lap_debug = runtime_output.emit(_make_decision(), state=_make_state(lap_number=6, lap_distance_m=4720.0), render=False)

            disable_result = coordinator.process_completed_turn(
                state=armed_state,
                turn=_make_turn("voice-turn:disable-corner-gear", "关闭入弯档位语音建议"),
                voice_output=control_output,
                primary_message=None,
                render=False,
            )
            disabled_snapshot = CornerGearAssistController().snapshot()
        finally:
            if previous_state_path is None:
                os.environ.pop("ASURADA_CORNER_GEAR_ASSIST_STATE_PATH", None)
            else:
                os.environ["ASURADA_CORNER_GEAR_ASSIST_STATE_PATH"] = previous_state_path

    first_event = ((first_debug or {}).get("event") or {})
    duplicate_event = ((duplicate_debug or {}).get("event") or {})
    next_lap_event = ((next_lap_debug or {}).get("event") or {})

    checks = {
        "enable_control_executed": enable_result.status == "processed",
        "enable_query_kind": ((enable_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "enable_corner_gear_assist",
        "enable_ack_text": "已开启" in ((((enable_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or ""),
        "status_control_executed": status_result.status == "processed",
        "status_query_kind": ((status_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "corner_gear_assist_status",
        "shared_state_persists_enable": shared_snapshot.get("mode") == "on",
        "first_corner_fires": first_event.get("event_type") == "start"
        and first_event.get("action_code") == "CORNER_GEAR_T14"
        and first_event.get("speak_text") == "T14，2档。",
        "same_lap_duplicate_suppressed": duplicate_event.get("event_type") in {"idle", "complete"}
        and duplicate_event.get("action_code") == "CORNER_GEAR_T14",
        "next_lap_refires": next_lap_event.get("event_type") == "start"
        and next_lap_event.get("action_code") == "CORNER_GEAR_T14",
        "disable_control_executed": disable_result.status == "processed",
        "disable_query_kind": ((disable_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "disable_corner_gear_assist",
        "disable_ack_text": "已关闭" in ((((disable_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or ""),
        "disabled_state_persisted": disabled_snapshot.get("mode") == "off",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "enable_result": enable_result.to_dict(),
            "status_result": status_result.to_dict(),
            "first_debug": first_debug,
            "duplicate_debug": duplicate_debug,
            "next_lap_debug": next_lap_debug,
            "disable_result": disable_result.to_dict(),
            "shared_snapshot": shared_snapshot,
            "disabled_snapshot": disabled_snapshot,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase3_voice_corner_gear_assist_regression())

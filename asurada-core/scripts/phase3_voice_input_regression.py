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
            "wing_damage_pct": {"front_left": 10, "front_right": 16, "rear": 2},
            "floor_damage_pct": 8,
            "diffuser_damage_pct": 6,
            "sidepod_damage_pct": 3,
            "gearbox_damage_pct": 1,
            "engine_damage_pct": 5,
            "engine_components_damage_pct": {},
            "engine_blown": False,
            "engine_seized": False,
            "pit_status": "NONE",
            "num_pit_stops": 1,
            "total_warnings": 2,
            "corner_cutting_warnings": 1,
            "num_unserved_drive_through_pens": 0,
            "num_unserved_stop_go_pens": 0,
            "pit_stop_should_serve_pen": False,
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
    main_risk_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("现在最该注意什么"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    tyre_outlook_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("未来几圈轮胎预计损耗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    defend_projection_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("如果我现在守住会怎样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    attack_defend_tradeoff_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("现在守和攻哪个代价更低"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    overall_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("整体形势怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    damage_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("车损情况怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    track_incident_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("赛道出什么事儿了"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    fallback_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("这一圈大概会怎么发展"),
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
        "control_query_executed": cancel_result.status == "control_executed"
        and ((cancel_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {}).get("event_type") == "cancel",
        "main_risk_spoken": main_risk_result.status == "spoken"
        and (((main_risk_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "main_risk_summary"),
        "tyre_outlook_spoken": tyre_outlook_result.status == "spoken"
        and (((tyre_outlook_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "tyre_wear_outlook")
        and (
            "未来" in str((((tyre_outlook_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or "")
            or "接下来" in str((((tyre_outlook_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or "")
        ),
        "defend_projection_spoken": defend_projection_result.status == "spoken"
        and (((defend_projection_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "defend_outcome_projection"),
        "attack_defend_tradeoff_spoken": attack_defend_tradeoff_result.status == "spoken"
        and (((attack_defend_tradeoff_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "attack_defend_tradeoff"),
        "overall_situation_spoken": overall_result.status == "spoken"
        and (((overall_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "overall_situation")
        and ("最大风险" in str((((overall_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or "")),
        "damage_spoken": damage_result.status == "spoken"
        and (((damage_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "damage_status")
        and ((((damage_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("action_code") == "QUERY_DAMAGE_STATUS"),
        "track_incident_spoken": track_incident_result.status == "spoken"
        and (((track_incident_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "race_control_status")
        and ((((track_incident_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("action_code") == "QUERY_RACE_CONTROL_STATUS"),
        "open_fallback_spoken": fallback_result.status == "spoken"
        and (((fallback_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "open_fallback")
        and ((((fallback_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("action_code") == "QUERY_OPEN_FALLBACK"),
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "rear_gap_result": rear_gap_result.to_dict(),
            "cancel_result": cancel_result.to_dict(),
            "main_risk_result": main_risk_result.to_dict(),
            "tyre_outlook_result": tyre_outlook_result.to_dict(),
            "defend_projection_result": defend_projection_result.to_dict(),
            "attack_defend_tradeoff_result": attack_defend_tradeoff_result.to_dict(),
            "overall_result": overall_result.to_dict(),
            "damage_result": damage_result.to_dict(),
            "track_incident_result": track_incident_result.to_dict(),
            "fallback_result": fallback_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_input_regression(), ensure_ascii=False, indent=2))

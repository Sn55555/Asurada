from __future__ import annotations

from regression_support import ImmediateSpeechBackend, emit_result

import json
import os
import tempfile

from asurada.audio_io import AudioFormat
from asurada.models import DriverState, SessionState, StrategyDecision, StrategyMessage, TyreState
from asurada.output import ConsoleVoiceOutput
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


def _make_state(
    *,
    lap_distance_m: float,
    speed_kph: float = 290.0,
    weather: str = "LightCloud",
    tyre_wear_pct: float = 18.0,
    surface_temps: list[int] | None = None,
    inner_temps: list[int] | None = None,
    tyre_damage_pct: float | None = None,
    aero_damage_pct: int | None = None,
    fuel_laps_remaining: float = 10.0,
    compound: str = "Medium",
) -> SessionState:
    tyre = TyreState(
        compound=compound,
        wear_pct=tyre_wear_pct,
        age_laps=8,
        surface_temperature_c=list(surface_temps or []),
        inner_temperature_c=list(inner_temps or []),
    )
    player = DriverState(
        car_index=0,
        name="Leclerc",
        position=3,
        lap=12,
        gap_ahead_s=0.7,
        gap_behind_s=1.0,
        fuel_laps_remaining=fuel_laps_remaining,
        ers_pct=62.0,
        drs_available=True,
        tyre=tyre,
        speed_kph=speed_kph,
        lap_distance_m=lap_distance_m,
        tyre_damage_pct=tyre_damage_pct,
        aero_damage_pct=aero_damage_pct,
    )
    return SessionState(
        session_uid="session-brake-assist",
        track="Shanghai",
        lap_number=12,
        total_laps=56,
        weather=weather,
        safety_car="NONE",
        player=player,
        rivals=[],
        source_timestamp_ms=1_777_500_000_000,
        raw={
            "frame_identifier": 420,
            "overall_frame_identifier": 1420,
            "session_time_s": 900.0,
            "source_timestamp_ms": 1_777_500_000_000,
            "lap_distance_m": lap_distance_m,
            "track_length_m": 5438.675,
        },
    )


def _make_turn(turn_id: str, transcript_text: str) -> VoiceTurn:
    return VoiceTurn(
        turn_id=turn_id,
        started_at_ms=1_777_500_000_100,
        ended_at_ms=1_777_500_000_400,
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
                "interaction_session_id": "runtime:session-brake-assist",
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


def _reminder_to_dict(reminder: object | None) -> dict[str, object] | None:
    if reminder is None:
        return None
    target = getattr(reminder, "target", None)
    return {
        "speak_text": getattr(reminder, "speak_text", None),
        "action_code": getattr(reminder, "action_code", None),
        "countdown_value": getattr(reminder, "countdown_value", None),
        "target": (None if target is None else target.to_dict()),
    }


def run_phase3_voice_brake_point_assist_regression() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="asurada-brake-assist-") as temp_dir:
        state_path = os.path.join(temp_dir, "brake_point_assist_state.json")
        previous_state_path = os.environ.get("ASURADA_BRAKE_POINT_ASSIST_STATE_PATH")
        os.environ["ASURADA_BRAKE_POINT_ASSIST_STATE_PATH"] = state_path
        try:
            coordinator = VoiceInputCoordinator()
            arm_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            countdown_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            arm_state = _make_state(lap_distance_m=3500.0)
            arm_result = coordinator.process_completed_turn(
                state=arm_state,
                turn=_make_turn("voice-turn:arm-brake", "下个长直道帮我注意刹车点"),
                voice_output=arm_output,
                primary_message=None,
                render=False,
            )
            arm_variant_result = coordinator.process_completed_turn(
                state=arm_state,
                turn=_make_turn("voice-turn:arm-brake-variant", "下个长直道提醒我注意刹车"),
                voice_output=arm_output,
                primary_message=None,
                render=False,
            )
            arm_loose_variant_result = coordinator.process_completed_turn(
                state=arm_state,
                turn=_make_turn("voice-turn:arm-brake-loose-variant", "下个长直道提醒我注意"),
                voice_output=arm_output,
                primary_message=None,
                render=False,
            )
            tune_earlier_result = coordinator.process_completed_turn(
                state=arm_state,
                turn=_make_turn("voice-turn:brake-earlier", "刹车点提醒提前一点"),
                voice_output=arm_output,
                primary_message=None,
                render=False,
            )
            tune_later_result = coordinator.process_completed_turn(
                state=arm_state,
                turn=_make_turn("voice-turn:brake-later", "刹车点提醒晚一点"),
                voice_output=arm_output,
                primary_message=None,
                render=False,
            )

            shared_snapshot_after_arm = countdown_output._brake_point_assist.snapshot()
            countdown_three_debug = countdown_output.emit(_make_decision(), state=_make_state(lap_distance_m=4385.0), render=False)
            countdown_two_debug = countdown_output.emit(_make_decision(), state=_make_state(lap_distance_m=4465.0), render=False)
            countdown_one_debug = countdown_output.emit(_make_decision(), state=_make_state(lap_distance_m=4545.0), render=False)
            countdown_three_event = countdown_three_debug.get("event", {}) or {}
            countdown_two_event = countdown_two_debug.get("event", {}) or {}
            countdown_one_event = countdown_one_debug.get("event", {}) or {}
            assist_state_after_countdown = countdown_output._brake_point_assist.snapshot()

            adaptive_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            adaptive_output._brake_point_assist.arm_next_long_straight(state=arm_state)
            adaptive_dry_reminder = adaptive_output._brake_point_assist.maybe_build_reminder(
                state=_make_state(
                    lap_distance_m=4348.0,
                    speed_kph=290.0,
                    weather="LightCloud",
                    tyre_wear_pct=18.0,
                    surface_temps=[92, 93, 90, 91],
                    inner_temps=[88, 89, 87, 88],
                    tyre_damage_pct=4.0,
                    aero_damage_pct=0,
                    fuel_laps_remaining=8.0,
                )
            )
            adaptive_dry_snapshot = adaptive_output._brake_point_assist.snapshot()
            adaptive_wet_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            adaptive_wet_output._brake_point_assist.arm_next_long_straight(state=arm_state)
            adaptive_wet_reminder = adaptive_wet_output._brake_point_assist.maybe_build_reminder(
                state=_make_state(
                    lap_distance_m=4348.0,
                    speed_kph=290.0,
                    weather="Wet",
                    tyre_wear_pct=62.0,
                    surface_temps=[111, 110, 108, 109],
                    inner_temps=[106, 105, 103, 104],
                    tyre_damage_pct=28.0,
                    aero_damage_pct=24,
                    fuel_laps_remaining=26.0,
                )
            )
            adaptive_wet_snapshot = adaptive_wet_output._brake_point_assist.snapshot()

            compound_soft_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            compound_soft_output._brake_point_assist.arm_next_long_straight(state=arm_state)
            compound_soft_reminder = compound_soft_output._brake_point_assist.maybe_build_reminder(
                state=_make_state(
                    lap_distance_m=4348.0,
                    speed_kph=290.0,
                    weather="LightCloud",
                    compound="Soft",
                    tyre_wear_pct=22.0,
                    surface_temps=[95, 95, 94, 94],
                    inner_temps=[90, 90, 89, 89],
                    tyre_damage_pct=0.0,
                    aero_damage_pct=0,
                    fuel_laps_remaining=8.0,
                )
            )
            compound_soft_snapshot = compound_soft_output._brake_point_assist.snapshot()
            compound_wet_output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
            compound_wet_output._brake_point_assist.arm_next_long_straight(state=arm_state)
            compound_wet_reminder = compound_wet_output._brake_point_assist.maybe_build_reminder(
                state=_make_state(
                    lap_distance_m=4348.0,
                    speed_kph=290.0,
                    weather="LightCloud",
                    compound="Wet",
                    tyre_wear_pct=22.0,
                    surface_temps=[95, 95, 94, 94],
                    inner_temps=[90, 90, 89, 89],
                    tyre_damage_pct=0.0,
                    aero_damage_pct=0,
                    fuel_laps_remaining=8.0,
                )
            )
            compound_wet_snapshot = compound_wet_output._brake_point_assist.snapshot()
        finally:
            if previous_state_path is None:
                os.environ.pop("ASURADA_BRAKE_POINT_ASSIST_STATE_PATH", None)
            else:
                os.environ["ASURADA_BRAKE_POINT_ASSIST_STATE_PATH"] = previous_state_path

    checks = {
        "arm_control_executed": arm_result.status == "processed",
        "arm_query_kind": ((arm_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "arm_brake_point_assist",
        "arm_ack_text": "报三二一" in (((arm_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {}).get("speak_text") or ""),
        "arm_variant_query_kind": ((arm_variant_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "arm_brake_point_assist",
        "arm_loose_variant_query_kind": ((arm_loose_variant_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "arm_brake_point_assist",
        "tune_earlier_query_kind": ((tune_earlier_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "brake_point_assist_earlier",
        "tune_later_query_kind": ((tune_later_result.bundle or {}).get("structured_query") or {}).get("query_kind") == "brake_point_assist_later",
        "tune_earlier_ack_text": "提前一点" in ((((tune_earlier_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {}) or {}).get("speak_text") or ""),
        "tune_later_ack_text": "晚一点" in ((((tune_later_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {}) or {}).get("speak_text") or ""),
        "shared_state_persists_arm": shared_snapshot_after_arm.get("mode") == "armed",
        "countdown_three_fires": countdown_three_event.get("event_type") == "start" and countdown_three_event.get("action_code") == "BRAKE_POINT_ASSIST_3" and countdown_three_event.get("speak_text") == "三",
        "countdown_two_fires": countdown_two_event.get("event_type") == "start" and countdown_two_event.get("action_code") == "BRAKE_POINT_ASSIST_2" and countdown_two_event.get("speak_text") == "二",
        "countdown_one_fires": countdown_one_event.get("event_type") == "start" and countdown_one_event.get("action_code") == "BRAKE_POINT_ASSIST_1" and countdown_one_event.get("speak_text") == "一",
        "adaptive_dry_waits": adaptive_dry_reminder is None,
        "adaptive_wet_triggers_earlier": (adaptive_wet_reminder.action_code if adaptive_wet_reminder is not None else None) == "BRAKE_POINT_ASSIST_3",
        "adaptive_wet_offset_greater": float(adaptive_wet_snapshot.get("last_adaptive_offset_m") or 0.0) > float(adaptive_dry_snapshot.get("last_adaptive_offset_m") or 0.0),
        "compound_soft_waits": compound_soft_reminder is None,
        "compound_wet_triggers_earlier": (compound_wet_reminder.action_code if compound_wet_reminder is not None else None) == "BRAKE_POINT_ASSIST_3",
        "compound_wet_offset_greater": float(compound_wet_snapshot.get("last_adaptive_offset_m") or 0.0) > float(compound_soft_snapshot.get("last_adaptive_offset_m") or 0.0),
        "assist_disarms_after_countdown": assist_state_after_countdown.get("mode") == "off",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "arm_result": arm_result.to_dict(),
            "arm_variant_result": arm_variant_result.to_dict(),
            "arm_loose_variant_result": arm_loose_variant_result.to_dict(),
            "tune_earlier_result": tune_earlier_result.to_dict(),
            "tune_later_result": tune_later_result.to_dict(),
            "countdown_three_debug": countdown_three_debug,
            "countdown_two_debug": countdown_two_debug,
            "countdown_one_debug": countdown_one_debug,
            "assist_state_after_countdown": assist_state_after_countdown,
            "adaptive_dry_reminder": _reminder_to_dict(adaptive_dry_reminder),
            "adaptive_wet_reminder": _reminder_to_dict(adaptive_wet_reminder),
            "adaptive_dry_snapshot": adaptive_dry_snapshot,
            "adaptive_wet_snapshot": adaptive_wet_snapshot,
            "compound_soft_reminder": _reminder_to_dict(compound_soft_reminder),
            "compound_wet_reminder": _reminder_to_dict(compound_wet_reminder),
            "compound_soft_snapshot": compound_soft_snapshot,
            "compound_wet_snapshot": compound_wet_snapshot,
        },
    }


if __name__ == "__main__":
    emit_result(run_phase3_voice_brake_point_assist_regression())

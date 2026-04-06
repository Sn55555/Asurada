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
            "wing_damage_pct": {"front_left": 18, "front_right": 22, "rear": 4},
            "floor_damage_pct": 12,
            "diffuser_damage_pct": 9,
            "sidepod_damage_pct": 3,
            "gearbox_damage_pct": 4,
            "engine_damage_pct": 7,
            "engine_components_damage_pct": {},
            "engine_blown": False,
            "engine_seized": False,
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
    front_gap_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:front-gap", "前车多近"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    tyre_outlook_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:tyre-outlook", "未来几圈轮胎预计损耗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    damage_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:damage", "车损情况怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    damage_pit_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:damage-pit", "这车损要不要进站"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    front_wing_damage_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:front-wing-damage", "前翼坏了吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    floor_damage_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:floor-damage", "底板伤了多少"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    engine_damage_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:engine-damage", "发动机有损伤吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    drs_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:drs", "现在有DRS吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    front_rival_drs_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:front-rival-drs", "前车有没有DRS"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    rear_rival_drs_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:rear-rival-drs", "后车到DRS了吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    ers_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:ers", "ERS还有多少"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    race_control_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:race-control", "现在赛道状态怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    safety_car_followup_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:safety-car", "现在有安全车吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    track_incident_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:track-incident", "赛道出什么事儿了"),
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
    pit_penalty_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:pit-penalty", "这次进站要不要服刑"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    penalty_handling_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:penalty-handling", "这次处罚现在最好的处理方式是什么"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    overall_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:overall", "整体情况怎么样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    attack_defend_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:attack-defend", "现在该攻还是守"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    risk_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:risk", "现在最该注意什么"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    risk_severity_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:risk-severity", "那这个风险大吗"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    risk_timing_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:risk-timing", "这个风险多久会变严重"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    rear_pressure_relief_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:rear-pressure-relief", "后车压力会不会自己降下去"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    next_lap_focus_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:next-lap-focus", "下一圈该注意什么"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    pit_delay_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:pit-delay", "如果继续不进站会怎样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    pit_one_lap_delay_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:pit-one-lap-delay", "如果等一圈再进站会怎样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    tyre_mgmt_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:tyre-mgmt", "现在要不要保胎"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    fuel_mgmt_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:fuel-mgmt", "现在要不要省油"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    defend_projection_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:defend-projection", "如果我现在守住会怎样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    attack_projection_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:attack-projection", "如果我现在进攻会怎样"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    attack_defend_tradeoff_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:attack-defend-tradeoff", "现在守和攻哪个代价更低"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    front_followup_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:front-followup", "那前车呢"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )
    unsupported_result = coordinator.process_completed_turn(
        state=state,
        turn=_make_turn("voice-turn:unsupported", "这一圈大概会怎么发展"),
        voice_output=voice_output,
        primary_message=primary_message,
        render=False,
    )

    natural_event = ((natural_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    followup_event = ((followup_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    explain_event = ((explain_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})
    overall_event = ((overall_result.output_debug or {}).get("output_lifecycle") or {}).get("event", {})

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
        "front_gap_maps": front_gap_result.status == "spoken"
        and (front_gap_result.bundle or {}).get("structured_query", {}).get("query_kind") == "front_gap",
        "tyre_outlook_maps": tyre_outlook_result.status == "spoken"
        and (tyre_outlook_result.bundle or {}).get("structured_query", {}).get("query_kind") == "tyre_wear_outlook"
        and (
            "未来" in str((((tyre_outlook_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or "")
            or "接下来" in str((((tyre_outlook_result.output_debug or {}).get("output_lifecycle") or {}).get("event") or {}).get("speak_text") or "")
        ),
        "damage_status_maps": damage_result.status == "spoken"
        and (damage_result.bundle or {}).get("structured_query", {}).get("query_kind") == "damage_status",
        "damage_pit_maps": damage_pit_result.status == "spoken"
        and (damage_pit_result.bundle or {}).get("structured_query", {}).get("query_kind") == "damage_pit_advice",
        "front_wing_maps": front_wing_damage_result.status == "spoken"
        and (front_wing_damage_result.bundle or {}).get("structured_query", {}).get("query_kind") == "front_wing_damage_status",
        "floor_damage_maps": floor_damage_result.status == "spoken"
        and (floor_damage_result.bundle or {}).get("structured_query", {}).get("query_kind") == "floor_damage_status",
        "engine_damage_maps": engine_damage_result.status == "spoken"
        and (engine_damage_result.bundle or {}).get("structured_query", {}).get("query_kind") == "engine_damage_status",
        "drs_status_maps": drs_result.status == "spoken"
        and (drs_result.bundle or {}).get("structured_query", {}).get("query_kind") == "drs_status",
        "front_rival_drs_maps": front_rival_drs_result.status == "spoken"
        and (front_rival_drs_result.bundle or {}).get("structured_query", {}).get("query_kind") == "front_rival_drs_status",
        "rear_rival_drs_maps": rear_rival_drs_result.status == "spoken"
        and (rear_rival_drs_result.bundle or {}).get("structured_query", {}).get("query_kind") == "rear_rival_drs_status",
        "ers_status_maps": ers_result.status == "spoken"
        and (ers_result.bundle or {}).get("structured_query", {}).get("query_kind") == "ers_status",
        "race_control_status_maps": race_control_result.status == "spoken"
        and (race_control_result.bundle or {}).get("structured_query", {}).get("query_kind") == "race_control_status",
        "safety_car_followup_maps": safety_car_followup_result.status == "spoken"
        and (safety_car_followup_result.bundle or {}).get("structured_query", {}).get("query_kind") == "race_control_status",
        "track_incident_maps": track_incident_result.status == "spoken"
        and (track_incident_result.bundle or {}).get("structured_query", {}).get("query_kind") == "race_control_status",
        "penalty_status_maps": penalty_result.status == "spoken"
        and (penalty_result.bundle or {}).get("structured_query", {}).get("query_kind") == "penalty_status",
        "pit_penalty_maps": pit_penalty_result.status == "spoken"
        and (pit_penalty_result.bundle or {}).get("structured_query", {}).get("query_kind") == "pit_penalty_plan",
        "penalty_handling_maps": penalty_handling_result.status == "spoken"
        and (penalty_handling_result.bundle or {}).get("structured_query", {}).get("query_kind") == "penalty_handling_strategy",
        "overall_situation_maps": overall_result.status == "spoken"
        and (overall_result.bundle or {}).get("structured_query", {}).get("query_kind") == "overall_situation",
        "overall_situation_is_conclusion_first": "当前整体" in str(overall_event.get("speak_text") or "")
        and "最大风险" in str(overall_event.get("speak_text") or "")
        and (
            "下一步优先" in str(overall_event.get("speak_text") or "")
            or "下一步先" in str(overall_event.get("speak_text") or "")
        ),
        "attack_or_defend_maps": attack_defend_result.status == "spoken"
        and (attack_defend_result.bundle or {}).get("structured_query", {}).get("query_kind") == "attack_or_defend_summary",
        "main_risk_maps": risk_result.status == "spoken"
        and (risk_result.bundle or {}).get("structured_query", {}).get("query_kind") == "main_risk_summary",
        "risk_severity_maps": risk_severity_result.status == "spoken"
        and (risk_severity_result.bundle or {}).get("structured_query", {}).get("query_kind") == "risk_severity_followup",
        "risk_timing_maps": risk_timing_result.status == "spoken"
        and (risk_timing_result.bundle or {}).get("structured_query", {}).get("query_kind") == "risk_escalation_timing",
        "rear_pressure_relief_maps": rear_pressure_relief_result.status == "spoken"
        and (rear_pressure_relief_result.bundle or {}).get("structured_query", {}).get("query_kind") == "rear_pressure_relief_outlook",
        "next_lap_focus_maps": next_lap_focus_result.status == "spoken"
        and (next_lap_focus_result.bundle or {}).get("structured_query", {}).get("query_kind") == "next_lap_focus",
        "pit_delay_maps": pit_delay_result.status == "spoken"
        and (pit_delay_result.bundle or {}).get("structured_query", {}).get("query_kind") == "pit_delay_consequence",
        "pit_one_lap_delay_maps": pit_one_lap_delay_result.status == "spoken"
        and (pit_one_lap_delay_result.bundle or {}).get("structured_query", {}).get("query_kind") == "pit_one_lap_delay_consequence",
        "tyre_mgmt_maps": tyre_mgmt_result.status == "spoken"
        and (tyre_mgmt_result.bundle or {}).get("structured_query", {}).get("query_kind") == "tyre_management_advice",
        "fuel_mgmt_maps": fuel_mgmt_result.status == "spoken"
        and (fuel_mgmt_result.bundle or {}).get("structured_query", {}).get("query_kind") == "fuel_management_advice",
        "defend_projection_maps": defend_projection_result.status == "spoken"
        and (defend_projection_result.bundle or {}).get("structured_query", {}).get("query_kind") == "defend_outcome_projection",
        "attack_projection_maps": attack_projection_result.status == "spoken"
        and (attack_projection_result.bundle or {}).get("structured_query", {}).get("query_kind") == "attack_outcome_projection",
        "attack_defend_tradeoff_maps": attack_defend_tradeoff_result.status == "spoken"
        and (attack_defend_tradeoff_result.bundle or {}).get("structured_query", {}).get("query_kind") == "attack_defend_tradeoff",
        "front_followup_maps": front_followup_result.status == "spoken"
        and (front_followup_result.bundle or {}).get("structured_query", {}).get("query_kind") == "front_gap",
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
            "front_gap_result": front_gap_result.to_dict(),
            "tyre_outlook_result": tyre_outlook_result.to_dict(),
            "damage_result": damage_result.to_dict(),
            "damage_pit_result": damage_pit_result.to_dict(),
            "front_wing_damage_result": front_wing_damage_result.to_dict(),
            "floor_damage_result": floor_damage_result.to_dict(),
            "engine_damage_result": engine_damage_result.to_dict(),
            "drs_result": drs_result.to_dict(),
            "front_rival_drs_result": front_rival_drs_result.to_dict(),
            "rear_rival_drs_result": rear_rival_drs_result.to_dict(),
            "ers_result": ers_result.to_dict(),
            "race_control_result": race_control_result.to_dict(),
            "safety_car_followup_result": safety_car_followup_result.to_dict(),
            "track_incident_result": track_incident_result.to_dict(),
            "penalty_result": penalty_result.to_dict(),
            "pit_penalty_result": pit_penalty_result.to_dict(),
            "penalty_handling_result": penalty_handling_result.to_dict(),
            "overall_result": overall_result.to_dict(),
            "attack_defend_result": attack_defend_result.to_dict(),
            "risk_result": risk_result.to_dict(),
            "risk_severity_result": risk_severity_result.to_dict(),
            "risk_timing_result": risk_timing_result.to_dict(),
            "rear_pressure_relief_result": rear_pressure_relief_result.to_dict(),
            "next_lap_focus_result": next_lap_focus_result.to_dict(),
            "pit_delay_result": pit_delay_result.to_dict(),
            "pit_one_lap_delay_result": pit_one_lap_delay_result.to_dict(),
            "tyre_mgmt_result": tyre_mgmt_result.to_dict(),
            "fuel_mgmt_result": fuel_mgmt_result.to_dict(),
            "defend_projection_result": defend_projection_result.to_dict(),
            "attack_projection_result": attack_projection_result.to_dict(),
            "attack_defend_tradeoff_result": attack_defend_tradeoff_result.to_dict(),
            "front_followup_result": front_followup_result.to_dict(),
            "unsupported_result": unsupported_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_semantic_voice_regression(), ensure_ascii=False, indent=2))

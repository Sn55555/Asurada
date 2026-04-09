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


def _make_turn(*, transcript_text: str, transcript_hint: str | None = None) -> VoiceTurn:
    metadata = {"transcript_text": transcript_text}
    if transcript_hint is not None:
        metadata["transcript_hint"] = transcript_hint
    return VoiceTurn(
        turn_id="voice-turn:test",
        started_at_ms=1_777_000_000_100,
        ended_at_ms=1_777_000_000_420,
        audio_format=AudioFormat(),
        pcm_s16le=b"\x00\x00" * 3200,
        chunk_count=8,
        source="ptt",
        completion_reason="vad_speech_end",
        metadata=metadata,
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

    front_gap_turn = _make_turn(transcript_text="前车差距")
    front_gap_result = recognizer.recognize_turn(front_gap_turn)

    tyre_outlook_turn = _make_turn(transcript_text="未来几圈轮胎预计损耗")
    tyre_outlook_result = recognizer.recognize_turn(tyre_outlook_turn)

    damage_turn = _make_turn(transcript_text="车损情况怎么样")
    damage_result = recognizer.recognize_turn(damage_turn)

    damage_pit_turn = _make_turn(transcript_text="这车损要不要进站")
    damage_pit_result = recognizer.recognize_turn(damage_pit_turn)

    front_wing_turn = _make_turn(transcript_text="前翼坏了吗")
    front_wing_result = recognizer.recognize_turn(front_wing_turn)

    floor_damage_turn = _make_turn(transcript_text="底板伤了多少")
    floor_damage_result = recognizer.recognize_turn(floor_damage_turn)

    engine_damage_turn = _make_turn(transcript_text="发动机有损伤吗")
    engine_damage_result = recognizer.recognize_turn(engine_damage_turn)

    drs_turn = _make_turn(transcript_text="现在有DRS吗")
    drs_result = recognizer.recognize_turn(drs_turn)

    track_incident_turn = _make_turn(transcript_text="赛道出什么事儿了")
    track_incident_result = recognizer.recognize_turn(track_incident_turn)

    pit_penalty_turn = _make_turn(transcript_text="这次进站要不要服刑")
    pit_penalty_result = recognizer.recognize_turn(pit_penalty_turn)

    front_rival_drs_turn = _make_turn(transcript_text="前车有没有DRS")
    front_rival_drs_result = recognizer.recognize_turn(front_rival_drs_turn)

    rear_rival_drs_turn = _make_turn(transcript_text="后车到DRS了吗")
    rear_rival_drs_result = recognizer.recognize_turn(rear_rival_drs_turn)

    penalty_handling_turn = _make_turn(transcript_text="这次处罚现在最好的处理方式是什么")
    penalty_handling_result = recognizer.recognize_turn(penalty_handling_turn)

    main_risk_turn = _make_turn(transcript_text="现在最该注意什么")
    main_risk_result = recognizer.recognize_turn(main_risk_turn)

    next_lap_focus_turn = _make_turn(transcript_text="下一圈该注意什么")
    next_lap_focus_result = recognizer.recognize_turn(next_lap_focus_turn)

    risk_severity_turn = _make_turn(transcript_text="那这个风险大吗")
    risk_severity_result = recognizer.recognize_turn(risk_severity_turn)

    risk_timing_turn = _make_turn(transcript_text="这个风险多久会变严重")
    risk_timing_result = recognizer.recognize_turn(risk_timing_turn)

    rear_pressure_relief_turn = _make_turn(transcript_text="后车压力会不会自己降下去")
    rear_pressure_relief_result = recognizer.recognize_turn(rear_pressure_relief_turn)

    pit_delay_turn = _make_turn(transcript_text="如果继续不进站会怎样")
    pit_delay_result = recognizer.recognize_turn(pit_delay_turn)

    pit_one_lap_delay_turn = _make_turn(transcript_text="如果等一圈再进站会怎样")
    pit_one_lap_delay_result = recognizer.recognize_turn(pit_one_lap_delay_turn)

    tyre_mgmt_turn = _make_turn(transcript_text="现在要不要保胎")
    tyre_mgmt_result = recognizer.recognize_turn(tyre_mgmt_turn)

    fuel_mgmt_turn = _make_turn(transcript_text="现在要不要省油")
    fuel_mgmt_result = recognizer.recognize_turn(fuel_mgmt_turn)

    defend_projection_turn = _make_turn(transcript_text="如果我现在守住会怎样")
    defend_projection_result = recognizer.recognize_turn(defend_projection_turn)

    attack_projection_turn = _make_turn(transcript_text="如果我现在进攻会怎样")
    attack_projection_result = recognizer.recognize_turn(attack_projection_turn)

    attack_defend_tradeoff_turn = _make_turn(transcript_text="现在守和攻哪个代价更低")
    attack_defend_tradeoff_result = recognizer.recognize_turn(attack_defend_tradeoff_turn)

    overall_turn = _make_turn(transcript_text="整体情况怎么样")
    overall_result = recognizer.recognize_turn(overall_turn)

    cancel_turn = _make_turn(transcript_text="取消")
    cancel_result = recognizer.recognize_turn(cancel_turn)

    fallback_turn = _make_turn(transcript_text="帮我解释为什么刚才那圈不进站")
    fallback_result = recognizer.recognize_turn(fallback_turn)

    partial_hint_turn = _make_turn(transcript_text="后车插句", transcript_hint="后车差距")
    partial_hint_result = recognizer.recognize_turn(partial_hint_turn)

    checks = {
        "rear_gap_matches": rear_gap_result.query_kind == "rear_gap" and rear_gap_result.status == "matched",
        "rear_gap_bundle_routes": rear_gap_bundle.structured_query["query_kind"] == "rear_gap"
        and rear_gap_bundle.query_route["handler"] == "rear_gap_snapshot_handler",
        "front_gap_matches": front_gap_result.query_kind == "front_gap" and front_gap_result.status == "matched",
        "tyre_outlook_matches": tyre_outlook_result.query_kind == "tyre_wear_outlook" and tyre_outlook_result.status == "matched",
        "damage_matches": damage_result.query_kind == "damage_status" and damage_result.status == "matched",
        "damage_pit_matches": damage_pit_result.query_kind == "damage_pit_advice" and damage_pit_result.status == "matched",
        "front_wing_matches": front_wing_result.query_kind == "front_wing_damage_status" and front_wing_result.status == "matched",
        "floor_damage_matches": floor_damage_result.query_kind == "floor_damage_status" and floor_damage_result.status == "matched",
        "engine_damage_matches": engine_damage_result.query_kind == "engine_damage_status" and engine_damage_result.status == "matched",
        "drs_matches": drs_result.query_kind == "drs_status" and drs_result.status == "matched",
        "track_incident_matches": track_incident_result.query_kind == "race_control_status" and track_incident_result.status == "matched",
        "pit_penalty_matches": pit_penalty_result.query_kind == "pit_penalty_plan" and pit_penalty_result.status == "matched",
        "front_rival_drs_matches": front_rival_drs_result.query_kind == "front_rival_drs_status" and front_rival_drs_result.status == "matched",
        "rear_rival_drs_matches": rear_rival_drs_result.query_kind == "rear_rival_drs_status" and rear_rival_drs_result.status == "matched",
        "penalty_handling_matches": penalty_handling_result.query_kind == "penalty_handling_strategy" and penalty_handling_result.status == "matched",
        "main_risk_matches": main_risk_result.query_kind == "main_risk_summary" and main_risk_result.status == "matched",
        "next_lap_focus_matches": next_lap_focus_result.query_kind == "next_lap_focus" and next_lap_focus_result.status == "matched",
        "risk_severity_matches": risk_severity_result.query_kind == "risk_severity_followup" and risk_severity_result.status == "matched",
        "risk_timing_matches": risk_timing_result.query_kind == "risk_escalation_timing" and risk_timing_result.status == "matched",
        "rear_pressure_relief_matches": rear_pressure_relief_result.query_kind == "rear_pressure_relief_outlook" and rear_pressure_relief_result.status == "matched",
        "pit_delay_matches": pit_delay_result.query_kind == "pit_delay_consequence" and pit_delay_result.status == "matched",
        "pit_one_lap_delay_matches": pit_one_lap_delay_result.query_kind == "pit_one_lap_delay_consequence" and pit_one_lap_delay_result.status == "matched",
        "tyre_mgmt_matches": tyre_mgmt_result.query_kind == "tyre_management_advice" and tyre_mgmt_result.status == "matched",
        "fuel_mgmt_matches": fuel_mgmt_result.query_kind == "fuel_management_advice" and fuel_mgmt_result.status == "matched",
        "defend_projection_matches": defend_projection_result.query_kind == "defend_outcome_projection" and defend_projection_result.status == "matched",
        "attack_projection_matches": attack_projection_result.query_kind == "attack_outcome_projection" and attack_projection_result.status == "matched",
        "attack_defend_tradeoff_matches": attack_defend_tradeoff_result.query_kind == "attack_defend_tradeoff" and attack_defend_tradeoff_result.status == "matched",
        "overall_matches": overall_result.query_kind == "overall_situation" and overall_result.status == "matched",
        "asr_fast_input_type": rear_gap_bundle.input_event["input_type"] == "asr_fast_query",
        "cancel_maps_to_control_query": cancel_result.query_kind == "cancel",
        "fallback_unmatched": fallback_result.status == "fallback" and fallback_result.query_kind is None,
        "partial_hint_route_fallback": partial_hint_result.status == "matched"
        and partial_hint_result.query_kind == "rear_gap"
        and (partial_hint_result.metadata or {}).get("transcript_source") == "transcript_hint",
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "rear_gap_result": rear_gap_result.to_dict(),
            "front_gap_result": front_gap_result.to_dict(),
            "tyre_outlook_result": tyre_outlook_result.to_dict(),
            "damage_result": damage_result.to_dict(),
            "damage_pit_result": damage_pit_result.to_dict(),
            "front_wing_result": front_wing_result.to_dict(),
            "floor_damage_result": floor_damage_result.to_dict(),
            "engine_damage_result": engine_damage_result.to_dict(),
            "drs_result": drs_result.to_dict(),
            "track_incident_result": track_incident_result.to_dict(),
            "pit_penalty_result": pit_penalty_result.to_dict(),
            "front_rival_drs_result": front_rival_drs_result.to_dict(),
            "rear_rival_drs_result": rear_rival_drs_result.to_dict(),
            "penalty_handling_result": penalty_handling_result.to_dict(),
            "main_risk_result": main_risk_result.to_dict(),
            "next_lap_focus_result": next_lap_focus_result.to_dict(),
            "risk_severity_result": risk_severity_result.to_dict(),
            "risk_timing_result": risk_timing_result.to_dict(),
            "rear_pressure_relief_result": rear_pressure_relief_result.to_dict(),
            "pit_delay_result": pit_delay_result.to_dict(),
            "pit_one_lap_delay_result": pit_one_lap_delay_result.to_dict(),
            "tyre_mgmt_result": tyre_mgmt_result.to_dict(),
            "fuel_mgmt_result": fuel_mgmt_result.to_dict(),
            "defend_projection_result": defend_projection_result.to_dict(),
            "attack_projection_result": attack_projection_result.to_dict(),
            "attack_defend_tradeoff_result": attack_defend_tradeoff_result.to_dict(),
            "overall_result": overall_result.to_dict(),
            "rear_gap_bundle": rear_gap_bundle.to_dict(),
            "cancel_result": cancel_result.to_dict(),
            "fallback_result": fallback_result.to_dict(),
            "partial_hint_result": partial_hint_result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_fast_intent_regression(), ensure_ascii=False, indent=2))

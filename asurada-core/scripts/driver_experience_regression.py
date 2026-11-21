"""Compare a scoped brake reference and a radio preference via shared speech IPC."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from asurada.brake_habit import BrakeProbe, verified_reference
from asurada.config import StrategyThresholds
from asurada.driver_experience_profile import export_profile, rebuild_profile
from asurada.input_quality import marshal_zone_flag
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput
from asurada.snapshot_contract import snapshot_payload
from asurada.strategy import StrategyEngine
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.training_memory import TrainingMemory
from asurada.voice_input import VoiceInputCoordinator, _pit_feedback_provenance
from asurada.voice_interrupt import VoiceTurnInterruption
from personality_acceptance_regression import low_load_state
from phase3_voice_input_regression import _make_turn
from phase3_voice_regression import FakeSpeechBackend
from regression_support import emit_result

ENGINE = StrategyEngine(StrategyThresholds())


def frame(uid, lap, position, elapsed, *, brake=0, flag=1, front=3, stage=1, wall_ms=None):
    state = low_load_state(stage=stage, kind=None)
    state.session_uid, state.track, state.lap_number = uid, "Suzuka", lap
    state.player.lap = lap
    state.player.lap_distance_m = position
    state.player.gap_ahead_s = front
    stamp = wall_ms if wall_ms is not None else 1_800_000_000_000 + int(elapsed * 1000)
    state.source_timestamp_ms = stamp
    state.raw.update(session_time_s=elapsed, brake=brake, pit_status="NONE", num_pit_stops=0, marshal_zone_flag=flag,
                     tyres_wear_pct=[state.player.tyre.wear_pct] * 4,
                     input_quality={"brake": {"quality": "observed", "source": "CarTelemetry", "observed_at_ms": stamp}})
    ENGINE.evaluate(state)
    state.personality = replace(state.personality, session_uid=uid, source_timestamp_ms=stamp,
                                snapshot_id=state.assessment.snapshot_id, clock_s=elapsed, low_load=brake < .13 and front >= 2)
    return state


def pass_frames(uid, lap, elapsed, onset, **kwargs):
    return [frame(uid, lap, position, elapsed + i * .1, brake=.45 if position >= onset else 0, **kwargs)
            for i, position in enumerate(range(70, 161, 10))]


def extract_reference():
    probe = BrakeProbe()
    passes = []
    for run in range(3):
        for lap in range(2, 5):
            for state in pass_frames(f"training-{run}", lap, 100 * (run + 1) + lap * 2, 130):
                if item := probe.observe(state):
                    passes.append(item)
    return verified_reference(passes)


def utter(client, state, text):
    with VoiceTurnInterruption(client) as interruption:
        context = interruption.begin()
        result = VoiceInputCoordinator().process_completed_turn(
            state=state, turn=_make_turn(text), voice_output=interruption.output_for(context),
            render=False, context=context)
    assert result.status == "processed", result
    return result.output_debug["radio_experience"]


def preference_case(client, output, backend, *, cancel=None):
    at_bend = frame("query", 2, 160, 300)
    utter(client, at_bend, "取消直道解释")
    immediate = client.emit_query_response(state=at_bend, query_kind="why_not_pit", render=False)
    backend.complete_all()
    output.tick()
    utter(client, at_bend, "长解释留到直道")
    deferred = client.emit_query_response(state=at_bend, query_kind="why_not_pit", render=False)
    backend.complete_all()
    output.tick()
    if cancel == "revoked":
        utter(client, at_bend, "取消直道解释")
    if cancel == "high_load":
        straight = frame("query", 2, 950, 302, front=.5)
    else:
        straight = frame("query", 2, 950, 320 if cancel == "expired" else 302)
    reply = client.emit(StrategyDecision([], record=straight.decision_record), state=straight, render=False)["event"]
    backend.complete_all()
    output.tick()
    return {
        "before": immediate["output_lifecycle"]["event"]["speak_text"],
        "candidate": deferred["output_lifecycle"]["event"]["speak_text"],
        "at_straight": reply["speak_text"],
        "code": reply["action_code"],
    }


def habit_case(client, output, backend, *, identifier, flag=1, front=3):
    for state in pass_frames(identifier, 2, 600., 90, flag=flag, front=front):
        client.emit(StrategyDecision([], record=state.decision_record), state=state, render=False)
    exit_frame = frame(identifier, 2, 260, 602.5, flag=flag, front=front)
    reply = client.emit(StrategyDecision([], record=exit_frame.decision_record), state=exit_frame, render=False)["event"]
    backend.complete_all()
    output.tick()
    return reply


def authority_case(directory):
    location = directory / "authority.json"
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    service = SpeechService(directory / "authority.sock", output=output, session_source=location)

    def publish(distance, elapsed):
        state = frame("authoritative", 2, distance, elapsed, wall_ms=int(time.time() * 1000))
        record = state.decision_record
        decision = StrategyDecision(list(record.actions), record=record,
                                    debug={"arbiter_v2": {"output": dict(record.arbitration)}})
        staged = location.with_suffix(".temp")
        staged.write_text(json.dumps(snapshot_payload(state, decision), ensure_ascii=False))
        staged.replace(location)
        return state, decision

    try:
        service.start()
        client = SharedSpeechClient(service.path)
        bend, _ = publish(160, 401)
        assert client.set_radio_preference(True)["status"] == "applied"
        result = client.emit_query_response(state=bend, query_kind="why_not_pit", render=False)
        backend.complete_all()
        output.tick()
        straight, decision = publish(950, 403)
        after = client.emit(decision, state=straight, render=False)["event"]
        backend.complete_all()
        output.tick()
        return result["output_lifecycle"]["event"]["event_type"] == "start" and after["action_code"] == "PERSONALITY_DEFERRED_REASON"
    finally:
        service.close()


def run(destination):
    reference = extract_reference()
    assert reference is not None
    with TemporaryDirectory(dir="/tmp") as dirname:
        directory = Path(dirname)
        database = directory / "training.sqlite"
        memory = TrainingMemory(database)
        memory.put_brake_habit(driver="fixture-car", track=reference["track"], corner=reference["corner"], record=reference)
        with patch.dict(os.environ, ASURADA_PERSONALITY_ENABLED="1", ASURADA_DRIVER_ID="fixture-car",
                        ASURADA_TRAINING_MEMORY_DB=str(database)):
            backend = FakeSpeechBackend()
            output = ConsoleVoiceOutput(backend=backend)
            service = SpeechService(directory / "speech.sock", output=output)
            try:
                service.start()
                client = SharedSpeechClient(service.path)
                preference = preference_case(client, output, backend)
                expired = preference_case(client, output, backend, cancel="expired")
                crowded = preference_case(client, output, backend, cancel="high_load")
                revoked = preference_case(client, output, backend, cancel="revoked")
                normal = habit_case(client, output, backend, identifier="observed")
                yellow = habit_case(client, output, backend, identifier="yellow", flag=3)
                traffic = habit_case(client, output, backend, identifier="traffic", front=1)
                # Create a new completed mention, then correct exactly that evidence through voice IPC.
                again = habit_case(client, output, backend, identifier="observed-again")
                correction = utter(client, frame("observed-again", 2, 260, 603.), "那几圈是在跟车")
                after = habit_case(client, output, backend, identifier="corrected")
            finally:
                service.close()

            bundle = export_profile(memory, "fixture-car")
            restored = TrainingMemory(directory / "rebuilt.sqlite")
            rebuild_profile(restored, "fixture-car", bundle)
            resumed = restored.put_brake_habit(driver="fixture-car", track=reference["track"],
                                               corner=reference["corner"], record=reference)
            train_scope = restored.brake_habits(driver="other-driver")
            with patch.dict(os.environ, ASURADA_DRIVER_ID="other-driver"):
                blank_backend = FakeSpeechBackend()
                blank_output = ConsoleVoiceOutput(backend=blank_backend)
                blank_service = SpeechService(directory / "blank.sock", output=blank_output)
                try:
                    blank_service.start()
                    blank = habit_case(SharedSpeechClient(blank_service.path), blank_output, blank_backend, identifier="observed")
                finally:
                    blank_service.close()
            turn = replace(_make_turn("同意进站"), metadata={"transcript_text": "同意进站", "transcript_hint": "我不进站"})
            low_choice = replace(turn, metadata={"transcript_text": "同意进站", "asr_confidence": .5})
            checks = {
                "one_modelled_corner_two_training_runs_holdout": len(reference["training"]) == 6 and len(reference["holdout"]) == 3,
                "reason_moves_to_low_load_straight": "继续对照" in preference["before"]
                    and "继续对照" not in preference["candidate"] and preference["code"] == "PERSONALITY_DEFERRED_REASON"
                    and "继续对照" in preference["at_straight"],
                "expired_crowded_and_revoked_never_delivered": all(item["code"] != "PERSONALITY_DEFERRED_REASON"
                                                                   for item in (expired, crowded, revoked)),
                "h1_valid_habit_speaks_after_braking": normal["action_code"] == again["action_code"] == "PERSONALITY_BRAKE_HABIT",
                "yellow_traffic_and_corrected_silent": all(item["action_code"] != "PERSONALITY_BRAKE_HABIT"
                                                            for item in (yellow, traffic, after)),
                "tombstone_survives_rebuild": correction["status"] == "applied" and not resumed
                    and not restored.brake_habits(driver="fixture-car")
                    and restored.brake_habits(driver="fixture-car", include_revoked=True)[0]["record"] == reference,
                "other_driver_has_no_private_evidence": not train_scope and not blank["speak_text"],
                "conflicting_audio_retains_no_response": _pit_feedback_provenance(turn, "accept") == "pit_feedback_hypotheses_conflict"
                    and _pit_feedback_provenance(low_choice, "accept") == "pit_feedback_asr_not_confident",
                "marshal_zone_wraps_using_official_zone_fraction": marshal_zone_flag(
                    [{"zone_start": .1, "zone_flag": 1}, {"zone_start": .9, "zone_flag": 3}], 10, 1000) == 3,
                "deferred_reason_revalidated_on_authoritative_live_entry": authority_case(directory),
            }
            report = {
                "passed": all(checks.values()), "checks": checks,
                "scope": "shared IPC and simulated telemetry; fake audio backend",
                "same_query_preference_comparison": preference,
                "same_corner_profile_comparison": {"with_reference": normal["speak_text"],
                                                    "blank_profile_same_input": blank["speak_text"],
                                                    "after_correction": after["speak_text"]},
                "training_reference": reference,
            }
            if destination:
                destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    emit_result(run(args.output))

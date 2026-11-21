"""Replay pit advice, explicit voice turns, and authoritative tyre observations."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from asurada.config import StrategyThresholds
from asurada.contributor_admission import ContributorPolicy, SCORING_FIELDS
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.output import ConsoleVoiceOutput
from asurada.personality_runtime import PersonalityRuntime
from asurada.pit_feedback import PitEvidenceStore, PitFeedbackTracker, load_history
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.strategy import StrategyEngine
from asurada.voice_input import VoiceInputCoordinator
from personality_pit_advice_regression import make_frame, NORMAL, WORN
from phase3_voice_input_regression import _make_turn
from phase3_voice_regression import FakeSpeechBackend
from regression_support import emit_result


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for authoritative evidence")
        time.sleep(.015)


def run_case(folder, *, feedback=(), action="tyre_change", complete=True):
    folder.mkdir()
    db_path = folder / "evidence.sqlite3"
    latest = folder / "latest.json"
    store = PitEvidenceStore(db_path)
    tracker = PitFeedbackTracker(store)
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend, pit_feedback=tracker)
    engine = StrategyEngine(StrategyThresholds(),
        model_policy=ModelAdmissionPolicy(modes=dict.fromkeys(MODEL_NAMES, "disabled")),
        contributor_policy=ContributorPolicy(modes=dict.fromkeys(SCORING_FIELDS, "disabled")))
    personality = PersonalityRuntime()
    input_coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    service = SpeechService(folder / "voice.sock", output=output, session_source=latest).start()
    replies = []
    try:
        client = SharedSpeechClient(service.path)

        def publish(row, *, submit_audio=False, epoch=0, result=2):
            state = make_frame(row)
            state.session_epoch = epoch
            state.session_epoch_explicit = True
            state.raw["result_status"] = result
            state.source_timestamp_ms = int(time.time() * 1000)
            decision = engine.evaluate(state)
            state.decision_record = decision.record
            state.personality = personality.observe_snapshot(state, decision)
            staging = folder / "latest.tmp"
            staging.write_text(json.dumps(snapshot_payload(state, decision)), encoding="utf-8")
            staging.replace(latest)
            if submit_audio:
                event = client.emit(decision, state=state, render=False)["event"]
                assert event["action_code"] == "BOX_WINDOW" and event["event_type"] == "start", event
                assert event["metadata"]["pit_recommendation_id"] == tracker.record["recommendation_id"]
            else:
                wait_for(lambda: not tracker.active or tracker.last_source_ms == state.source_timestamp_ms)
            return state

        state = publish((10, WORN, 4, 14, 0, 0), submit_audio=True)
        if complete:
            backend.complete_all()
            output.tick()
        for text, token in feedback:
            result = input_coordinator.process_completed_turn(
                state=state, turn=replace(_make_turn(text), turn_id=token), voice_output=client, render=False)
            replies.append({"status": result.status, "reason": result.reason,
                            "details": (result.output_debug or {}).get("pit_feedback")})
        if action == "rewind":
            publish((9, WORN, 4, 14, 0, 0), epoch=1)
        elif action == "no_action":
            publish((14, WORN, 4, 14, 0, 0), result=3)
        elif action == "withdrawn_then_pit":
            for second in (12, 13, 14):
                publish((second, NORMAL, 4, 14, 0, 0))
            publish((17, NORMAL, 4, 14, 1, 0))
            publish((19, NORMAL, 8, 0, 0, 1))
        else:
            publish((13, WORN, 4, 14, 1, 0))
            if action == "pit_only":
                publish((14, WORN, 4, 14, 0, 1))
                publish((16, WORN, 4, 14, 0, 1))
                publish((18, WORN, 4, 14, 0, 1), result=3)
            else:
                for second in (14, 15, 16):
                    publish((second, NORMAL, 8, 0, 0, 1))
                if action == "late_reply":
                    state = publish((17, NORMAL, 8, 0, 0, 1))
                    replies.append(client.record_pit_feedback(state=state, text="同意进站", request_id="too-late"))
        health = client.health()["pit_evidence"]
        assert health["failures"] == 0 and health["dropped"] == 0
    finally:
        assert service.close()
        assert store.close()
    records = load_history(db_path)
    assert len(records) == 1
    return {"feedback_responses": replies, "record": records[0]}


def run():
    with TemporaryDirectory(prefix="asurada-pit-feedback-", dir="/tmp") as directory, patch.dict(
            os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        root = Path(directory)
        scenarios = {
            "accept_and_change": run_case(root/"accept", feedback=(("同意进站", "yes"), ("同意进站", "yes"))),
            "silent_and_change": run_case(root/"silent"),
            "decline_and_change": run_case(root/"decline", feedback=(("同意进站", "yes"), ("我不进站", "no"))),
            "accept_without_action": run_case(root/"no-action", feedback=(("同意进站", "yes"),), action="no_action"),
            "accept_pit_without_change": run_case(root/"pit-only", feedback=(("同意进站", "yes"),), action="pit_only"),
            "sound_not_completed": run_case(root/"partial", feedback=(("同意进站", "too-early"),), complete=False),
            "late_accept": run_case(root/"late", action="late_reply"),
            "rewind": run_case(root/"rewind", feedback=(("同意进站", "yes"),), action="rewind"),
            "withdrawn_then_pit": run_case(root/"withdrawn", feedback=(("同意进站", "yes"),), action="withdrawn_then_pit"),
        }
    records = {name: item["record"] for name, item in scenarios.items()}
    accepted = records["accept_and_change"]
    silent = records["silent_and_change"]
    refused = records["decline_and_change"]
    checks = {
        "spoken_advice_and_asr_feedback_join_by_recommendation_id": (
            accepted["playback"]["completed_at"] is not None and accepted["decision_id"] and accepted["snapshot_binding_id"]
            and all(reply["details"]["recommendation_id"] == accepted["recommendation_id"]
                    for reply in scenarios["accept_and_change"]["feedback_responses"])),
        "explicit_retry_is_idempotent": (
            len(accepted["feedback"]) == 1
            and scenarios["accept_and_change"]["feedback_responses"][1]["details"]["status"] == "already_recorded"),
        "accept_plus_pit_and_new_set_verifies_adoption": (
            accepted["adopted"] and accepted["telemetry"]["pit_status_code"] == 1
            and accepted["telemetry"]["tyre_change"]["reason"] == "fitted_set_changed"
            and accepted["outcome"]["wear_reduction_percentage_points"] == 63.0
            and accepted["outcome"]["wear_verdict_after"] == "stable"),
        "silence_is_never_adoption_even_if_pit_and_replacement_are_observed": (
            not silent["adopted"] and silent["feedback"] == []
            and silent["end_reason"] == "tyre_change_verified"),
        "last_explicit_decline_is_not_adoption": (
            not refused["adopted"] and [event["choice"] for event in refused["feedback"]] == ["accept", "decline"]
            and refused["outcome"]["wear_after_pct"] == 15.5),
        "acceptance_alone_is_not_adoption": (
            not records["accept_without_action"]["adopted"] and records["accept_without_action"]["outcome"] is None),
        "pit_without_change_is_not_adoption": (
            records["accept_pit_without_change"]["telemetry"]["pit_observed"]
            and not records["accept_pit_without_change"]["adopted"]),
        "interrupted_playback_cannot_create_acceptance": (
            records["sound_not_completed"]["playback"]["completed_at"] is None
            and not records["sound_not_completed"]["feedback"] and not records["sound_not_completed"]["adopted"]),
        "late_response_cannot_backdate_adoption": (
            not records["late_accept"]["adopted"] and scenarios["late_accept"]["feedback_responses"][0]["status"] == "rejected"),
        "withdrawn_advice_is_not_linked_to_a_later_pit_stop": (
            records["withdrawn_then_pit"]["end_reason"] == "recommendation_withdrawn"
            and not records["withdrawn_then_pit"]["adopted"]),
        "rewind_does_not_carry_feedback_to_the_new_epoch": (
            records["rewind"]["end_reason"] == "telemetry_authority_lost" and not records["rewind"]["adopted"]),
    }
    return {"passed": all(checks.values()), "checks": checks, "scenarios": scenarios}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run()
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit_result(result)

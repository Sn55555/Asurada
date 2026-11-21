"""Prove verified pit cooperation changes a later radio response."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from asurada.config import StrategyThresholds
from asurada.output import ConsoleVoiceOutput
from asurada.personality_memory import export_evidence, rebuild_evidence, update_database
from asurada.personality_runtime import PersonalityRuntime
from asurada.pit_feedback import PitEvidenceStore, load_cooperation
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.strategy import StrategyEngine
from personality_pit_advice_regression import make_frame, NORMAL, WORN
from phase3_voice_regression import FakeSpeechBackend, make_strategy_decision
from pit_feedback_regression import run_case
from regression_support import emit_result


def response(folder, relationship, wear):
    state = make_frame((15, wear, 2, 6, 0, 0))
    state.session_uid = "following-race"
    state.source_timestamp_ms = int(time.time() * 1000)
    decision = StrategyEngine(StrategyThresholds()).evaluate(state)
    state.decision_record = decision.record
    hint = PersonalityRuntime().observe_snapshot(state, decision)
    state.personality = replace(hint, stage=relationship.stage, pit_cooperation=relationship.last_cooperation)
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    service = SpeechService(folder / "voice.sock", output=output).start()
    try:
        client = SharedSpeechClient(service.path)
        reply = client.emit_query_response(state=state, query_kind="why_not_pit", render=False)
        event = reply["output_lifecycle"]["event"]
        unstable = make_strategy_decision(state=state, code="DYNAMICS_UNSTABLE", priority=96,
                                          title="停车检查", detail="Fixture")
        urgent = output.emit(unstable, state=state, render=False)["event"]
    finally:
        service.close()
    return {"reply": event["speak_text"], "evidence_id": event["metadata"].get("personality", {}).get("pit_cooperation_id"),
            "urgent": urgent["speak_text"], "stage": relationship.stage}


def run(work):
    accept = run_case(work / "accepted", feedback=(("同意进站", "turn-accept"),))["record"]
    silence = run_case(work / "silent")["record"]
    pit_path = work / "accepted/evidence.sqlite3"
    driver = accept["driver_id"]
    first_race = accept["session_uid"]
    coop = load_cooperation(pit_path, driver_id=driver, race_id=first_race, epoch=0)
    silent_count = len(load_cooperation(work / "silent/evidence.sqlite3", driver_id=driver, race_id=first_race, epoch=0))

    archive, baseline = work / "relationship.sqlite3", work / "baseline.sqlite3"
    base_races = [f"fixture-{index}" for index in range(1, 7)] + [first_race]
    for index, uid in enumerate(base_races):
        event = {"id": f"event:{uid}", "kind": "overtake", "time_s": 10}
        finish = dict(race_id=uid, epoch=0, positive_events=[event] if index < 2 else [])
        one = update_database(archive, "race", finish, pit_path=pit_path)
        blank = update_database(baseline, "race", finish)
    baseline_answer = response(work, blank, NORMAL)
    cooperation_answer = response(work, one, NORMAL)
    changed_answer = response(work, one, WORN)

    second_race = "fixture-second-cooperation"
    second = dict(accept, recommendation_id="fixture-coop-2", session_uid=second_race)
    wrong_epoch = dict(second, recommendation_id="fixture-wrong-epoch", session_epoch=1)
    wrong_owner = dict(second, recommendation_id="fixture-wrong-driver", driver_id="other-driver")
    store = PitEvidenceStore(pit_path)
    for item in (second, wrong_epoch, wrong_owner):
        assert store.save(item)
    assert store.close()
    finish = dict(race_id=second_race, epoch=0, positive_events=[])
    two = update_database(archive, "race", finish, pit_path=pit_path)
    retry = update_database(archive, "race", finish, pit_path=pit_path)
    update_database(archive, "revoke_pit_cooperation", second["recommendation_id"])
    revoked = update_database(archive, "load", pit_path=pit_path)
    package = export_evidence(archive)
    rebuilt = rebuild_evidence(package, work / "rebuild.sqlite3")

    legacy_path = work / "legacy.sqlite3"
    for index in range(8):
        update_database(legacy_path, "race", dict(race_id=str(index), epoch=0, positive_events=[
            {"id": f"positive-{index}", "kind": "overtake", "time_s": 5.}]))
    # Mirror the old SQLite schema and an already earned H2 for migration proof.
    with sqlite3.connect(legacy_path) as database:
        database.execute("DROP TABLE profile")
        database.execute("PRAGMA user_version=1")
        database.execute("UPDATE growth SET stage=2 WHERE id=1")
    migrated = update_database(legacy_path)
    checks = {
        "explicit_goal_and_silence_are_distinct": len(coop) == 1 and not silence["adopted"] and silent_count == 0,
        "same_h1_context_changes_only_for_verified_history": (
            baseline_answer["stage"] == cooperation_answer["stage"] == 1
            and one.races == blank.races and one.positive_races == blank.positive_races
            and baseline_answer["evidence_id"] is None
            and cooperation_answer["evidence_id"] == accept["recommendation_id"]
            and len(cooperation_answer["reply"]) < len(baseline_answer["reply"])),
        "risk_evidence_disables_familiar_shortcut": changed_answer["evidence_id"] is None
        and "进站评估" in changed_answer["reply"],
        "urgent_text_same": baseline_answer["urgent"] == cooperation_answer["urgent"],
        "h2_requires_two_distinct_verified_finished_races": one.stage == 1 and two.stage == 2
        and one.cooperation_races == 1 and two.cooperation_races == 2 and two == retry,
        "revocation_survives_resync_and_rebuild": revoked == rebuilt and revoked.cooperation_races == 1
        and revoked.stage == 2 and second["recommendation_id"] != revoked.last_cooperation["recommendation_id"]
        and export_evidence(work / "rebuild.sqlite3") == package,
        "old_attained_stage_preserved": migrated.stage == 2 and migrated.cooperation_races == 0,
    }
    return dict(passed=all(checks.values()), checks=checks, fixture="synthetic authoritative telemetry snapshots",
                without_cooperation=baseline_answer, with_cooperation=cooperation_answer,
                after_current_risk_changes=changed_answer, silence_with_change=silence)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(dir="/tmp") as directory, patch.dict(os.environ, {
        "ASURADA_DRIVER_ID": "fixture-driver", "ASURADA_PERSONALITY_ENABLED": "1",
        "ASURADA_HUMOR_ENABLED": "1",
    }):
        report = run(Path(directory))
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit_result(report)

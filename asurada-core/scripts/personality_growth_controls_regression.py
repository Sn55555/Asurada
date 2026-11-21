"""Verify relationship evidence portability and live local personality controls."""
from copy import deepcopy
from dataclasses import replace
import json
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.config import AppConfig
from asurada.output import ConsoleVoiceOutput
from asurada.personality_memory import (
    RelationshipStore, export_evidence, growth_progress, rebuild_evidence, update_database,
)
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.strategy import StrategyEngine
from personality_acceptance_regression import fixture_cooperation, low_load_state
from phase3_voice_regression import FakeSpeechBackend, make_strategy_decision
from regression_support import emit_result


def rejects(call, type_):
    try:
        call()
    except type_:
        return True
    return False


def check_evidence(directory):
    source = directory / "archive.sqlite3"
    target = directory / "reconstructed.sqlite3"
    for race in range(8):
        update_database(source, "race", {"race_id": f"race-{race}", "epoch": 0, "positive_events": []})
    unfinished = growth_progress(source)
    update_database(source, "acknowledgement", "race-1")
    update_database(source, "acknowledgement", "race-2")
    ready = growth_progress(source)
    original_mtime = source.stat().st_mtime_ns
    bundle = export_evidence(source)
    result = rebuild_evidence(bundle, target)
    no_src_writes = source.stat().st_mtime_ns == original_mtime

    for index in range(8, 16):
        event = {"id": f"event-{index}", "kind": "fastest_lap", "time_s": 5 + index}
        for path in (source, target):
            race_id = f"race-{index}"
            update_database(path, "race", {"race_id": race_id, "epoch": 0, "positive_events": [event]})
            if index in {8, 9}:
                update_database(path, "pit_cooperation", fixture_cooperation(race_id))
    broken = deepcopy(bundle)
    broken["relationship"]["stage"] = 3
    failed_target = directory / "invalid.sqlite3"
    store = RelationshipStore(source)
    assert store.close()
    committed = store.current
    with patch("asurada.personality_memory.update_database", side_effect=sqlite3.OperationalError("fixture_io_error")):
        errored = rejects(lambda: store.append("load", None), sqlite3.OperationalError)
    return {
        "growth_explains_evidence_gap": unfinished["stage_label"] == "H1"
            and unfinished["next"]["missing"] == {"races": 0, "positive_races": 2, "cooperation_races": 2},
        "acknowledgement_stays_bound_to_a_verified_race": ready["acknowledgements"] == 2
            and not ready["next"]["waiting_only_for_finish"] and ready["stage_label"] == "H1",
        "export_and_rebuild_are_exact_and_preserve_next_promotion": result.stage == 1
            and growth_progress(source) == growth_progress(target)
            and growth_progress(target)["stage_label"] == "H3"
            and export_evidence(source) == export_evidence(target),
        "export_does_not_write_the_source_database": no_src_writes,
        "storage_failure_preserves_last_committed_stage": errored and store.current == committed and committed.stage == 3,
        "rebuild_cannot_overwrite_an_existing_database": rejects(lambda: rebuild_evidence(bundle, target), FileExistsError),
        "invalid_bundle_leaves_no_database": rejects(lambda: rebuild_evidence(broken, failed_target), ValueError)
            and not failed_target.exists(),
    }


def check_controls(directory):
    config = AppConfig()
    state = low_load_state(stage=3, safe=True)
    decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(state, [])
    state.personality = replace(state.personality, memory_kind="overtake")
    latest = directory / "latest.json"
    latest.write_text(json.dumps(snapshot_payload(state, decision)))
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    now = [70.]
    output._personality_dialogue.clock = lambda: now[0]
    output._personality_dialogue.wall_clock = lambda: (state.source_timestamp_ms + 1) / 1000
    service = SpeechService(directory / "voice.sock", output=output, session_source=latest).start()
    try:
        client = SharedSpeechClient(service.path)
        enabled = client.personality_preferences()
        raw = client.emit_personality_reply(state=state, text="开个玩笑", request_id="normal")
        ordinary = raw["output_lifecycle"]["event"]
        active = backend._handles[-1]
        quiet = client.personality_preferences(quiet=True)
        canceled = not active["active"]
        output.tick()
        raw = client.emit_personality_reply(state=state, text="开个玩笑", request_id="quiet")
        silence = raw["output_lifecycle"]["event"]["event_type"]
        urgent = make_strategy_decision(state=state, code="DYNAMICS_UNSTABLE", priority=96,
                                        title="动态不稳定", detail="urgent")
        event = output.emit(urgent, state=state, render=False)["event"]
        emergency_handle = backend._handles[-1]
        changed = client.personality_preferences(humor="off")
        still_running = emergency_handle["active"]
        backend.complete_all()
        output.tick()
        low = client.personality_preferences(quiet=False, humor="low")
        now[0] += 60
        raw = client.emit_personality_reply(state=state, text="开个玩笑", request_id="low-cooldown")
        held = raw["output_lifecycle"]["event"]["event_type"]
        now[0] += 35
        state = low_load_state(stage=3, safe=True)
        decision = StrategyEngine(config.thresholds, config.usage_hooks_path).evaluate(state, [])
        state.personality = replace(state.personality, memory_kind="overtake")
        latest.write_text(json.dumps(snapshot_payload(state, decision)))
        raw = client.emit_personality_reply(state=state, text="开个玩笑", request_id="low-ready")
        mellow = raw["output_lifecycle"]["event"]
        return {
            "quiet_mode_takes_effect_over_local_ipc": enabled["humor_enabled"] and quiet["quiet"]
                and ordinary["event_type"] == "start" and canceled and silence == "suppress",
            "quiet_mode_keeps_urgent_audio": event["event_type"] == "start" and still_running and not changed["humor_enabled"],
            "low_humor_cools_down_longer_and_drops_memory_callbacks": low["humor"] == "low" and low["humor_enabled"]
                and held == "suppress" and mellow["event_type"] == "start" and "超车" not in mellow["speak_text"],
            "preferences_reject_invalid_values": rejects(lambda: client.personality_preferences(quiet=1), RuntimeError)
                and client.personality_preferences()["quiet"] is False,
        }
    finally:
        service.close()


def run():
    with TemporaryDirectory(dir="/tmp") as temp, patch.dict(
            os.environ, {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        folder = Path(temp)
        checks = {**check_evidence(folder), **check_controls(folder)}
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run())

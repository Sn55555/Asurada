"""Replay fuel advice, exact voice feedback, early lift and comparable fuel use."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.assessment import assess_domain
from asurada.output import ConsoleVoiceOutput
from asurada.pit_feedback import PitEvidenceStore, PitFeedbackTracker, load_history
from asurada.voice_input import VoiceInputCoordinator
from personality_pit_advice_regression import make_frame, NORMAL
from phase3_voice_input_regression import _make_turn
from phase3_voice_regression import FakeSpeechBackend, make_strategy_decision
from regression_support import emit_result


def sample(lap, step, *, critical=False, invalid=False):
    clock = ((lap - 1) * 60 + step) * .65
    state = make_frame((clock, NORMAL, 2, 4, 0, 0))
    state.source_timestamp_ms = 1777000000000 + round(clock * 1000)
    state.lap_number = state.player.lap = lap
    state.player.lap_distance_m = step * 50
    state.player.fuel_laps_remaining = 1. if critical else 25.
    brake_at = 14
    lift_at = 13 if lap == 1 else 12
    start_fuel = {1: 12., 2: 10.6, 3: 9.4}[lap]
    base_use = 1.4 if lap == 1 else 1.2
    state.raw.update(fuel_in_tank=start_fuel - base_use * step / 60,
                     throttle=0. if lift_at <= step <= brake_at else .75,
                     brake=.3 if step == brake_at else .0)
    if invalid:
        state.safety_car = "FULL"
    assess_domain(state)
    return state


def case(folder, *, feedback, interrupted=False, caution=False):
    store = PitEvidenceStore(folder / "fuel.sqlite3")
    tracker = PitFeedbackTracker(store)
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend, pit_feedback=tracker)
    driver = VoiceInputCoordinator(enable_llm_sidecar=False)
    decision = None
    event = None
    answer = None
    try:
        for step in range(60):
            output.observe_pit_evidence(sample(1, step))
        state = sample(2, 0, critical=True)
        decision = make_strategy_decision(state=state, code="LOW_FUEL", priority=72,
                                          title="燃油紧张", detail="比赛燃油余量不足")
        event = output.emit(decision, state=state, render=False)["event"]
        if not interrupted:
            backend.complete_all()
            output.tick()
        state = sample(2, 1)
        if feedback:
            answer = driver.process_completed_turn(
                state=state, turn=replace(_make_turn(feedback), turn_id="fuel-test-turn"),
                voice_output=output, render=False)
        for step in range(1, 60):
            output.observe_pit_evidence(sample(2, step, invalid=(caution and step == 8)))
        output.observe_pit_evidence(sample(3, 0))
        output.end_pit_evidence("service_stopped")
    finally:
        output.shutdown()
        assert store.close()
    result, = load_history(folder / "fuel.sqlite3", kind="fuel")
    return {"event": event, "response": answer.output_debug if answer else None, "record": result}


def run(work):
    cases = {
        "accepted": case(work / "accepted", feedback="我会提前收油"),
        "silent": case(work / "silent", feedback=None),
        "invalid_lap": case(work / "invalid", feedback="同意节油", caution=True),
        "unfinished_audio": case(work / "unfinished", feedback="同意节油", interrupted=True),
    }
    positive = cases["accepted"]
    record = positive["record"]
    checks = {
        "emitted_action_bound_to_history": (
            positive["event"]["metadata"].get("fuel_recommendation_id") == record["recommendation_id"]
            and "提前收油" in positive["event"]["speak_text"]),
        "explicit_confirmation_matches_action_and_result": (
            record["adopted"] and record["feedback"][0]["choice"] == "accept"
            and record["telemetry"]["early_lift"]["coast_distance_m"] == 100.
            and record["outcome"]["delta_kg"] == .2),
        "silent_execution_not_adoption": not cases["silent"]["record"]["adopted"]
        and cases["silent"]["record"]["outcome"] is not None,
        "caution_lap_not_comparable": cases["invalid_lap"]["record"]["outcome"] is None,
        "unfinished_speech_cannot_confirm": cases["unfinished_audio"]["record"]["outcome"] is None
        and not cases["unfinished_audio"]["record"]["feedback"],
    }
    return dict(passed=all(checks.values()), checks=checks, cases=cases,
                fixture="simulated continuous telemetry, deterministic playback, no real microphone")


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

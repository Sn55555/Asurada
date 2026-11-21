"""Replay identical tyre evidence through the real strategy and speech scheduler."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.config import StrategyThresholds
from asurada.contributor_admission import ContributorPolicy, SCORING_FIELDS
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.output import ConsoleVoiceOutput
from asurada.personality_dialogue import PIT_FOLLOW_UP_CODES
from asurada.personality_runtime import PersonalityRuntime
from asurada.pit_feedback import PitEvidenceStore, PitFeedbackTracker
from asurada.speech_applicability import validate_pit_follow_up_applicability
from asurada.strategy import StrategyEngine
from phase3_voice_regression import FakeSpeechBackend, make_state
from regression_support import emit_result

WORN = (77, 78, 79, 80)
NORMAL = (14, 15, 16, 17)
SCENES = (
    *[(second, WORN, 4, 14, 0, 0) for second in range(10, 23)],
    (23, WORN, 4, 14, 1, 0),
    *[(second, NORMAL, 8, 0, 0, 1) for second in (24, 25, 26, 27)],
    (35, WORN, 8, 7, 0, 1),
    (36, NORMAL, 8, 7, 0, 1),
    (37, WORN, 8, 7, 0, 1),
    *[(second, NORMAL, 8, 7, 0, 1) for second in (38, 39, 40, 41)],
)


def make_frame(row):
    second, wear, fitted, age, pit, stops = row
    state = make_state()
    state.source_timestamp_ms = 1777000000000 + second * 1000
    state.player.gap_ahead_s = state.player.gap_behind_s = 3.
    state.rivals = []
    state.player.tyre = replace(state.player.tyre, wear_pct=sum(wear)/4, age_laps=age)
    state.raw.update(session_time_s=second, session_type="Race", result_status=2,
                     timing_mode="race_like", timing_support_level="official_preferred",
                     pit_status_code=pit, num_pit_stops=stops, tyres_wear_pct=list(wear),
                     brake=.03, steer=.02, throttle=.5, tyre_sets={"car_index": state.player.car_index, "fitted_idx": fitted})
    return state


def run_case(stage, *, scenes=SCENES, interrupt_kind=None, disabled=False, failed_initial=False, quiet=False,
             response=None, response_at=11, evidence_store=None):
    engine = StrategyEngine(StrategyThresholds(),
        model_policy=ModelAdmissionPolicy(modes=dict.fromkeys(MODEL_NAMES, "disabled")),
        contributor_policy=ContributorPolicy(modes=dict.fromkeys(SCORING_FIELDS, "disabled")))
    personality = PersonalityRuntime()

    class Backend(FakeSpeechBackend):
        def completion_error(self, handle):
            if failed_initial and handle["job"]["action_code"] == "BOX_WINDOW":
                return "fixture_failure"
            return None

    backend = Backend()
    history = []
    starts = []
    selected = None
    interruption = None

    def submit(state):
        history.append(state)
        decision = engine.evaluate(state, history[-30:])
        state.decision_record = decision.record
        state.personality = replace(personality.observe_snapshot(state, decision), stage=stage)
        return output.emit(decision, state=state, render=False)

    with patch.dict(os.environ, {"ASURADA_PERSONALITY_ENABLED": "0" if disabled else "1"}):
        tracker = PitFeedbackTracker(evidence_store) if evidence_store is not None else None
        output = ConsoleVoiceOutput(backend=backend, pit_feedback=tracker)
        if quiet:
            output.configure_personality({"quiet": True})
        for row in scenes:
            state = make_frame(row)
            event = submit(state)["event"]
            if row[0] == response_at and response is not None:
                reply = output.record_pit_feedback(state=state, text=response, request_id="fixture-reply")
                assert reply["status"] == "queued" and reply["recommendation_id"] == tracker.record["recommendation_id"]
                if event["event_type"] == "start" and event["action_code"] == PIT_FOLLOW_UP_CODES["insist"]:
                    assert not backend._handles[-1]["active"]
            if event["event_type"] == "start":
                starts.append({"second": row[0], "code": event["action_code"], "text": event["speak_text"]})
                if event["action_code"] == PIT_FOLLOW_UP_CODES.get(interrupt_kind):
                    selected = backend._handles[-1]
                    urgent = make_frame(row)
                    urgent.source_timestamp_ms += 100
                    urgent.raw["session_time_s"] += .1
                    if interrupt_kind == "insist":
                        urgent.player.status_tags = ["unstable"]
                    else:
                        urgent.safety_car = "FULL"
                    lifecycle = submit(urgent)
                    urgent_event = lifecycle["event"]
                    cancelled = lifecycle["cancelled_output"] or {}
                    interruption = {
                        "follow_up": selected["job"]["action_code"],
                        "urgent": urgent_event["action_code"],
                        "urgent_text": urgent_event["speak_text"],
                        "began": urgent_event["event_type"] == "start",
                        "stopped_previous": not selected["active"],
                        "cancelled_event": (cancelled.get("output_event_id") == event["output_event_id"]
                                            and cancelled.get("event_type") == "cancel"),
                    }
                    break
            backend.complete_all()
            output.tick()
        backend.complete_all()
        output.tick()
    return starts, interruption, output._last_completed_envelope


def validate_latest_condition():
    from asurada.assessment import assess_domain
    from types import SimpleNamespace

    original = make_frame(SCENES[0])
    latest = make_frame(SCENES[1])
    assess_domain(original)
    assess_domain(latest)
    job = SimpleNamespace(metadata={"pit_follow_up": "insist"})
    clock = lambda: latest.source_timestamp_ms / 1000
    validate_pit_follow_up_applicability(job, original, latest, wall_clock=clock)
    latest.raw["steer"] = .7
    assess_domain(latest)
    try:
        validate_pit_follow_up_applicability(job, original, latest, wall_clock=clock)
    except ValueError:
        return True
    return False


def run():
    codes = list(PIT_FOLLOW_UP_CODES.values())
    examples = {}
    checks = {}
    for stage in range(4):
        starts, _, repeatable = run_case(stage)
        follow_ups = [event for event in starts if event["code"] in codes]
        checks[f"H{stage}_order_and_dedup"] = (
            [event["code"] for event in follow_ups] == codes
            and [event["second"] for event in follow_ups] == [22, 26, 40]
            and sum(event["code"] == "BOX_WINDOW" for event in starts) == 2)
        checks[f"H{stage}_withdrawn_advice_cannot_be_repeated"] = repeatable is None
        examples[f"H{stage}"] = starts
    checks["four_stage_variants"] = all(
        len({item["text"] for starts in examples.values() for item in starts if item["code"] == code}) == 4
        for code in codes)
    interruptions = {kind: run_case(2, interrupt_kind=kind)[1] for kind in PIT_FOLLOW_UP_CODES}
    checks["all_follow_ups_are_preemptible"] = all(
        interrupt and interrupt["began"] and interrupt["stopped_previous"] and interrupt["cancelled_event"]
        and interrupt["urgent"] == ("DYNAMICS_UNSTABLE" if kind == "insist" else "SAFETY_CAR")
        for kind, interrupt in interruptions.items())
    no_fitted_index = [(*row[:2], 255, *row[3:]) for row in SCENES]
    checks["no_same_set_proof_no_admission"] = all(
        event["code"] != PIT_FOLLOW_UP_CODES["admit"] for event in run_case(1, scenes=no_fitted_index)[0])
    checks["personality_switch_disables_follow_ups"] = all(
        event["code"] not in codes for event in run_case(0, disabled=True)[0])
    checks["failed_original_audio_cannot_be_followed_up"] = all(
        event["code"] not in codes for event in run_case(0, failed_initial=True)[0])
    worn_replacement = (*SCENES[:14], (24, WORN, 8, 0, 0, 1), (25, WORN, 8, 0, 0, 1))
    checks["prior_episode_does_not_suppress_new_worn_set"] = [
        item["second"] for item in run_case(0, scenes=worn_replacement)[0] if item["code"] == "BOX_WINDOW"
    ] == [10, 24]
    quiet_starts = [item for item in run_case(3, quiet=True)[0] if item["code"] in codes]
    checks["quiet_suppresses_insistence_but_keeps_h0_corrections"] = (
        [item["code"] for item in quiet_starts] == codes[1:]
        and [item["text"] for item in quiet_starts] ==
            [item["text"] for item in examples["H0"] if item["code"] in codes[1:]])
    checks["authoritative_snapshot_blocks_follow_up_in_corner"] = validate_latest_condition()
    with TemporaryDirectory(prefix="asurada-s5-pit-response-") as directory:
        for label, response in (("accept", "同意进站"), ("decline", "我不进站")):
            store = PitEvidenceStore(Path(directory) / f"{label}.db")
            try:
                starts, _, _ = run_case(2, response=response, evidence_store=store)
            finally:
                assert store.close()
            checks[f"explicit_{label}_suppresses_insistence_but_preserves_corrections"] = (
                [item["code"] for item in starts] == ["BOX_WINDOW", codes[1], "BOX_WINDOW", codes[2]])
        store = PitEvidenceStore(Path(directory) / "active.db")
        try:
            starts, _, _ = run_case(2, response="我不进站", response_at=22, evidence_store=store)
        finally:
            assert store.close()
        checks["explicit_reply_cancels_in_progress_insistence_and_preserves_corrections"] = (
            [item["code"] for item in starts if item["code"] in codes] == codes)
    return {"passed": all(checks.values()), "checks": checks, "examples": examples,
            "interruptions": interruptions, "scenes": SCENES}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Save exact replay inputs and scheduled speech.")
    args = parser.parse_args()
    report = run()
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    emit_result(report)

"""Compare an audited race fragment and controlled attack transitions through speech IPC."""
from __future__ import annotations

import argparse
from dataclasses import replace
import itertools
import json
from pathlib import Path
from subprocess import check_output
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.decode import decode_snapshot
from asurada.attack_opportunity import AttackOpportunities, forecast_on_approach, validate_attack_cue
from asurada.models import StrategyDecision, StrategyMessage
from asurada.output import ConsoleVoiceOutput
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.tts_backends import SpeechBackend
from asurada.voice_input import VoiceInputCoordinator
from phase3_attack_mode_regression import _decision, _state
from phase3_voice_input_regression import _make_turn
from personality_acceptance_regression import low_load_state
from regression_support import emit_result

class ReplayBackend(SpeechBackend):
    def __init__(self, durations):
        self.clock = 0.
        self.jobs = []
        self.durations = durations

    def start(self, job):
        # Simulation only. Physical samples and ears must be inspected separately.
        opportunity = job.metadata.get("attack_opportunity")
        duration = self.durations.get(opportunity["phase"], 1.5) if opportunity else 2.0
        row = {"code": job.action_code, "text": job.speak_text, "start_s": self.clock,
               "simulated_end_s": self.clock + duration, "cancel_s": None,
               "opportunity": job.metadata.get("attack_opportunity")}
        self.jobs.append(row)
        return row

    def is_active(self, handle):
        return handle["cancel_s"] is None and self.clock < handle["simulated_end_s"]

    def stop(self, handle):
        handle["cancel_s"] = self.clock


def synthetic_rows(*, transient=False, pending=False, rewind=False, change_target=False, urgent=False):
    closed_s = 4.5
    for offset, t in enumerate([0., .25, .5, .75, 1., 1.25, 1.5, 2., 2.5, 3., 3.25, 3.5, 4., 4.5, 5., 5.5]):
        ready = (1.25 <= t < closed_s) if not transient else t == 1.25
        gap = max(.6, 1.37 - .25 * t)
        rear = .3 if t >= closed_s and not change_target else 1.8
        state = _state(gap_ahead=gap, drs_available=ready)
        state.track = "Jeddah"
        state.lap_number = state.player.lap = 16
        state.source_timestamp_ms = int((1597 + t) * 1000)
        state.session_epoch = 1 if rewind and t >= closed_s else 0
        state.session_epoch_explicit = True
        state.raw.update(result_status=2, pit_status_code=0, brake=0., steer=0., session_time_s=1597 + t,
                         lap_distance_m=1860 + 60 * t)
        state.player = replace(state.player, gap_confidence_ahead="high", lap_distance_m=1860 + 60 * t,
                               speed_kph=216., gap_behind_s=rear)
        state.rivals = [replace(state.player, position=1, name="阿尔本",
                                lap_distance_m=state.player.lap_distance_m + gap * state.player.speed_kph / 3.6,
                                car_index=(7 if change_target and t >= closed_s else 16))]
        code = "ATTACK_WINDOW" if ready else "NONE"
        if pending and offset == 0 or urgent and t == 3.25:
            code = "DYNAMICS_UNSTABLE"
        decision = _decision(code=code, detail="原策略：当前选定进攻窗口。" if ready else "状态更新",
                             setup_method="drs_tow", commit_method="drs_tow" if ready else "none")
        decision.debug["context"]["track_segment"] = "Straight 03"
        yield state, decision


def archive_rows(path):
    with path.open() as archive:
        for line in itertools.islice(archive, 245, 323):
            row = json.loads(line)
            state = decode_snapshot(row)
            decision = StrategyDecision(messages=[StrategyMessage(**item) for item in row["messages"]],
                                        debug=dict(row["debug"]), record=state.decision_record)
            yield state, decision


def historical_cues(path):
    with path.open() as archive:
        return [event for line in itertools.islice(archive, 245, 323)
                for receipt in json.loads(line)["debug"].get("speech_submission", {}).get("receipts", ())
                if (event := ((receipt.get("lifecycle") or {}).get("event") or {})).get("event_type") == "start"
                and event.get("action_code") in {"ATTACK_WINDOW", "ATTACK_MODE_REMINDER", "ATTACK_MODE_FORMING"}]


def rendered_durations(folder):
    def seconds(clip):
        return float(check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=noprint_wrappers=1:nokey=1", str(clip)], text=True).strip())

    clips = {"forming": "preparation.aiff", "actionable": "action.aiff", "withdrawal": "withdraw.aiff"}
    return {phase: seconds(folder / name) for phase, name in clips.items()}


def acoustic_timing(report, durations):
    report["acoustic_scope"] = "local macOS say file render using the existing fallback route; not earphone timing"
    report["rendered_clip_seconds"] = durations
    for label in ("candidate", "archive_comparison"):
        if label not in report:
            continue
        sample = report[label]
        for job in sample["jobs"]:
            opportunity = job["opportunity"]
            if opportunity:
                whole_clip_end = job["start_s"] + durations[opportunity["phase"]]
                job["keyword_end_upper_bound_s"] = round(whole_clip_end, 6)
                boundary = min(opportunity["latest_useful_s"], sample.get("latest_observed_brake_s", float("inf")),
                               job["cancel_s"] if job["cancel_s"] is not None else float("inf"))
                job["earliest_cutoff_s"] = round(boundary, 6)
                job["remaining_s_after_clip"] = round(boundary - whole_clip_end, 6)
    if "archive_comparison" in report:
        passed = any(job["remaining_s_after_clip"] > 0
                     for job in report["archive_comparison"]["jobs"]
                     if job["opportunity"] and job["opportunity"]["phase"] == "forming")
        report["checks"]["real_preparation_finishes_before_brake_or_cancellation"] = passed
        report["passed"] = report["passed"] and passed


def replay(rows, *, automatic, manual=False, block_until=None, durations=None):
    with TemporaryDirectory(dir="/tmp", prefix="attack-check-") as tmp:
        with patch.dict("os.environ", {
            "ASURADA_PERSONALITY_ENABLED": str(int(automatic)),
            "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "attack.json"),
        }):
            backend = ReplayBackend(durations or {})
            output = ConsoleVoiceOutput(backend=backend)
            service = SpeechService(Path(tmp) / "voice.sock", output=output).start()
            client = SharedSpeechClient(service.path)
            decisions = []
            try:
                for state, decision in rows:
                    if manual and not output._attack_mode.status().enabled:
                        output._attack_mode.enable(state=state)
                    backend.clock = state.raw["session_time_s"]
                    result = client.emit(decision, state=state)
                    event = result["event"]
                    if block_until is not None and event["action_code"] == "DYNAMICS_UNSTABLE":
                        backend.jobs[-1]["simulated_end_s"] = block_until
                    if event["event_type"] not in {"idle", "suppress"}:
                        decisions.append({"at_s": backend.clock, "action": event["action_code"],
                                          "event": event["event_type"], "text": event["speak_text"]})
                backend.clock += 4.
                output.tick()
                jobs = list(backend.jobs)
                return {"jobs": jobs, "lifecycle": decisions}
            finally:
                service.close()


def phases(result):
    return [row["opportunity"]["phase"] for row in result["jobs"] if row["opportunity"]]


def contextual_followups():
    state = low_load_state(stage=2)
    state.rivals = [replace(state.player, position=state.player.position - 1, car_index=11)]
    coordinator = VoiceInputCoordinator(enable_llm_sidecar=False)
    backend = ReplayBackend({})
    output = ConsoleVoiceOutput(backend=backend)

    def say(words, index):
        backend.clock += 3
        turn = replace(_make_turn(words), turn_id=f"followup-{index}")
        result = coordinator.process_completed_turn(state=state, turn=turn, voice_output=output, render=False)
        return result.output_debug.get("output_lifecycle", {}).get("event", {}).get("speak_text", "")

    first = say("为什么现在不攻", 1)
    refreshed = say("那现在呢", 2)
    state.rivals = [replace(state.rivals[0], car_index=20)]
    changed = say("那现在呢", 3)
    state.session_epoch += 1
    rewound = say("那现在呢", 4)
    return ("因为" in first and "因为" in refreshed and "不是当前目标" in changed
            and "进攻，还是进站" in rewound)


def forecast_runway_checks():
    def sample(clock, distance, *, rear_gap=2., steer=0., permission=True, opened=False):
        state = _state(gap_ahead=.35, drs_available=False)
        state.track = "Jeddah"
        state.player = replace(state.player, lap=state.lap_number, lap_distance_m=distance,
                               speed_kph=216., gap_confidence_ahead="high", gap_behind_s=rear_gap)
        state.rivals = [replace(state.player, position=state.player.position - 1, car_index=11,
                                name="前车", lap_distance_m=distance + 22, pit_status="NONE")]
        state.raw.update(result_status=2, pit_status_code=0, session_time_s=clock, brake=0., steer=steer,
                         forecast_drs_allowed=permission, drs_open=opened)
        forecast = dict(
            id="same-target-and-straight", recommended=True, target=11, clock_s=clock,
            gate_m=5445., gate_lap=state.player.lap, length_m=6174., straight_m=815.,
            remaining_m=5445. - distance, eta_s=(5445. - distance) / 60., gap_s=.35,
        )
        decision = _decision(code="NONE", detail="状态更新", setup_method="none", commit_method="none")
        decision.debug["attack_forecast"] = forecast
        return state, decision

    track = AttackOpportunities()
    high_load, decision = sample(10., 4410.)
    on_mapped_approach = forecast_on_approach(high_load, decision.debug["attack_forecast"])
    first = track._forecast_cue(high_load, decision, {})
    exit_state, decision = sample(11., 4600.)
    settling = track._forecast_cue(exit_state, decision, {})
    on_straight, decision = sample(11.45, 4635.)
    cue = track._forecast_cue(on_straight, decision, {})
    late, _ = sample(11.80, 5310.)
    near_gate, _ = sample(11.80, 5240.)
    busy, _ = sample(11.60, 4650., steer=.3)
    unknown, _ = sample(11.55, 4640., permission=None)
    denied, _ = sample(11.55, 4640., permission=False)
    already_open, _ = sample(11.55, 4640., opened=True)
    unknown_wing, _ = sample(11.55, 4640., opened=None)
    spoken = replay([sample(20., 4635.), sample(20.45, 4660.)], automatic=True)
    silent = replay([sample(20., 4635., permission=None), sample(20.45, 4660., permission=None)],
                    automatic=True)
    return {
        "far_gate_on_a_high_load_corner_stays_silent": (
            first is None and not on_mapped_approach),
        "next_straight_gets_stable_action_first": (
            settling is None and cue is not None and cue.text == "这条直道，开尾翼。"),
        "drs_call_waits_for_permission_and_an_unopened_wing": (
            cue is not None and all(not validate_attack_cue(cue.metadata, state, "NONE")
                                    for state in (unknown, denied, already_open, unknown_wing))),
        "shared_radio_delivers_place_and_action_only_when_confirmed": (
            [job["text"] for job in spoken["jobs"]] == ["这条直道，开尾翼。"] and not silent["jobs"]),
        "key_phrase_and_driver_margin_rechecked_before_start": (
            cue is not None and validate_attack_cue(cue.metadata, on_straight, "NONE")
            and not validate_attack_cue(cue.metadata, late, "NONE")
            and not validate_attack_cue(cue.metadata, near_gate, "NONE")
            and not validate_attack_cue(cue.metadata, on_straight, "NONE", delivery_delay_s=3.)),
        "holding_the_queue_does_not_grant_permission_to_speak_mid_corner": (
            cue is not None and not validate_attack_cue(cue.metadata, busy, "NONE")),
    }


def run(archive, durations=None):
    baseline = replay(synthetic_rows(), automatic=False, durations=durations)
    candidate = replay(synthetic_rows(), automatic=True, durations=durations)
    explicit = replay(synthetic_rows(), automatic=True, manual=True, durations=durations)
    transient = replay(synthetic_rows(transient=True), automatic=True, durations=durations)
    pending = replay(synthetic_rows(pending=True), automatic=True, block_until=1602., durations=durations)
    rewind = replay(synthetic_rows(rewind=True), automatic=True, durations=durations)
    swapped = replay(synthetic_rows(change_target=True), automatic=True, durations=durations)
    interrupted = replay(synthetic_rows(urgent=True), automatic=True, durations=durations)
    checks = {
        "same_target_prepare_commit_single_withdrawal": phases(candidate) == ["forming", "actionable", "withdrawal"],
        "personality_and_manual_have_one_stream": phases(explicit) == phases(candidate),
        "one_frame_window_ignored": "actionable" not in phases(transient),
        "withdraw_unheard_queued_opportunity_silently": not phases(pending),
        "rewind_does_not_publish_old_withdrawal": "withdrawal" not in phases(rewind),
        "front_car_change_retracts_delivered_opportunity": phases(swapped)[-1:] == ["withdrawal"],
        "emergency_starts_when_attack_is_stopped": any(
            row["code"] == "DYNAMICS_UNSTABLE" and any(
                candidate["code"] == "ATTACK_MODE_REMINDER" and candidate["cancel_s"] == row["start_s"]
                for candidate in interrupted["jobs"])
            for row in interrupted["jobs"]),
        "baseline_no_preparation": "forming" not in phases(baseline),
        "followups_bind_same_target_and_clarify_after_rewind": contextual_followups(),
        **forecast_runway_checks(),
    }
    report = {"checks": checks, "input_scope": "in-process replay through shared speech IPC and simulated playback",
              "baseline": baseline, "candidate": candidate, "manual": explicit}
    if archive and archive.is_file():
        observed = replay(archive_rows(archive), automatic=True, durations=durations)
        observed["archive"] = str(archive)
        observed["rows"] = [246, 323]
        observed["latest_observed_brake_s"] = next(state.raw["session_time_s"] for state, _ in archive_rows(archive)
            if state.raw["session_time_s"] > 1597 and state.raw.get("brake", 0) > .18)
        observed["historical_attack_cues_in_same_straight"] = historical_cues(archive)
        report["archive_comparison"] = observed
        checks["real_straight_gets_preparatory_cue_before_braking"] = bool(phases(observed)) and any(
            row["simulated_end_s"] < min(observed["latest_observed_brake_s"],
                                         row["cancel_s"] if row["cancel_s"] is not None else float("inf"))
            for row in observed["jobs"] if row["opportunity"] and row["opportunity"]["phase"] == "forming")
    report["passed"] = all(checks.values())
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--audio-dir", type=Path, help="Existing fallback-voice AIFF renders for elapsed-time estimates")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    durations = rendered_durations(args.audio_dir) if args.audio_dir else None
    report = run(args.archive, durations)
    if durations:
        acoustic_timing(report, durations)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    emit_result(report)

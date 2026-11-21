"""Correlate spoken pit advice, explicit driver feedback and observed tyre changes."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from statistics import mean
import time
import uuid

from .async_sink import AsyncRuntimeSink
from .fuel_feedback import FuelFeedbackTracker, fuel_feedback_intent
from .personality_pit_advice import CONFIRM_SECONDS, MAX_SAMPLE_GAP_SECONDS, TyreObservation, tyre_observation

FEEDBACK_WINDOW_SECONDS = 120
OUTCOME_WINDOW_SECONDS = 180
FEEDBACK_PHRASES = {
    "同意进站": "accept", "采纳进站建议": "accept", "我会进站": "accept", "我去换胎": "accept",
    "不进站": "decline", "我不进站": "decline", "拒绝进站建议": "decline", "先不进站": "decline",
}


def pit_feedback_intent(text: str | None) -> str | None:
    return FEEDBACK_PHRASES.get((text or "").strip().strip("，。！？,.!?").strip())


def evidence_path() -> Path:
    return Path(os.getenv("ASURADA_PIT_EVIDENCE_DB") or "~/.asurada/pit-evidence.sqlite3").expanduser()


def driver_profile_id() -> str:
    return os.getenv("ASURADA_DRIVER_ID", "").strip() or "local"


def verified_pit_cooperation(record: dict) -> dict | None:
    """Accept only a completed, explicit, telemetrically verified strategy outcome."""
    outcome = record.get("outcome") or {}
    telemetry = record.get("telemetry") or {}
    change = telemetry.get("tyre_change") or {}
    feedback = record.get("feedback") or []
    original = record.get("before") or {}
    if (record.get("adopted") is not True or record.get("end_reason") != "tyre_change_verified"
            or (record.get("playback") or {}).get("completed_at") is None
            or not feedback or feedback[-1].get("choice") != "accept"
            or not telemetry.get("pit_observed") or not change.get("snapshot_id")
            or not record.get("snapshot_binding_id") or not feedback[-1].get("snapshot_id")
            or original.get("verdict") != "box_now" or outcome.get("wear_goal_verified") is not True):
        return None
    return {
        "recommendation_id": record["recommendation_id"],
        "driver_id": record["driver_id"],
        "race_id": record["session_uid"],
        "epoch": record["session_epoch"],
        "recommendation_snapshot_id": record["snapshot_binding_id"],
        "reply_snapshot_id": feedback[-1]["snapshot_id"],
        "outcome_snapshot_id": change["snapshot_id"],
        "wear_before_pct": outcome["wear_before_pct"],
        "wear_after_pct": outcome["wear_after_pct"],
    }


class PitEvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.worker = AsyncRuntimeSink(self, capacity=128)

    def save(self, record: dict) -> bool:
        return self.worker.append(record["recommendation_id"], record)

    def append(self, identity: str, record: dict) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=.5)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS pit_evidence(
                id TEXT PRIMARY KEY, created_at REAL NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS pit_cooperation(
                id TEXT PRIMARY KEY, driver_id TEXT NOT NULL, race_id TEXT NOT NULL,
                epoch INTEGER NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS pit_cooperation_scope
                ON pit_cooperation(driver_id, race_id, epoch)""")
            db.execute("""INSERT INTO pit_evidence VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload""",
                (identity, record["playback"]["started_at"], json.dumps(record, ensure_ascii=False)))
            cooperation = verified_pit_cooperation(record)
            if cooperation is not None:
                db.execute("INSERT OR IGNORE INTO pit_cooperation VALUES (?, ?, ?, ?, ?)",
                           (identity, cooperation["driver_id"], cooperation["race_id"],
                            cooperation["epoch"], json.dumps(cooperation)))

    def close(self) -> bool:
        return self.worker.close(timeout_s=1)


def load_history(path: Path, limit: int = 20, *, kind: str = "pit") -> list[dict]:
    if limit == 0 or not path.exists():
        return []
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=.5)) as db:
        records = []
        for payload, in db.execute("SELECT payload FROM pit_evidence ORDER BY created_at DESC"):
            record = json.loads(payload)
            if kind == "all" or record.get("advice_kind", "pit") == kind:
                records.append(record)
                if 0 < limit <= len(records):
                    break
        return records


def load_cooperation(path: Path, *, driver_id: str, race_id: str, epoch: int) -> list[dict]:
    return load_race_cooperation(path, driver_id=driver_id, races=[(race_id, epoch)])


def load_race_cooperation(path: Path, *, driver_id: str, races: list[tuple[str, int]]) -> list[dict]:
    if not races or not path.exists():
        return []
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=.5)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='pit_cooperation'").fetchone() is None:
            return []
        placeholders = ",".join("(?, ?)" for _ in races)
        parameters = (driver_id, *(item for scope in races for item in scope))
        rows = db.execute(
            f"""SELECT payload FROM pit_cooperation WHERE driver_id=?
                AND (race_id, epoch) IN (VALUES {placeholders}) ORDER BY rowid""", parameters)
        return [json.loads(row[0]) for row in rows]


class PitFeedbackTracker:
    def __init__(self, store: PitEvidenceStore) -> None:
        self.store = store
        self.fuel = FuelFeedbackTracker(store, driver_profile_id())
        self.record: dict | None = None
        self.baseline: TyreObservation | None = None
        self.last: TyreObservation | None = None
        self.confirming: tuple[float, str, int | None, str, int] | None = None
        self.last_source_ms: int | None = None

    @property
    def active(self) -> bool:
        return self.record is not None and self.record["end_reason"] is None

    def needs_snapshot(self, source_timestamp_ms: int) -> bool:
        return self.fuel.source_ms is None or source_timestamp_ms > self.fuel.source_ms

    def start(self, job, scope: tuple) -> None:
        self.fuel.start(job, scope)
        evidence = job.metadata.get("tyre_pit_original")
        if not evidence:
            return
        original = TyreObservation(**evidence)
        if self.active:
            self.end("superseded_by_new_advice")
        identity = uuid.uuid4().hex
        job.metadata["pit_recommendation_id"] = identity
        self.baseline, self.last, self.confirming = original, original, None
        self.last_source_ms = job.metadata.get("pit_source_timestamp_ms")
        self.record = {
            "recommendation_id": identity,
            "driver_id": driver_profile_id(),
            "session_uid": str(scope[0]), "session_epoch": scope[1],
            "decision_id": job.metadata.get("pit_decision_id"),
            "snapshot_binding_id": job.snapshot_binding_id,
            "source_timestamp_ms": self.last_source_ms,
            "output_event_id": job.output_event_id,
            "text": job.speak_text,
            "playback": {"started_at": time.time(), "completed_at": None},
            "before": asdict(original), "feedback": [], "telemetry": {"pit_observed": False, "tyre_change": None},
            "outcome": None, "adopted": False, "end_reason": None,
        }
        self._save()

    def playback_completed(self, job) -> None:
        self.fuel.completed(job)
        if self.active and job.metadata.get("pit_recommendation_id") == self.record["recommendation_id"]:
            self.record["playback"]["completed_at"] = time.time()
            self._save()

    def feedback(self, state, text: str, turn_id: str, *, interpretation=None) -> dict:
        choice = pit_feedback_intent(text)
        if interpretation is not None:
            if not isinstance(interpretation, dict) or interpretation.get("choice") not in {"accept", "decline", "defer"}:
                return {"status": "rejected", "reason": "invalid_radio_choice"}
            choice = interpretation["choice"]
            topic = interpretation.get("topic")
            record = self.record if topic == "pit" else self.fuel.record if topic == "fuel" else None
            if not record or not record.get("recommendation_id") or record["recommendation_id"] != interpretation.get("id"):
                return {"status": "rejected", "reason": "radio_advice_superseded"}
            if topic == "fuel":
                return self.fuel.feedback(state, text, turn_id, choice=choice)
        elif fuel_feedback_intent(text):
            return self.fuel.feedback(state, text, turn_id)
        if choice is None:
            return {"status": "rejected", "reason": "explicit_pit_feedback_required"}
        record = self.record
        scope = (str(state.session_uid), state.session_epoch)
        if record is None or scope != (record["session_uid"], record["session_epoch"]):
            return {"status": "rejected", "reason": "no_matching_pit_recommendation"}
        for reply in record["feedback"]:
            if reply["turn_id"] == turn_id:
                if reply["choice"] != choice:
                    return {"status": "rejected", "reason": "pit_feedback_turn_conflict"}
                return {"status": "already_recorded", "recommendation_id": record["recommendation_id"],
                        "choice": choice, "adopted": record["adopted"]}
        sample = tyre_observation(state)
        if (not self.active or record["playback"]["completed_at"] is None or sample is None or sample.pit
                or sample.verdict != "box_now" or record["telemetry"]["pit_observed"]
                or sample.stops != self.baseline.stops
                or not 0 <= sample.time_s - self.baseline.time_s <= FEEDBACK_WINDOW_SECONDS):
            return {"status": "rejected", "reason": "pit_feedback_window_unavailable"}
        if len(record["feedback"]) >= 32:
            return {"status": "rejected", "reason": "pit_feedback_limit"}
        record["feedback"].append({"choice": choice, "turn_id": turn_id, "text": text,
                                   "session_time_s": sample.time_s, "observed_at": time.time(),
                                   "snapshot_id": state.assessment.snapshot_id})
        if not self._save():
            record["feedback"].pop()
            return {"status": "unavailable", "reason": "pit_evidence_queue_full"}
        return {"status": "queued", "recommendation_id": record["recommendation_id"],
                "choice": choice, "adopted": False}

    def observe(self, state) -> None:
        self.fuel.observe(state)
        if not self.active or (str(state.session_uid), state.session_epoch) != (
                self.record["session_uid"], self.record["session_epoch"]):
            return
        if self.last_source_ms is not None and state.source_timestamp_ms <= self.last_source_ms:
            return
        self.last_source_ms = state.source_timestamp_ms
        if state.raw.get("result_status") in {3, 4, 5, 6, 7}:
            self.end("session_finished")
            return
        sample = tyre_observation(state)
        if sample is None:
            self.confirming = None
            return
        before = self.baseline
        if sample.time_s < self.last.time_s or sample.stops < before.stops:
            self.end("telemetry_rewound")
            return
        if sample.time_s == self.last.time_s:
            return
        continuous = sample.time_s - self.last.time_s <= MAX_SAMPLE_GAP_SECONDS
        self.last = sample
        if sample.time_s - before.time_s > OUTCOME_WINDOW_SECONDS:
            self.end("pit_observed_tyre_change_unverified" if self.record["telemetry"]["pit_observed"]
                     else "observation_timeout")
            return
        telemetry = self.record["telemetry"]
        if not telemetry["pit_observed"] and (sample.pit or sample.stops > before.stops):
            telemetry.update(pit_observed=True, first_pit_time_s=sample.time_s, pit_status_code=sample.pit,
                             pit_count_at_detection=sample.stops, pit_snapshot_id=state.assessment.snapshot_id)
            self._save()
        if sample.stops > before.stops + 1:
            self.end("additional_pit_stop_before_confirmation")
            return
        evidence = None
        if not sample.pit and sample.stops == before.stops + 1:
            evidence = self._change_reason(sample, before)
        elif (not telemetry["pit_observed"] and sample.verdict == "stable"
              and before.fitted is not None and sample.fitted == before.fitted
              and sample.compound == before.compound and sample.age_laps >= before.age_laps
              and all(old - new >= 10 for old, new in zip(before.wear, sample.wear))):
            evidence = "recommendation_withdrawn"
        if evidence is None:
            self.confirming = None
            return
        signature = (evidence, sample.fitted, sample.compound, sample.stops)
        if not continuous or self.confirming is None or self.confirming[1:] != signature:
            self.confirming = (sample.time_s, *signature)
            return
        if sample.time_s - self.confirming[0] < CONFIRM_SECONDS:
            return
        if evidence == "recommendation_withdrawn":
            self.end(evidence)
            return
        telemetry["tyre_change"] = {"reason": evidence, "after": asdict(sample),
                                   "snapshot_id": state.assessment.snapshot_id,
                                   "source_timestamp_ms": state.source_timestamp_ms}
        delta = round(mean(before.wear) - mean(sample.wear), 2)
        self.record["outcome"] = {"wear_before_pct": round(mean(before.wear), 2),
                                  "wear_after_pct": round(mean(sample.wear), 2),
                                  "wear_reduction_percentage_points": delta,
                                  "wear_verdict_after": sample.verdict,
                                  "wear_goal_verified": delta > 0 and sample.verdict == "stable",
                                  "measured": "tyre_wear"}
        feedback = self.record["feedback"]
        self.record["adopted"] = bool(self.record["playback"]["completed_at"] is not None
                                      and feedback and feedback[-1]["choice"] == "accept"
                                      and feedback[-1]["session_time_s"] < telemetry["first_pit_time_s"])
        self.end("tyre_change_verified")

    @staticmethod
    def _change_reason(sample: TyreObservation, before: TyreObservation) -> str | None:
        if before.fitted is not None and sample.fitted is not None and sample.fitted != before.fitted:
            return "fitted_set_changed"
        if sample.compound != before.compound:
            return "compound_changed"
        if sample.age_laps < before.age_laps and all(old - new >= 10 for old, new in zip(before.wear, sample.wear)):
            return "tyre_age_reset_and_wear_dropped"
        return None

    def end(self, reason: str) -> None:
        if reason in {"session_scope_changed", "telemetry_authority_lost", "service_stopped"}:
            self.fuel.mark_end(reason)
        if self.active:
            self.record["end_reason"] = reason
            self._save()

    def _save(self) -> bool:
        return self.store.save(self.record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=evidence_path())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--kind", choices=("pit", "fuel", "all"), default="pit")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    print(json.dumps(load_history(args.db, args.limit, kind=args.kind), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

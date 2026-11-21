"""Associate one explicit lift-and-coast suggestion with comparable fuel observations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import time
import uuid

from .input_quality import valid_input


def fuel_feedback_intent(text: str | None) -> str | None:
    return {"同意节油": "accept", "我会提前收油": "accept",
            "不节油": "decline", "我不提前收油": "decline"}.get(
        (text or "").strip().strip("，。！？,.!?").strip())


@dataclass(frozen=True)
class FuelSample:
    session_time: float
    lap: int
    distance_m: float
    fuel_kg: float
    throttle: float
    brake: float
    speed: float
    track: str
    weather: str
    tyre: str
    snapshot_id: str
    source_ms: int

    @property
    def context(self) -> tuple:
        return self.track, self.weather, self.tyre


def fuel_observation(state) -> FuelSample | None:
    if (state.assessment is None or state.raw.get("result_status") != 2
            or state.raw.get("session_paused") or state.raw.get("pit_status_code") != 0
            or state.assessment.labels.race_state != "green"
            or state.assessment.labels.dynamics_state != "stable"
            or not state.track or not state.weather
            or not state.player.tyre.compound or state.player.tyre.compound.lower() == "unknown"):
        return None
    throttle = valid_input("throttle", state.raw.get("throttle"))
    brake = valid_input("brake", state.raw.get("brake"))
    values = (state.raw.get("session_time_s"), state.player.lap_distance_m,
              state.raw.get("fuel_in_tank"), throttle, brake, state.player.speed_kph,
              state.player.gap_ahead_s, state.player.gap_behind_s)
    if (any(type(x) not in {int, float} or not math.isfinite(x) or x < 0 for x in values)
            or type(state.lap_number) is not int or state.lap_number < 1 or min(values[-2:]) < 1.5):
        return None
    clock, distance, fuel, throttle, brake, speed, _, _ = values
    return FuelSample(clock, state.lap_number, distance, fuel, throttle, brake, speed, state.track,
                      state.weather, state.player.tyre.compound, state.assessment.snapshot_id,
                      state.source_timestamp_ms)


@dataclass
class _FuelLap:
    start: FuelSample
    clean: bool
    lifts: list[tuple[float, float, FuelSample]] = field(default_factory=list)
    rolling_lift: FuelSample | None = None


class FuelFeedbackTracker:
    def __init__(self, store, driver_id: str) -> None:
        self.store = store
        self.driver_id = driver_id
        self.record = None
        self.scope = None
        self.source_ms = None
        self.last = None
        self.lap = None
        self.reference = None
        self.locked_reference = None

    @property
    def active(self) -> bool:
        return self.record is not None and self.record["end_reason"] is None

    def start(self, job, scope) -> None:
        if job.metadata.get("fuel_original") is None:
            return
        if self.active:
            return  # An ongoing comparison is not replaced by a reminder.
        if self.scope != scope:
            self._switch_scope(scope)
        original = job.metadata["fuel_original"]
        self.locked_reference = self.reference
        identity = uuid.uuid4().hex
        job.metadata["fuel_recommendation_id"] = identity
        self.record = dict(recommendation_id=identity, advice_kind="fuel", driver_id=self.driver_id,
                           session_uid=str(scope[0]), session_epoch=scope[1], text=job.speak_text,
                           snapshot_binding_id=job.snapshot_binding_id,
                           output_event_id=job.output_event_id, before=original,
                           playback={"started_at": time.time(), "completed_at": None}, feedback=[],
                           telemetry={"early_lift": None}, outcome=None, adopted=False, end_reason=None)
        self._save()

    def _save(self) -> bool:
        return self.store.save(self.record)

    def completed(self, job) -> None:
        if self.active and job.metadata.get("fuel_recommendation_id") == self.record["recommendation_id"]:
            self.record["playback"]["completed_at"] = time.time()
            self._save()

    def mark_end(self, reason: str) -> None:
        if self.active:
            self.record["end_reason"] = reason
            self._save()

    def _switch_scope(self, scope) -> None:
        self.mark_end("session_scope_changed")
        self.scope = scope
        self.source_ms = self.last = self.lap = self.reference = self.locked_reference = None

    def feedback(self, state, text: str, turn_id: str, *, choice=None) -> dict:
        choice = choice or fuel_feedback_intent(text)
        sample = fuel_observation(state)
        record = self.record
        if (choice is None or not self.active or (state.session_uid, state.session_epoch) != self.scope
                or sample is None or record["playback"]["completed_at"] is None
                or record["telemetry"]["early_lift"] is not None
                or not 0 <= sample.session_time - record["before"]["session_time"] <= 120):
            return {"status": "rejected", "reason": "no_matching_fuel_recommendation", "advice_kind": "fuel"}
        status = "queued"
        stored = next((reply for reply in record["feedback"] if reply["turn_id"] == turn_id), None)
        if stored is not None:
            status = "already_recorded" if stored["choice"] == choice else "rejected"
        elif len(record["feedback"]) < 32:
            record["feedback"].append(dict(choice=choice, turn_id=turn_id, text=text,
                                          session_time_s=sample.session_time, snapshot_id=sample.snapshot_id))
            if not self._save():
                record["feedback"].pop()
                status = "unavailable"
        else:
            status = "unavailable"
        return dict(status=status, reason="fuel_feedback_not_recorded", advice_kind="fuel",
                    recommendation_id=record["recommendation_id"], choice=choice)

    def observe(self, state) -> None:
        scope = state.session_uid, state.session_epoch
        if scope != self.scope:
            self._switch_scope(scope)
        if self.source_ms is not None and state.source_timestamp_ms <= self.source_ms:
            return
        self.source_ms = state.source_timestamp_ms
        if state.raw.get("result_status") in {3, 4, 5, 6, 7}:
            self.mark_end("session_finished_without_verified_fuel_result")
        sample = fuel_observation(state)
        if sample is None:
            if self.lap is not None:
                self.lap.clean = False
            self.last = None
            return
        if self.active and sample.session_time - self.record["before"]["session_time"] > 360:
            self.mark_end("fuel_observation_timeout")
        if self.lap is None:
            self.lap = _FuelLap(sample, sample.distance_m <= 40)
        before = self.last
        if self.lap.start.lap != sample.lap:
            clean_wrap = (before is not None and sample.lap == before.lap + 1 and sample.distance_m <= 40
                          and 0 < sample.session_time - before.session_time <= 1)
            if clean_wrap:
                self._finish_lap(sample)
            self.lap = _FuelLap(sample, clean_wrap)
        elif before is not None:
            gap = sample.session_time - before.session_time
            distance = sample.distance_m - before.distance_m
            if gap < 0 or gap > 1 or distance < 0 or distance > 120 or sample.context != before.context:
                self.lap.clean = False
                self.lap.rolling_lift = None
            elif gap > 0:
                self._lift(before, sample)
        self.last = sample

    def _lift(self, before: FuelSample, sample: FuelSample) -> None:
        if before.throttle >= .5 and sample.throttle <= .08 and sample.brake <= .05 and sample.speed >= 100:
            self.lap.rolling_lift = sample
        lift = self.lap.rolling_lift
        if lift is None:
            return
        distance = sample.distance_m - lift.distance_m
        if sample.throttle > .08 or distance > 160:
            self.lap.rolling_lift = None
        elif sample.brake >= .18:
            self.lap.rolling_lift = None
            if 0 <= distance <= 160 and len(self.lap.lifts) < 64:
                self.lap.lifts.append((sample.distance_m, distance, lift))

    def _finish_lap(self, following: FuelSample) -> None:
        lap = self.lap
        usage = lap.start.fuel_kg - following.fuel_kg
        duration = following.session_time - lap.start.session_time
        if not lap.clean or lap.start.context != following.context or not .05 <= usage <= 10 or duration < 20:
            return
        if self.active:
            self._compare(lap, usage, duration)
        self.reference = lap, usage, duration

    def _compare(self, lap, usage, duration) -> None:
        reference = self.locked_reference
        record = self.record
        if (reference is None or record["playback"]["completed_at"] is None
                or lap.start.session_time < record["before"]["session_time"]):
            return
        base_lap, base_usage, base_duration = reference
        if (lap.start.context != base_lap.start.context or abs(duration - base_duration) > base_duration * .1):
            return
        for brake_at, coast_distance, lift in lap.lifts:
            matches = [old_coast for old_brake, old_coast, _ in base_lap.lifts
                       if abs(brake_at - old_brake) <= 35]
            if len(matches) != 1 or coast_distance < matches[0] + 20:
                continue
            record["telemetry"]["early_lift"] = dict(snapshot_id=lift.snapshot_id,
                                                      session_time_s=lift.session_time,
                                                      coast_distance_m=coast_distance, baseline_coast_m=matches[0])
            record["outcome"] = dict(measured="fuel_used_per_clean_lap", baseline_lap=base_lap.start.lap,
                                     observed_lap=lap.start.lap, baseline_kg=round(base_usage, 3),
                                     observed_kg=round(usage, 3), delta_kg=round(base_usage - usage, 3))
            feedback = record["feedback"]
            record["adopted"] = bool(feedback and feedback[-1]["choice"] == "accept"
                                     and feedback[-1]["session_time_s"] < lift.session_time)
            self.mark_end("fuel_comparison_observed")
            return

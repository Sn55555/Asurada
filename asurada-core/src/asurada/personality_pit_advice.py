"""Evidence for following up on an audible tyre-based pit recommendation."""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean

from .assessment import valid_percentage
from .input_quality import valid_input

FOLLOW_UP_SECONDS = 12
CONFIRM_SECONDS = 2
MAX_SAMPLE_GAP_SECONDS = 3
UPDATE_WINDOW_SECONDS = 10


@dataclass(frozen=True)
class TyreObservation:
    time_s: float
    wear: tuple[float, ...]
    compound: str
    age_laps: int
    fitted: int | None
    stops: int
    pit: int
    verdict: str


def tyre_observation(state) -> TyreObservation | None:
    raw, tyre = state.raw, state.player.tyre
    wear = raw.get("tyres_wear_pct")
    clock = raw.get("session_time_s")
    pit, stops = raw.get("pit_status_code"), raw.get("num_pit_stops")
    if (state.assessment is None or raw.get("result_status") != 2 or raw.get("session_paused")
            or type(clock) not in (int, float) or not math.isfinite(clock) or clock < 0
            or pit not in (0, 1, 2) or type(stops) is not int or stops < 0
            or type(tyre.age_laps) is not int or tyre.age_laps < 0
            or not tyre.compound or tyre.compound.casefold() == "unknown"
            or not isinstance(wear, (list, tuple)) or len(wear) != 4):
        return None
    values = tuple(valid_percentage(value) for value in wear)
    if None in values or valid_percentage(tyre.wear_pct) is None or abs(mean(values) - tyre.wear_pct) > .01:
        return None
    sets = raw.get("tyre_sets")
    fitted = sets.get("fitted_idx") if isinstance(sets, dict) and sets.get("car_index") == state.player.car_index else None
    return TyreObservation(clock, values, tyre.compound, tyre.age_laps,
                           fitted if type(fitted) is int and 0 <= fitted < 20 else None,
                           stops, pit, state.assessment.labels.tyre_state)


def safe_pit_follow_up(state) -> bool:
    if state.assessment is None:
        return False
    labels = state.assessment.labels
    brake = valid_input("brake", state.raw.get("brake"))
    steer = valid_input("steer", state.raw.get("steer"))
    return (labels.race_state == "green" and labels.dynamics_state == "stable"
            and brake is not None and brake <= .18 and steer is not None and abs(steer) <= .15)


class PersonalityPitAdvice:
    def __init__(self) -> None:
        self.current: TyreObservation | None = None
        self.original: TyreObservation | None = None
        self.original_output_id: str | None = None
        self.saw_pit = False
        self.risk_since: float | None = None
        self.recovery: tuple[str, float, int] | None = None
        self.update: tuple[str, float] | None = None
        self.insisted = False
        self.acknowledged = False

    def observe(self, sample: TyreObservation | None) -> None:
        previous = self.current
        if previous is not None and sample is not None and sample.time_s == previous.time_s:
            return
        if previous is not None and sample is not None and sample.time_s < previous.time_s:
            self.__init__()
            previous = None
        self.current = sample
        if self.original is None:
            return
        if sample is None:
            self.recovery = None
            self.risk_since = None
            return
        time_s = sample.time_s
        continuous = previous is not None and time_s - previous.time_s <= MAX_SAMPLE_GAP_SECONDS
        self.saw_pit |= sample.pit != 0 or sample.stops > self.original.stops
        if self.update is not None:
            if time_s - self.update[1] > UPDATE_WINDOW_SECONDS or sample.verdict != "stable" or sample.pit:
                self.retire()
            return
        if sample.verdict == "box_now" and not sample.pit:
            if self.same_stint(sample):
                self.risk_since = (self.risk_since if continuous and self.risk_since is not None else time_s)
                self.recovery = None
            else:
                self.retire()
            return
        self.risk_since = None
        kind = self.recovery_kind(sample)
        if kind is None:
            self.recovery = None
            return
        if not continuous or self.recovery is None or self.recovery[0] != kind:
            self.recovery = (kind, time_s, 1)
            return
        _, since, count = self.recovery
        self.recovery = (kind, since, count + 1)
        if time_s - since >= CONFIRM_SECONDS and count >= 2:
            if kind == "unverified":
                self.retire()
            else:
                self.update = (kind, time_s)

    def same_stint(self, sample: TyreObservation) -> bool:
        original = self.original
        return (not self.saw_pit and sample.compound == original.compound and sample.age_laps >= original.age_laps
                and (original.fitted is None or sample.fitted is None or original.fitted == sample.fitted))

    def recovery_kind(self, sample: TyreObservation) -> str | None:
        if sample.verdict != "stable" or sample.pit:
            return None
        original = self.original
        fitted_changed = original.fitted is not None and sample.fitted is not None and original.fitted != sample.fitted
        if self.saw_pit and (fitted_changed or sample.compound != original.compound or sample.age_laps < original.age_laps):
            return "revise"
        same_fitted = original.fitted is not None and original.fitted == sample.fitted
        if (self.same_stint(sample) and same_fitted
                and all(before - after >= 10 for before, after in zip(original.wear, sample.wear))):
            return "admit"
        return "unverified"

    def original_completed(self, original: TyreObservation, output_event_id: str) -> None:
        sample = self.current
        if (self.original is None and sample is not None
                and 0 <= sample.time_s - original.time_s <= UPDATE_WINDOW_SECONDS):
            self.original = original
            self.original_output_id = output_event_id
            self.saw_pit = (sample.pit != 0 or sample.stops > original.stops)
            if sample.verdict == "box_now" and self.same_stint(sample) and not sample.pit:
                self.risk_since = sample.time_s

    def acknowledge(self, output_event_id: str) -> bool:
        if self.original is None or self.original_output_id != output_event_id:
            return False
        self.acknowledged = True
        return True

    def due(self) -> str | None:
        sample = self.current
        if sample is None or sample.pit:
            return None
        if self.update is not None:
            return self.update[0]
        if (not self.insisted and not self.acknowledged and self.risk_since is not None
                and sample.time_s - self.risk_since >= FOLLOW_UP_SECONDS):
            return "insist"
        return None

    def withdraws_repeat(self) -> bool:
        sample = self.current
        return sample is not None and (sample.pit != 0 or sample.verdict != "box_now" or self.original is None)

    def retire(self) -> None:
        self.original = None
        self.original_output_id = None
        self.saw_pit = False
        self.risk_since = None
        self.recovery = None
        self.update = None
        self.insisted = False
        self.acknowledged = False

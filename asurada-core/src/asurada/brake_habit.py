"""Build a personal braking reference from observed, comparable corner passes."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from functools import lru_cache
from statistics import median

from .input_quality import valid_input
from .personality_runtime import RACE_SESSIONS
from .track_model import load_track_profile

BRAKE_ON = .18
MAX_SNAPSHOT_GAP_S = .30
MIN_LAPS_PER_SESSION = 3


@lru_cache(maxsize=32)
def track_profile(track):
    return load_track_profile(track)


def race_context(state):
    raw = state.raw
    return (
        raw.get("session_type") in RACE_SESSIONS
        and raw.get("result_status") == 2
        and raw.get("pit_status_code") == 0
        and not raw.get("session_paused")
        and state.safety_car in (None, "NONE")
        and raw.get("track_status") in (None, 0, 1, "GREEN")
        and raw.get("marshal_zone_flag") in (None, 0, 1)
        and not any(tag in {"unstable", "unavailable"} for tag in state.player.status_tags)
    )


def race_time(state):
    value = state.raw.get("session_time_s")
    return float(value) if type(value) in (int, float) and 0 <= value < float("inf") else None


@dataclass(frozen=True)
class BrakePass:
    session: str
    epoch: int
    lap: int
    track: str
    corner: str
    weather: str
    tyre: str
    onset_m: float
    first_source_ms: int
    brake_source_ms: int
    end_source_ms: int
    uncertainty_m: float


@dataclass
class _Pass:
    key: tuple
    first_ms: int
    onset: float | None = None
    onset_ms: int | None = None
    uncertainty: float | None = None
    brake_confirmed: bool = False


class BrakeProbe:
    def __init__(self):
        self.previous = None
        self.active = None

    def reset(self):
        self.previous = self.active = None

    def observe(self, state):
        now = race_time(state)
        position = state.player.lap_distance_m
        brake = valid_input("brake", state.raw.get("brake"))
        quality = (state.raw.get("input_quality") or {}).get("brake", {})
        weather, tyre = state.weather, state.player.tyre.compound
        front_gap = state.player.gap_ahead_s
        if (not race_context(state) or type(state.raw.get("marshal_zone_flag")) is not int
                or state.raw["marshal_zone_flag"] not in (0, 1)
                or now is None or type(position) not in (int, float)
                or not 0 <= position < float("inf") or brake is None
                or quality.get("quality") != "observed" or quality.get("source") != "CarTelemetry"
                or type(quality.get("observed_at_ms")) not in (int, float)
                or abs(quality["observed_at_ms"] - state.source_timestamp_ms) > 300
                or not weather or not tyre or "unknown" in (weather.lower(), tyre.lower())
                or (front_gap is None and state.player.position != 1)
                or (front_gap is not None and not front_gap >= 2)):
            self.reset()
            return None
        key = (state.session_uid, state.session_epoch, state.lap_number, state.track, weather, tyre)
        sample = (key, now, position, brake, state.source_timestamp_ms, quality["observed_at_ms"])
        prior, self.previous = self.previous, sample
        if (prior is None or prior[0] != key or not 0 < now - prior[1] <= MAX_SNAPSHOT_GAP_S
                or not 0 <= position - prior[2] <= 30 or state.source_timestamp_ms <= prior[4]
                or not 0 < sample[5] - prior[5] <= 300):
            self.active = None
            return None
        if self.active is None:
            profile = track_profile(state.track)
            if profile is None:
                return None
            for zone in profile.semantic_segments:
                if (zone.zone_type == "braking_entry" and zone.start_m >= 25
                        and prior[2] <= zone.start_m - 25 < position <= zone.start_m
                        and prior[3] < BRAKE_ON):
                    self.active = (zone, _Pass(key, prior[4]))
                    break
        if self.active is None:
            return None
        zone, observed = self.active
        if observed.onset is None and prior[3] < BRAKE_ON <= brake and position <= zone.end_m:
            span = position - prior[2]
            observed.onset = prior[2] + span * (BRAKE_ON - prior[3]) / (brake - prior[3])
            observed.onset_ms = state.source_timestamp_ms
            observed.uncertainty = span
        elif observed.onset is not None and not observed.brake_confirmed:
            if brake >= BRAKE_ON:
                observed.brake_confirmed = True
            else:
                observed.onset = None
        if position <= zone.end_m:
            return None
        self.active = None
        if observed.brake_confirmed:
            return BrakePass(*key[:4], zone.name, weather, tyre, round(observed.onset, 2),
                             observed.first_ms, observed.onset_ms, state.source_timestamp_ms,
                             round(observed.uncertainty, 2))
        return None


def verified_reference(passes):
    """Select one well-covered corner and retain an independent validation race."""
    cases = defaultdict(lambda: defaultdict(dict))
    for item in passes:
        key = (item.track, item.corner, item.weather, item.tyre)
        cases[key][item.session][item.lap] = item
    eligible = []
    for key, sessions in cases.items():
        ordered = sorted((tuple(laps.values()) for laps in sessions.values() if len(laps) >= MIN_LAPS_PER_SESSION),
                         key=lambda run: min(row.first_source_ms for row in run))
        if len(ordered) < 3:
            continue
        training = [item for run in ordered[:-1] for item in run]
        holdout = ordered[-1]
        values = sorted(item.onset_m for item in training)
        center = median(values)
        tolerance = max(12., median(item.uncertainty_m for item in training),
                        2.5 * median(abs(value - center) for value in values))
        low, high = center - tolerance, center + tolerance
        if sum(low <= item.onset_m <= high for item in holdout) * 3 < len(holdout) * 2:
            continue
        eligible.append((len(training), key, {
            "track": key[0], "corner": key[1], "weather": key[2], "tyre": key[3],
            "onset_low_m": round(low, 2), "onset_high_m": round(high, 2),
            "training": [asdict(item) for item in training],
            "holdout": [asdict(item) for item in holdout],
        }))
    if not eligible:
        return None
    return sorted(eligible, key=lambda row: (-row[0], row[1]))[0][2]

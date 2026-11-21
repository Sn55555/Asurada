"""Short-lived speech opportunities derived from the current strategy decision."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math

from .attack_outcome import AttackRun, LINES
from .battle_speech import front_runway, phrase_seconds
from .assessment import assess_domain
from .input_quality import valid_input
from .models import SessionState
from .track_model import load_track_profile
from .wing_damage import FRONT_WING_DAMAGE, covered_wing_damage

_WORD_BUDGET_S = {"forming": 2.1, "actionable": 1.35}
_ACTION_STABILITY_S = .30
FORECAST_DRIVER_MARGIN_S = 1.
_FORECAST_MIN_GATE_S = 4.
_HARD_BLOCKS = frozenset({"SAFETY_CAR", "DYNAMICS_UNSTABLE", "RED_FLAG", "BOX_NOW", "PIT_NOW", "BOX_WINDOW",
                          "TYRE_DAMAGE", "TYRE_WEAR_ALERT", "FRONT_WING_DAMAGE", "LOW_FUEL", "ERS_LOW", "DEFEND_WINDOW"})


def front_target(state: SessionState):
    targets = [rival for rival in state.rivals if rival.position == state.player.position - 1]
    return targets[0] if len(targets) == 1 else None


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def forecast_on_approach(state, forecast):
    """The call belongs to this straight or its immediate traction exit."""
    distance = _number(state.player.lap_distance_m)
    profile = load_track_profile(state.track)
    if profile is None or distance is None or not 0 <= distance < profile.lap_length_m:
        return False
    remaining = (forecast["gate_lap"] - state.player.lap) * forecast["length_m"] + forecast["gate_m"] - distance
    zone = profile.classify(distance).zone_type
    lead_in = remaining - forecast["straight_m"]
    return (0 < remaining and (zone == "deployment_straight" and lead_in <= 0
                              or zone == "exit_traction" and 0 < lead_in <= 35))


def _drs_call_location(state, *, starting=True):
    """Use the player's explicit permission and wing state, never predicted eligibility."""
    opened = state.raw.get("drs_open")
    if type(opened) is not bool or (starting and opened):
        return None
    if state.raw.get("forecast_drs_allowed") is not True and (starting or not opened):
        return None
    profile = load_track_profile(state.track)
    distance = _number(state.player.lap_distance_m)
    if profile is None or distance is None or not 0 <= distance < profile.lap_length_m:
        return None
    zone = profile.classify(distance)
    if zone.zone_type != "deployment_straight":
        return None
    return "主直道" if zone.zone_name == "Main Straight" else "这条直道"


def _block(state, code, *, playing=False):
    assessment = (state.assessment or assess_domain(state)).labels
    if state.raw.get("session_paused") or state.raw.get("result_status") != 2:
        return "not_racing"
    if state.raw.get("marshal_zone_flag") == 3:
        return "safety_or_pressure"
    if ((code != "DEFEND_WINDOW" and code in _HARD_BLOCKS) or assessment.race_state != "green"
            or assessment.dynamics_state != "stable" or state.raw.get("pit_status_code") != 0):
        return "safety_or_pressure"
    brake = valid_input("brake", state.raw.get("brake"))
    steer = valid_input("steer", state.raw.get("steer"))
    # A mild steering correction closes admission, but an already audible call
    # still has value while the same forecast holds. Braking and hard turns win.
    steer_limit = .35 if playing else .16
    if brake is None or steer is None or brake > .18 or abs(steer) > steer_limit:
        return "driver_busy"
    if assessment.defend_state == "urgent" or code == "DEFEND_WINDOW":
        return "rear_pressure"
    if assessment.defend_state != "clear":
        return "safety_or_pressure"
    return None


@dataclass(frozen=True)
class WindowSample:
    front: int
    position: int
    lap: int
    segment: str
    time: float
    gap: float
    distance: float
    latest_m: float
    latest_s: float


def _sample(state, code, segment):
    blocked = _block(state, code)
    if blocked:
        return None, blocked
    front = front_target(state)
    gap = _number(state.player.gap_ahead_s)
    if (front is None or front.pit_status in {"PITTING", "IN_PIT_AREA"}
            or state.player.gap_confidence_ahead != "high" or gap is None or not 0 < gap <= 1.6):
        return None, "front_gap_unavailable"
    distance = _number(state.player.lap_distance_m)
    speed = _number(state.player.speed_kph)
    clock = _number(state.raw.get("session_time_s"))
    profile = load_track_profile(state.track)
    if profile is None or distance is None or speed is None or speed <= 0 or clock is None or clock < 0:
        return None, "position_unavailable"
    zone = next((zone for zone in profile.semantic_segments
                 if zone.name == segment and zone.start_m <= distance < zone.end_m), None)
    if zone is None or zone.zone_type not in {"straight", "deployment_straight", "exit_traction"}:
        return None, "segment_unavailable"
    latest_m = min([zone.end_m, *(b.start_m for b in profile.braking_zones if distance <= b.start_m <= zone.end_m)])
    return WindowSample(front.car_index, state.player.position, state.lap_number, segment, clock, gap, distance,
                        latest_m, clock + (latest_m - distance) * 3.6 / speed), None


@dataclass
class Opportunity:
    identity: str
    sample: WindowSample
    state: str
    started: set[str] = field(default_factory=set)
    delivered: bool = False
    closed_at: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class OpportunityCue:
    state: str
    text: str
    metadata: dict


class AttackOpportunities:
    def __init__(self):
        self.scope = None
        self.sequence = 0
        self.history = deque(maxlen=256)
        self.current: Opportunity | None = None
        self.previous: Opportunity | None = None
        self._actionable_since: float | None = None
        self.reason: str | None = None
        self.run: AttackRun | None = None
        self.outcome = None
        self.outcome_started = False
        self.tracked_window = None
        self.forecast_seen = deque(maxlen=24)
        self.forecast_key = self.forecast_since = self.forecast_last = None
        self.last_busy = None

    def _close(self, state, reason, now):
        window = self.current
        if window is None:
            return
        passed = (state.player.position < window.sample.position and any(
            rival.car_index == window.sample.front and rival.position > state.player.position for rival in state.rivals))
        window.state = "closed"
        window.closed_at, window.reason = now, ("order_changed" if passed else reason)
        self.previous, self.current = window, None

    def observe(self, state, decision, *, completed_wing=None) -> OpportunityCue | None:
        if self.scope != (state.session_uid, state.session_epoch):
            self.last_busy = None
            self.forecast_seen.clear()
            self.forecast_key = self.forecast_since = self.forecast_last = None
            self.run = self.outcome = self.tracked_window = None
            self.outcome_started = False
        cue = self._observe_window(state, decision)
        window = self.current
        now = _number(state.raw.get("session_time_s"))
        if window and window.state == "actionable" and self.tracked_window != window.identity and now is not None:
            # One inference per action window, independent of playback and driver speech.
            if self.run is not None:
                decision.debug["superseded_attack_outcome"] = self.run.result("uncertain", "new_window", now)
            self.tracked_window = window.identity
            self.run = AttackRun(window.identity, window.sample.front, state.player.car_index,
                                 window.sample.position, state.lap_number, now, window.sample.latest_m)
            self.outcome = None
            self.outcome_started = False
        if self.run is not None:
            self.outcome = self.run.observe(state, now)
            if self.outcome is not None:
                decision.debug["attack_outcome"] = self.outcome
                self.run = None
        outcome = self.outcome
        if cue and cue.state == "withdrawal" and self._engaged(cue.metadata["id"]):
            cue = None
        if (outcome and outcome["verdict"] == "passed" and self.previous
                and self.previous.identity == outcome["window_id"]):
            self.previous.state, self.previous.reason = "fulfilled", "confirmed_overtake"
        forecast = self._forecast_cue(state, decision, completed_wing)
        if forecast and (cue is None or cue.state == "forming"):
            return forecast
        if cue is not None or not outcome or self.outcome_started or not outcome["samples"]:
            return cue
        metadata = dict(id=outcome["window_id"], front_car_index=outcome["target"], phase="outcome",
                        lap=outcome["lap"], observed_s=outcome["observed_s"],
                        latest_useful_s=outcome["observed_s"] + 3, outcome=outcome)
        code = decision.messages[0].code if decision.messages else "NONE"
        if validate_attack_cue(metadata, state, code):
            return OpportunityCue("outcome", LINES[outcome["verdict"]], metadata)
        return None

    def _forecast_cue(self, state, decision, completed_wing):
        now = _number(state.raw.get("session_time_s"))
        brake = valid_input("brake", state.raw.get("brake"))
        steer = valid_input("steer", state.raw.get("steer"))
        if brake is None or steer is None or brake > .18 or abs(steer) > .16:
            self.last_busy = now
        forecast = decision.debug.get("attack_forecast") or {}
        if not forecast.get("recommended") or not forecast_on_approach(state, forecast):
            self.forecast_key = self.forecast_since = None
            return None
        now, identity = forecast["clock_s"], forecast["id"]
        code = decision.messages[0].code if decision.messages else "NONE"
        blocked = _block(state, forecast_primary(state, code, completed_wing or {}))
        if blocked == "rear_pressure":
            self.last_busy = now
        if blocked:
            self.forecast_key = self.forecast_since = None
            return None
        if (
            identity != self.forecast_key
            or self.forecast_last is None
            or not 0 <= now - self.forecast_last <= 0.65
        ):
            self.forecast_key, self.forecast_since = identity, now
        self.forecast_last = now
        if (identity in self.forecast_seen or now - self.forecast_since < 0.4
                or self.last_busy is not None and 0 <= now - self.last_busy < 1.0):
            return None
        target = front_target(state)
        if target is None or target.car_index != forecast["target"]:
            return None
        location = _drs_call_location(state)
        if location is None:
            return None
        words = f"{location}，开尾翼"
        meta = dict(
            id=identity,
            phase="forecast",
            front_car_index=forecast["target"],
            lap=state.lap_number,
            observed_s=now,
            latest_useful_s=now + min(3.0, forecast["eta_s"] - 1.0),
            forecast=forecast,
            completed_wing=dict(completed_wing or {}),
            key_phrase=words,
            key_seconds=phrase_seconds(words) + .35,  # Include the pause between location and action.
            drs_location=location,
            speech_deadline=now + front_runway(state, target, forecast),
        )
        if not validate_attack_cue(meta, state, code):
            return None
        return OpportunityCue("forecast", words + "。", meta)

    def _observe_window(self, state, decision) -> OpportunityCue | None:
        scope = (state.session_uid, state.session_epoch)
        if scope != self.scope:
            self.scope, self.current, self.previous = scope, None, None
            self.history.clear()
            self._actionable_since = None
        code = decision.messages[0].code if decision.messages else "NONE"
        context = decision.debug.get("context") or {}
        segment = context.get("track_segment")
        now = _number(state.raw.get("session_time_s"))
        sample, reason = _sample(state, code, segment)
        self.reason = reason
        if sample is not None and self.history:
            previous = self.history[-1]
            if (sample.front, sample.lap, sample.segment) != (previous.front, previous.lap, previous.segment):
                self._close(state, "target_or_segment_changed", now)
                self.history.clear()
                self._actionable_since = None
            elif sample.time < previous.time or sample.distance < previous.distance:
                self._close(state, "telemetry_rewind", now)
                self.previous = None
                self.history.clear()
                self._actionable_since = None
            elif sample.time - previous.time > .55:
                self._close(state, "telemetry_gap", now)
                self.previous = None
                self.history.clear()
                self._actionable_since = None
        if sample is None:
            self._close(state, reason, now)
            self.history.clear()
            self._actionable_since = None
            return self._withdrawal(state, code, now)
        if not self.history or sample.time > self.history[-1].time:
            self.history.append(sample)
        remaining = sample.latest_s - sample.time
        if code != "ATTACK_WINDOW":
            self._actionable_since = None
        elif self._actionable_since is None:
            self._actionable_since = sample.time
        actionable = (self._actionable_since is not None and sample.time - self._actionable_since >= _ACTION_STABILITY_S
                      and remaining >= _WORD_BUDGET_S["actionable"])
        setup_method = context.get("attack_setup_method") or "none"
        comparable = [row for row in self.history if 0 <= sample.time - row.time <= 2.5]
        forming = (setup_method != "none" and len(comparable) >= 3
                   and sample.time - comparable[0].time >= .45
                   and comparable[0].gap - sample.gap >= .15
                   and len({round(row.gap, 2) for row in comparable}) >= 3
                   and remaining >= _WORD_BUDGET_S["forming"])
        current = self.current
        if current is not None and (remaining <= 0 or current.state == "actionable" and code != "ATTACK_WINDOW"
                                    or current.state == "forming" and not forming and code != "ATTACK_WINDOW"):
            self._close(state, "window_closed", now)
            # Reopening requires distinct evidence following closure.
            self.history.clear()
            self._actionable_since = None
            return self._withdrawal(state, code, now)
        withdrew = self._withdrawal(state, code, now)
        if withdrew is not None:
            return withdrew
        if current is None:
            if not (forming or actionable) or len(comparable) < 3:
                self.reason = "awaiting_stable_opportunity"
                return None
            if (self.previous is not None and self.previous.sample.front == sample.front
                    and self.previous.sample.lap == sample.lap and self.previous.sample.segment == sample.segment):
                return None
            self.sequence += 1
            current = self.current = Opportunity(f"{scope[0]}:{scope[1]}:attack:{self.sequence}", sample, "forming")
        if actionable:
            current.state = "actionable"
        elif not forming:
            return None
        current.sample = sample
        if current.state in current.started or remaining < _WORD_BUDGET_S[current.state]:
            return None
        words = "可以准备进攻。" if current.state == "actionable" else "先跟住。"
        return OpportunityCue(current.state, words, self._metadata(current, sample.time))

    def snapshot(self):
        window = self.current or self.previous
        return {"reason": self.reason, "window_id": window.identity if window else None,
                "phase": window.state if window else None, "close_reason": window.reason if window else None,
                "front_car_index": window.sample.front if window else None,
                "outcome": self.outcome,
                "action_completed": window.delivered if window else False}

    @staticmethod
    def _metadata(window, now):
        sample = window.sample
        return {"id": window.identity, "phase": window.state, "front_car_index": sample.front, "lap": sample.lap,
                "segment": sample.segment, "observed_s": now, "latest_lap_distance_m": sample.latest_m,
                "latest_useful_s": sample.latest_s, "gap_s": sample.gap,
                "reason": window.reason}

    def _withdrawal(self, state, code, now):
        previous = self.previous
        if (previous is None or not previous.delivered or previous.state != "closed"
                or "withdrawal" in previous.started or now is None or previous.closed_at is None
                or not 0 <= now - previous.closed_at <= 2 or previous.sample.lap != state.lap_number
                or previous.reason in {"driver_busy", "order_changed"} or _block(state, code) not in {None, "rear_pressure"}):
            return None
        text = "先守后车。" if previous.reason == "rear_pressure" else "先别攻，窗口关了。"
        metadata = self._metadata(previous, now)
        metadata.update(phase="withdrawal", latest_useful_s=previous.closed_at + 2)
        return OpportunityCue("withdrawal", text, metadata)

    def owns_overtake_announcement(self, hint):
        if hint is None or hint.opportunity != "overtake" or hint.opportunity_age_s is None:
            return False
        event_s = self.run.event_s if self.run else (self.outcome or {}).get("overtake_event_s")
        return event_s is not None and abs(hint.clock_s - hint.opportunity_age_s - event_s) < 1e-4

    def on_started(self, job):
        metadata = job.metadata.get("attack_opportunity")
        if metadata and metadata["phase"] == "forecast":
            self.forecast_seen.append(metadata["id"])
        elif metadata and metadata["phase"] == "outcome":
            self.outcome_started = True
        elif metadata:
            for window in (self.current, self.previous):
                if window is not None and window.identity == metadata["id"]:
                    window.started.add(metadata["phase"])

    def on_completed(self, job):
        metadata = job.metadata.get("attack_opportunity")
        if metadata and metadata["phase"] == "actionable":
            for window in (self.current, self.previous):
                if window is not None and window.identity == metadata["id"]:
                    window.delivered = True

    def _engaged(self, identity):
        if self.run and self.run.window_id == identity:
            return self.run.alongside_since is not None or self.run.attempt_s is not None
        return (self.outcome is not None and self.outcome["window_id"] == identity
                and (self.outcome["attempt_s"] is not None or self.outcome["verdict"] == "passed"))

    def still_current(self, metadata, *, starting=True):
        if metadata["phase"] == "forecast":
            return self.forecast_key == metadata["id"] and (not starting or metadata["id"] not in self.forecast_seen)
        if metadata["phase"] == "outcome":
            return self.outcome is not None and self.outcome["window_id"] == metadata["id"]
        if metadata["phase"] == "withdrawal":
            return self.previous is not None and self.previous.identity == metadata["id"] and not self._engaged(metadata["id"])
        return (self.current is not None and self.current.identity == metadata["id"]
                and (self.current.state == metadata["phase"]
                     or not starting and self.current.state == "actionable" and metadata["phase"] == "forming"))


@dataclass
class PlayingForecast:
    """Bridge one absent gap measurement on an already playing forecast."""
    observed_s: float
    gap_s: float
    missing_at: float | None = None
    recovered_at: float | None = None

    def supported(self, state, metadata, forecast, *, rear=False):
        now = _number(state.raw.get("session_time_s"))
        if now is None or now < self.observed_s:
            return False
        gap = _number(state.player.gap_behind_s if rear else state.player.gap_ahead_s)
        confidence = state.player.gap_confidence_behind if rear else state.player.gap_confidence_ahead
        if forecast is not None:
            if forecast["id"] != metadata["id"] or not forecast["recommended"] or gap is None:
                return False
            self.observed_s, self.gap_s = now, gap
            self.missing_at = self.recovered_at = None
            return True
        if now - self.observed_s > .25:
            return False
        if gap is None:
            if self.missing_at is None:
                self.missing_at = self.observed_s = now
            return self.recovered_at is None and self.missing_at == now
        # After a missing sample the strategy requires 1.5 seconds of fresh timing.
        # Continue only within the previously observed gap or the strategy's close-following range.
        limit = max(self.gap_s, .38)
        if self.missing_at is None or not 0 < gap <= limit or confidence != "high":
            return False
        if self.recovered_at is None:
            if not 0 < now-self.missing_at <= .25:
                return False
            self.recovered_at = now
        self.observed_s = now
        return now-self.recovered_at <= 1.5


def forecast_primary(state, code, completed_wing):
    if code == FRONT_WING_DAMAGE and covered_wing_damage(state, completed_wing):
        return "NONE"
    return code


def validate_attack_cue(metadata, state, code, *, starting=True, single_gap=False, completed_wing=None,
                        delivery_delay_s=0.):
    now = _number(state.raw.get("session_time_s"))
    deadline = metadata["latest_useful_s"]
    if metadata["phase"] in {"outcome","forecast"} and not starting:
        deadline += 2  # Allow an already audible short line to finish while the context is valid.
    if now is None or not metadata["observed_s"] <= now or now + delivery_delay_s >= deadline:
        return False
    if starting and metadata["phase"] in {"forming", "actionable", "forecast"}:
        car = front_target(state)
        margin = FORECAST_DRIVER_MARGIN_S if metadata["phase"] == "forecast" else .3
        required = metadata.get("key_seconds", 1.) + margin + delivery_delay_s
        if car is None or front_runway(state, car, metadata.get("forecast")) < required:
            return False
        if metadata.get("speech_deadline", float("inf")) - now < required:
            return False
    if metadata["phase"] == "forecast":
        f = metadata["forecast"]
        levels = metadata.get("completed_wing", {}) if completed_wing is None else completed_wing
        code = forecast_primary(state, code, levels)
        car = front_target(state)
        d = _number(state.player.lap_distance_m)
        speed = _number(state.player.speed_kph)
        if (not car or car.car_index != f["target"] or car.pit_status != "NONE" or not speed or d is None
                or not metadata.get("drs_location") or _drs_call_location(state, starting=starting) != metadata["drs_location"]
                or _block(state, code, playing=not starting) or state.raw.get("marshal_zone_flag") not in (0,1,None)
                or code not in ("NONE","ATTACK_WINDOW") or state.safety_car != "NONE"
                or ((state.raw.get("forecast_lap_times") or {}).get(str(car.car_index)) or {}).get("current_lap_invalid")
                or state.raw.get("current_lap_invalid")
                or (not single_gap and (state.player.gap_confidence_ahead != "high"
                                        or _number(state.player.gap_ahead_s) is None))):
            return False
        remaining = (f["gate_lap"]-state.player.lap)*f["length_m"] + f["gate_m"]-d
        return (0 < remaining <= f["remaining_m"]+5 and forecast_on_approach(state, f)
                and (not starting or remaining/(speed/3.6) >= max(required, _FORECAST_MIN_GATE_S)))
    if metadata["phase"] == "outcome":
        evidence = metadata["outcome"]
        if evidence["verdict"] != "uncertain":
            target = next((r for r in state.rivals if r.car_index == evidence["target"]), None)
            if (target is None or target.pit_status != "NONE" or
                    [state.player.position, target.position] != evidence["positions"]):
                return False
        return (code == "NONE" and state.lap_number == metadata["lap"] and _block(state, code) is None
                and state.raw.get("marshal_zone_flag") in (0, 1))
    if metadata["phase"] == "withdrawal":
        return state.lap_number == metadata["lap"] and _block(state, code) in {None, "rear_pressure"}
    sample, _ = _sample(state, code, metadata["segment"])
    return (sample is not None and sample.front == metadata["front_car_index"] and sample.lap == metadata["lap"]
            and (not starting or sample.latest_s - now >= _WORD_BUDGET_S[metadata["phase"]])
            and (metadata["phase"] != "actionable" or code == "ATTACK_WINDOW"))

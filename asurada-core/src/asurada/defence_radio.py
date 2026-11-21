"""Speech eligibility for one identified pursuer. Forecasts never consume race outcomes."""

from collections import deque

from .assessment import assess_domain
from .defence_field import rear_gap_view
from .defence_history import DefenceHistory
from .track_model import load_track_profile
from .attack_forecast import number
from .attack_opportunity import forecast_primary
from .attack_outcome import relative_position
from .input_quality import valid_input
from .defence_approach import DefenceApproach, PursuitPace, track_gap, within_defence_horizon


def rear_target(state):
    targets = [r for r in state.rivals if r.position == state.player.position + 1]
    return targets[0] if len(targets) == 1 else None


def applicable(meta, state, primary, *, starting=True, completed_wing=None, bridge_geometry=False):
    state, rear = rear_gap_view(state, meta["target"])
    if state is None:
        return False
    now = number(state.raw.get("session_time_s"))
    if (
        now is None
        or not meta["clock_s"] <= now <= meta["clock_s"] + (1 if starting else 5)
        or tuple(meta["scope"]) != (state.session_uid, state.session_epoch)
        or rear is None
        or rear.car_index != meta["target"]
        or rear.pit_status != "NONE"
    ):
        return False
    if starting and meta.get("speech_deadline", float("inf")) - now < meta.get("key_seconds", 0) + 1.:
        return False
    levels = meta["completed_wing"] if completed_wing is None else completed_wing
    code = forecast_primary(state, primary, levels)
    labels = (state.assessment or assess_domain(state)).labels
    if (
        code not in {"NONE", "DEFEND_WINDOW", "ATTACK_WINDOW"}
        or state.safety_car != "NONE"
        or state.raw.get("result_status") != 2
        or state.raw.get("session_paused")
        or state.raw.get("pit_status_code") != 0
        or state.raw.get("marshal_zone_flag") not in (0, 1, None)
        or labels.race_state != "green"
        or labels.dynamics_state != "stable"
    ):
        return False
    gap = state.player.gap_behind_s
    if not (gap is None and not starting) and (
        number(gap) is None or not 0 < gap < 10 or state.player.gap_confidence_behind != "high"
    ):
        return False
    f = meta.get("forecast")
    if f:
        if f["target"] != rear.car_index or state.raw.get("current_lap_invalid"):
            return False
        distance, speed = number(state.player.lap_distance_m), number(state.player.speed_kph)
        if distance is None or speed is None or speed <= 0:
            return False
        remaining = (f["gate_lap"] - state.player.lap) * f["length_m"] + f["gate_m"] - distance
        if not 0 < remaining <= f["remaining_m"] + 5 or starting and remaining / (speed / 3.6) < 3.5:
            return False
        if starting:
            brake, steer = (
                valid_input("brake", state.raw.get("brake")),
                valid_input("steer", state.raw.get("steer")),
            )
            if brake is None or steer is None or brake > 0.18 or abs(steer) > 0.16:
                return False
    elif meta.get("approach"):
        approach = meta["approach"]
        if starting and "history" in approach:
            brake = valid_input("brake", state.raw.get("brake"))
            steer = valid_input("steer", state.raw.get("steer"))
            if brake is None or steer is None or brake > .18 or abs(steer) > .16:
                return False
        measured = track_gap(state, rear, approach["length_m"])
        if (state.raw.get("current_lap_invalid") or measured is None or measured < 0
                or measured > approach["distance_m"] + 4):
            return False
        remaining = ((approach["gate_lap"] - state.player.lap) * approach["length_m"]
                     + approach["gate_m"] - state.player.lap_distance_m)
        if not 0 < remaining <= approach["remaining_m"] + 4:
            return False
        if starting and (approach["earliest_s"] - (now - meta["clock_s"]) < 1.8
                         or measured < 5):
            return False
    elif meta.get("closing") is not None:
        geo = relative_position(state.player, rear, state.raw.get("world_forward_dir") or {})
        if (geo is None and not bridge_geometry or geo and (
                -geo[0] > meta["closing"]["distance_m"] + 5 or (starting and -geo[0] <= 4))):
            return False
    else:
        return False
    if starting:
        closing = meta.get("closing")
        if closing:
            budget = 3.8 if f else 1.7
            if closing["earliest_s"] - (now - meta["clock_s"]) < budget:
                return False
        geo = relative_position(state.player, rear, state.raw.get("world_forward_dir") or {})
        if f and geo and -geo[0] < 12:
            return False
        if geo and abs(geo[0]) <= 4 and 1.7 <= abs(geo[1]) <= 5:
            return False
    return True


class Pursuer:
    def __init__(self):
        self.gate = self.since = self.latest = None
        self.last_call = {}
        self.samples = deque(maxlen=128)
        self.target = self.last_radio = None
        self.closest_since_call = self.separated_since = None
        self.separated = False
        self.approach = DefenceApproach()
        self.pace = PursuitPace()
        self.last_target = None
        self.spoken = deque(maxlen=40)

    def closing_evidence(self, state, rear, now):
        key = (state.session_uid, state.session_epoch, rear.car_index) if rear else None
        geo = relative_position(state.player, rear, state.raw.get("world_forward_dir") or {}) if rear else None
        distance = -geo[0] if geo else None
        if key != self.target:
            self.closest_since_call = self.separated_since = None
            self.separated = False
        if self.closest_since_call is not None:
            if distance is not None and 0 <= distance <= 250:
                self.closest_since_call = min(self.closest_since_call, distance)
            if distance is not None and distance >= max(50, self.closest_since_call + 25):
                if self.separated_since is None:
                    self.separated_since = now
                self.separated |= now - self.separated_since >= 1
            else:
                self.separated_since = None
        if (key != self.target or not self.samples or not 0 < now - self.samples[-1][0] <= 0.35
                or distance is None or not 4 < distance <= 250 or rear.pit_status != "NONE"):
            self.samples.clear()
        self.target = key
        if distance is None or not 4 < distance <= 250 or rear.pit_status != "NONE":
            return None
        self.samples.append((now, distance))
        while self.samples and now - self.samples[0][0] > 1:
            self.samples.popleft()
        if now - self.samples[0][0] < 0.6:
            return None
        start, middle = self.samples[0], self.samples[len(self.samples) // 2]
        if not start[0] < middle[0] < now:
            return None
        rates = ((start[1] - middle[1]) / (middle[0] - start[0]),
                 (middle[1] - distance) / (now - middle[0]))
        if min(rates) < 2 or max(rates) > 100:
            return None
        # Use the faster half for the speech deadline; both halves must corroborate the threat.
        return dict(distance_m=distance, closing_mps=list(rates),
                    earliest_s=(distance - 4) / max(rates), latest_s=(distance - 4) / min(rates))

    def observe(self, state, r, decision, completed_wing, original, history):
        f = decision.debug.get("defence_forecast")
        if f and f["target"] != r.car_index:
            f = None
        gate = f["id"] if f and f["recommended"] else None
        t = number(state.raw.get("session_time_s"))
        if t is None:
            self.gate = self.latest = None
            return None
        if gate != self.gate or self.latest is None or not 0 <= t - self.latest <= 0.65:
            self.gate, self.since = gate, t
        self.latest = t
        pace = self.pace.observe(state, r, t)
        closing = self.closing_evidence(state, r, t)
        approach = self.approach.observe(state, r, t, f) or history.forecast(state, r, t)
        primary = decision.messages[0].code if decision.messages else "NONE"
        if r is None:
            return None
        # A generic warning can precede a forecast by several corners. New location
        # information is useful once per target and braking point, after a radio pause.
        last = self.last_call.get(r.car_index)
        recent = last is not None and 0 <= t - last < 5
        ready = (
            gate is not None
            and t - self.since >= 0.4
        )
        if ready:
            slope = f.get("trend_s_per_s", 0)
            ready = slope <= 0 or f["gap_s"] / slope >= 3.5
        if closing and closing["earliest_s"] < 3.8:
            ready = False
        # A rank swap or an isolated small gap is insufficient. Re-arm a short call
        # for a different pursuer only when there is time to hear it and react.
        brake = valid_input("brake", state.raw.get("brake"))
        urgent = False
        renewed = False
        if closing and brake is not None:
            # Routine braking compresses the pack. During braking demand a large
            # sustained speed differential before using the radio.
            min_rate = 20 if brake > 0.18 else 9
            renewed = (self.separated and last is not None and t - last >= 8
                       and min(closing["closing_mps"]) >= 20)
            urgent = (min(closing["closing_mps"]) >= min_rate
                      and 0 < closing["earliest_s"] and within_defence_horizon(closing["latest_s"])
                      )
            if urgent and brake > .18:
                # In a braking pack, rotation alone can look like rapid closure.
                # Require independent speed evidence before a generic warning.
                v, rv = number(state.player.speed_kph), number(r.speed_kph)
                urgent = (v is not None and rv is not None and
                          (rv - v) / 3.6 >= .65 * min(closing["closing_mps"]))
            steer = valid_input("steer", state.raw.get("steer"))
            if urgent and (self.pace.braking_recently or brake > .18 or steer is not None and abs(steer) > .16):
                # Compare passage at the same station during braking/turn-in. If
                # the gap in seconds is not closing fast enough to matter in the
                # radio horizon, the pack is merely compressing in metres.
                urgent = bool(pace and pace["gain_per_s"] > 0 and
                              within_defence_horizon(pace["delay_s"] / pace["gain_per_s"]))
        # A car already on the same straight can reach us well before the mapped
        # braking point. Give the actual location precedence over a later corner.
        located = bool(approach)
        if located:
            ready = False
        if not ready and not urgent and not located:
            return None
        # A recommended distant braking point is not a predicted time of overlap.
        # Require a current closure estimate even when a mapped forecast is ready.
        if located:
            eta = approach["earliest_s"]
        elif closing and (urgent or ready) and within_defence_horizon(closing["latest_s"]):
            eta = closing["earliest_s"]
        elif ready and (f.get("trend_s_per_s") or 0) > 0:
            eta = f["gap_s"] / f["trend_s_per_s"]
        else:
            return None
        if not within_defence_horizon(eta) or eta <= 0:
            return None
        gap = state.player.gap_behind_s
        if number(gap) is None or gap <= 0 or gap > 2:
            return None
        place = ""
        if located:
            place = approach["text"].removeprefix("守").rstrip("。")
        elif ready and number(state.player.speed_kph) and abs(f["eta_s"] - eta) * state.player.speed_kph / 3.6 <= 65:
            place = f["label"].removeprefix("前面").replace("长直道尽头", "直道末端")
        else:
            profile = load_track_profile(state.track)
            speed, station = number(state.player.speed_kph), number(state.player.lap_distance_m)
            if profile and speed and station is not None:
                segment = profile.classify(station)
                end = (station + eta * speed / 3.6) % profile.lap_length_m
                if segment.zone_type == "deployment_straight" and profile.classify(end) == segment:
                    place = "主直道" if segment.zone_name == "Main Straight" else "直道"
        ready_to_call = ((ready and gate not in self.spoken and not recent) or
                         (not ready and (last is None or t - last >= 30 or renewed or
                          located and self.separated and t-last >= 8 and
                          (approach["rate_mps"] >= 20 or approach["sudden_braking"]))))
        meta = dict(
            contact_s=eta, call_ready=bool(ready_to_call), target=r.car_index,
            place=place, clear_lane=r.position > state.player.position + 1,
            name=r.name,
            scope=(state.session_uid, state.session_epoch),
            clock_s=t,
            rear_distance_m=self.samples[-1][1] if self.samples else None,
            completed_wing=dict(completed_wing),
            forecast=f if ready else None,
            closing=None if located else closing,
            passage_pace=pace if closing and not located else None,
            approach=approach if located else None,
            gate=gate if ready else None,
            gap_s=state.player.gap_behind_s,
        )
        if applicable(meta, original, primary, starting=False):
            return meta
        if ready and urgent:
            meta["forecast"] = meta["gate"] = None
            if applicable(meta, original, primary, starting=False):
                return meta
        return None

    def started(self, meta):
        closing = meta.get("closing")
        location = meta.get("approach") or closing
        self.closest_since_call = location["distance_m"] if location else None
        self.last_target = meta["target"]
        self.separated_since = None
        self.separated = False
        self.last_radio = meta["clock_s"]
        self.last_call[meta["target"]] = meta["clock_s"]
        if meta["forecast"]:
            self.spoken.append(meta["gate"])


class DefenceRadio:
    def __init__(self):
        self.pursuers = {}
        self.last_radio = None
        self.last_group = ()
        self.scope = None
        self.threats = []
        self.history = DefenceHistory()

    def observe(self, state, decision, completed_wing, *, quiet=False):
        now = number(state.raw.get("session_time_s"))
        scope = (state.session_uid, state.session_epoch)
        if self.scope != scope:
            self.__init__()
            self.scope = scope
        self.history.record(state, now)
        candidates = []
        observed = set()
        for car in state.rivals:
            view, rear = rear_gap_view(state, car.car_index)
            if view is None or now is None:
                continue
            observed.add(car.car_index)
            if car.car_index not in self.pursuers:
                self.pursuers[car.car_index] = Pursuer()
            tracker = self.pursuers[car.car_index]

            cue = tracker.observe(view, rear, decision, completed_wing, state, self.history)
            if cue:
                candidates.append(cue)
        for target in self.pursuers.keys() - observed:
            tracker = self.pursuers[target]
            if tracker.latest is not None:
                tracker.samples.clear()
                tracker.approach = DefenceApproach()
                tracker.pace = PursuitPace()
                tracker.latest = tracker.gate = None
                tracker.separated = False
        candidates.sort(key=lambda m: (m["contact_s"], m["gap_s"], m["target"]))
        self.threats = [dict(target=m["target"], name=m["name"], gap_s=m["gap_s"], contact_s=m["contact_s"],
                             **({"history": m["approach"]["history"]} if m["approach"] and "history" in m["approach"] else {}))
                        for m in candidates]
        decision.debug["defence_threats"] = self.threats
        if not candidates or quiet:
            return None
        best = candidates[0]
        group = tuple(m["target"] for m in candidates)
        changed = len(group) > 1 and group != self.last_group
        interval = 2.2 if best["approach"] and group[:1] != self.last_group[:1] else 4.
        if not (best["call_ready"] or changed) or self.last_radio is not None and now-self.last_radio < interval:
            return None
        best["threats"] = self.threats
        return best

    def started(self, meta):
        self.last_radio = meta["clock_s"]
        self.last_group = tuple(m["target"] for m in meta.get("threats", [meta]))
        tracker = self.pursuers.get(meta["target"])
        if tracker:
            tracker.started(meta)

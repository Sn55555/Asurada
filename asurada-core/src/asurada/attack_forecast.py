"""Causal, target-bound forecast for the braking zone after a deployment straight."""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from statistics import median

from .track_model import load_track_profile


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


@dataclass(frozen=True)
class Approach:
    name: str
    label: str
    entry: float
    length: float


@lru_cache(maxsize=32)
def approaches(track):
    profile = load_track_profile(track)
    if not profile:
        return ()
    points = []
    zones = profile.semantic_segments
    for index, end in enumerate(zones):
        if end.zone_type != "braking_entry":
            continue
        straight = []
        for back in range(1, len(zones)):
            segment = zones[(index - back) % len(zones)]
            if segment.zone_type != "deployment_straight":
                break
            straight.append(segment)
        if not any(
            z.usage
            in {"primary_overtake_deploy", "primary_ers_deploy", "overtake_setup", "lap_restart_accel"}
            for z in straight
        ):
            continue
        match = re.search(r"(?:Corner\s+|\bT)(\d+)", end.name)
        if not match:
            continue
        label = f"{int(match[1])}号弯"
        if end.name.startswith("Corner "):
            label = "主直道尽头" if straight[0].name == "Main Straight" else "前面长直道尽头"
        points.append(Approach(end.name, label, end.start_m, sum(z.end_m - z.start_m for z in straight)))
    return tuple(points)


def tyre(car, state):
    compound = car.tyre.compound
    if not compound or not re.fullmatch(r"C[0-6]|Soft|Medium|Hard|Intermediate|Wet|[SMH]", compound, re.I):
        compound = None
    actual = state.raw.get("forecast_actual_compounds")
    if isinstance(actual, dict):
        code = actual.get(str(car.car_index))
        # Compare packet compound identities directly, independently of visual tyre colours.
        compound = f"UDP-{code}" if type(code) is int and 0 < code < 255 else None
    source = state.raw.get("forecast_tyre_ages")
    age = source.get(str(car.car_index)) if isinstance(source, dict) else car.tyre.age_laps
    if type(age) is not int or age < 0 or (source is None and age == 0):
        age = None  # older normalizers also used zero for unavailable age
    return compound, age


def stint(state, car):
    compound, age = tyre(car, state)
    return state.weather, compound, car.lap - age if age is not None else None


class SectionTimes:
    """Time each car through the same mapped straight using only observed gate crossings."""

    def __init__(self):
        self.previous = {}
        self.entries = {}
        self.records = {}
        self.open_laps = {}
        self.completed = {}

    def observe_lap(self, car, packet, signature, now):
        """Keep official splits only for a continuously observed, valid lap."""
        key = car.car_index
        prev = self.open_laps.get(key)
        if (
            not packet
            or packet.get("current_lap_num") != car.lap
            or packet.get("current_lap_invalid") is not False
        ):
            self.open_laps.pop(key, None)
            return
        if prev and (signature != prev["signature"] or now - prev["time"] > 0.65):
            prev = None
        if prev and car.lap == prev["lap"] + 1 and prev["clean"]:
            total = number(packet.get("last_lap_time_ms"))
            s1, s2 = prev["s1"], prev["s2"]
            if total and s1 and s2 and total > s1 + s2:
                self.completed[key, prev["lap"]] = (
                    signature,
                    [x / 1000 for x in (s1, s2, total - s1 - s2, total)],
                )
        if not prev or prev["lap"] != car.lap:
            prev = dict(lap=car.lap, signature=signature, clean=car.lap_distance_m < 60, s1=None, s2=None)
        for field in (1, 2):
            split = number(packet.get(f"sector{field}_time_ms"))
            if split and split > 0 and packet.get("sector") in range(field, 3):
                prev[f"s{field}"] = split
        prev["time"] = now
        self.open_laps[key] = prev

    def official_pairs(self, state, front):
        pairs = []
        for lap in range(max(1, state.player.lap - 3), state.player.lap):
            p = self.completed.get((state.player.car_index, lap))
            f = self.completed.get((front.car_index, lap))
            if p and f and p[0] == stint(state, state.player) and f[0] == stint(state, front):
                pairs.append(dict(lap=lap, player_s=p[1], front_s=f[1]))
        return pairs

    def update(self, state, times, length, now):
        lap = state.lap_number
        self.completed = {k: v for k, v in self.completed.items() if lap - 3 <= k[1] <= lap}
        self.records = {k: v for k, v in self.records.items() if lap - 3 <= k[2] <= lap + 1}
        self.entries = {k: v for k, v in self.entries.items() if lap - 1 <= k[2] <= lap + 1}
        clean = (
            state.safety_car == "NONE"
            and state.raw.get("marshal_zone_flag") in (0, 1, None)
            and not state.raw.get("session_paused")
            and state.raw.get("result_status") == 2
        )
        visible = set()
        for car in (state.player, *state.rivals):
            car_id = car.car_index
            dist = number(car.lap_distance_m)
            packet = (state.raw.get("forecast_lap_times") or {}).get(str(car_id))
            invalid = (
                packet.get("current_lap_invalid")
                if packet
                else (state.raw.get("current_lap_invalid") if car is state.player else None)
            )
            if (
                invalid
                or not clean
                or car.pit_status != "NONE"
                or not car.lap
                or dist is None
                or not 0 <= dist <= length
            ):
                continue
            visible.add(car_id)
            absolute = (car.lap - 1) * length + dist
            signature = stint(state, car)
            self.observe_lap(car, packet, signature, now)
            previous = self.previous.get(car_id)
            self.previous[car_id] = now, absolute, signature
            if previous and now == previous[0] and absolute == previous[1]:
                continue
            if (
                not previous
                or signature != previous[2]
                or not 0 < now - previous[0] <= 0.65
                or not 0 <= absolute - previous[1] <= 125 * (now - previous[0]) + 4
            ):
                self.entries = {k: v for k, v in self.entries.items() if k[0] != car_id}
                continue
            before, start, _ = previous
            for turn in times:
                gate_lap = math.floor((start - turn.entry) / length) + 2
                gate = (gate_lap - 1) * length + turn.entry
                key = car_id, turn.name, gate_lap
                for boundary, opening in ((gate - turn.length, True), (gate, False)):
                    if start < boundary <= absolute:
                        passed = before + (now - before) * (boundary - start) / (absolute - start)
                        if opening:
                            self.entries[key] = passed
                        elif key in self.entries:
                            seconds = passed - self.entries.pop(key)
                            if seconds > 0:
                                self.records[key] = seconds, signature
        self.open_laps = {k: v for k, v in self.open_laps.items() if k in visible}
        self.previous = {k: v for k, v in self.previous.items() if k in visible}
        self.entries = {k: v for k, v in self.entries.items() if k[0] in visible}

    def pair(self, state, rival, turn, gate_lap):
        samples = []
        for lap in range(max(1, gate_lap - 3), gate_lap):
            p = self.records.get((state.player.car_index, turn.name, lap))
            f = self.records.get((rival.car_index, turn.name, lap))
            if (
                p
                and f
                and p[1] == stint(state, state.player)
                and f[1] == stint(state, rival)
                and p[1][1]
                and f[1][1]
            ):
                samples.append(dict(lap=lap, player_s=round(p[0], 3), front_s=round(f[0], 3)))
        return samples


class AttackForecast:
    def __init__(self, *, rear=False):
        self.rear = rear
        self.scope = self.target = self.last_s = None
        self.history = deque(maxlen=400)
        self.sections = SectionTimes()

    def observe(self, state, allowed, *, sections=None):
        now = number(state.raw.get("session_time_s"))
        scope = state.session_uid, state.session_epoch, state.track
        if scope != self.scope or (now is not None and self.last_s is not None and now < self.last_s):
            self.sections = SectionTimes()
            self.history.clear()
            self.target = None
        self.scope, self.last_s = scope, now
        turns = approaches(state.track)
        if not allowed or not turns or now is None:
            self.history.clear()
            self.sections.previous.clear()
            self.sections.entries.clear()
            self.sections.open_laps.clear()
            return None
        length = load_track_profile(state.track).lap_length_m
        if sections is None:
            self.sections.update(state, turns, length, now)
            sections = self.sections
        p = state.player
        rivals = [r for r in state.rivals if r.position == p.position + (1 if self.rear else -1)]
        rival = rivals[0] if len(rivals) == 1 else None
        gap, dist, speed = (
            number(p.gap_behind_s if self.rear else p.gap_ahead_s),
            number(p.lap_distance_m),
            number(p.speed_kph),
        )
        raw = state.raw
        if (
            not rival
            or state.safety_car != "NONE"
            or raw.get("result_status") != 2
            or ((raw.get("forecast_lap_times") or {}).get(str(rival.car_index)) or {}).get(
                "current_lap_invalid"
            )
            or raw.get("current_lap_invalid")
            or raw.get("session_paused")
            or raw.get("pit_status_code") != 0
            or rival.pit_status != "NONE"
            or raw.get("marshal_zone_flag") not in (0, 1, None)
            or (p.gap_confidence_behind if self.rear else p.gap_confidence_ahead) != "high"
            or gap is None
            or not 0 < gap <= 2
            or dist is None
            or not 0 <= dist <= length
            or speed is None
            or speed < 60
        ):
            self.history.clear()
            return None
        rival_dist = number(rival.lap_distance_m)
        if rival_dist is None or not 0 <= rival_dist <= length:
            self.history.clear()
            return None
        lead = (rival.lap - p.lap) * length + rival_dist - dist
        if self.rear:
            lead = -lead
        if not -3 <= lead <= 180:
            self.history.clear()
            return None
        target = rival.car_index, rival.position
        if target != self.target or self.history and now - self.history[-1][0] > 0.65:
            self.history.clear()
        self.target = target
        energy = number(raw.get("ers_store_energy"))
        usable = energy / 40000 if energy is not None and 0 < energy <= 4000000 else None
        resource = (raw.get("forecast_rival_resources") or {}).get(str(rival.car_index), {})
        if self.rear:
            # Legacy normalized zero may also mean missing CarStatus.
            usable = number(rival.ers_pct)
            if resource:
                energy = number(resource.get("ers_store_energy"))
                usable = energy / 40000 if energy is not None and 0 <= energy <= 4000000 else None
            elif usable is None or not 0 < usable <= 100:
                usable = None
        if not self.history or self.history[-1][0] != now:
            self.history.append((now, gap, usable))
        while self.history and now - self.history[0][0] > 4:
            self.history.popleft()
        turn = min(turns, key=lambda z: (z.entry - dist) % length)
        remaining = (turn.entry - dist) % length
        eta = remaining / (speed / 3.6)
        if not 3 <= eta <= 22 or remaining > turn.length + 450:
            return None
        gate_lap = p.lap + int(turn.entry < dist)
        pace = sections.pair(state, rival, turn, gate_lap)
        timed_gain = median([v["front_s"] - v["player_s"] for v in pace]) if pace else None
        if self.rear and timed_gain is not None:
            timed_gain = -timed_gain
        official = sections.official_pairs(state, rival)
        pt, ft = tyre(p, state), tyre(rival, state)
        span = now - self.history[0][0]
        if span < 1.5:
            return None
        early = [s[1] for s in self.history if s[0] <= self.history[0][0] + 0.45]
        late = [s[1] for s in self.history if s[0] >= now - 0.45]
        slope = (median(early) - median(late)) / max(0.5, span - 0.45)
        # Limit extrapolation on a straight we have only just entered.
        short_gain = max(-0.12, min(0.12, slope)) * min(eta, 5.0)
        remaining_fraction = min(1.0, remaining / turn.length)
        gain = short_gain
        if timed_gain is not None:
            gain = 0.55 * short_gain + 0.45 * max(-1.0, min(1.0, timed_gain)) * remaining_fraction
        if official:
            typical_lap = median(row["player_s"][3] for row in official)
            lap_gain = median(row["front_s"][3] - row["player_s"][3] for row in official)
            sector = raw.get("sector")
            if type(sector) is int and 0 <= sector < 3:
                sector_rate = median(
                    (row["front_s"][sector] - row["player_s"][sector]) / row["player_s"][sector]
                    for row in official
                )
                pace_rate = (sector_rate + lap_gain / typical_lap) / 2
            else:
                pace_rate = lap_gain / typical_lap
            if self.rear:
                pace_rate = -pace_rate
            gain = 0.8 * gain + 0.2 * min(eta, 5.0) * max(-0.12, min(0.12, pace_rate))
        projected = max(0.0, gap - gain)
        mode = raw.get("ers_deploy_mode")
        prev_energy = self.history[0][2]
        net_rate = (
            max(0.0, (prev_energy - usable) / span)
            if prev_energy is not None and usable is not None
            else None
        )
        reserve = usable - min(eta, 5.0) * net_rate if net_rate is not None else None
        chasing, leading = (ft, pt) if self.rear else (pt, ft)
        older = (
            chasing[0]
            and chasing[0] == leading[0]
            and chasing[1] is not None
            and leading[1] is not None
            and chasing[1] - leading[1] >= 4
        )
        # A tyre advantage is not converted into fictional seconds. Comparable timing
        # must support a call if the player has a substantial same-compound age deficit.
        permission = raw.get("forecast_drs_allowed", p.drs_available)
        activation = raw.get("drs_activation_distance_m")
        if self.rear:
            permission = resource.get("drs_allowed") if resource else (True if rival.drs_available else None)
            activation = resource.get("drs_activation_distance_m")
            mode = None
        available_ahead = permission is True or (
            number(activation) is not None and 0 < activation <= remaining + (lead if self.rear else 0)
        )
        limit = 0.48 if available_ahead else 0.38
        near = gap <= limit and slope >= -0.012
        supported = near or slope >= 0.018 or timed_gain is not None and timed_gain >= 0.12
        # Measured close pressure remains a threat even when the pursuer has little or unknown ERS.
        resource_supported = reserve is not None and reserve >= 18
        if self.rear and near:
            resource_supported = True
        planned = (
            supported
            and projected <= limit
            and resource_supported
            and (not older or timed_gain is not None and timed_gain > 0)
        )
        if self.rear:
            for sample in (*pace, *official):
                sample["rear_s"] = sample.pop("front_s")
        identity = f"{scope[0]}:{scope[1]}:{gate_lap}:{rival.car_index}:{turn.name}"
        return dict(
            id=f"rear:{identity}" if self.rear else identity,
            recommended=bool(planned),
            target=rival.car_index,
            name=rival.name,
            corner=turn.name,
            label=turn.label,
            gate_m=turn.entry,
            gate_lap=gate_lap,
            length_m=length,
            straight_m=turn.length,
            remaining_m=round(remaining, 2),
            eta_s=round(eta, 2),
            gap_s=gap,
            predicted_gap_s=round(projected, 3),
            trend_s_per_s=round(slope, 4),
            player_tyre=pt,
            **({"rear_tyre": ft} if self.rear else {"front_tyre": ft}),
            section_times=pace,
            official_laps=official,
            section_gain_s=timed_gain,
            ers_pct=usable,
            ers_mode=mode,
            ers_net_pct_per_s=net_rate,
            reserve_estimate_pct=reserve,
            drs_allowed=permission,
            drs_activation_distance_m=activation,
            local_flag=raw.get("marshal_zone_flag"),
            clock_s=now,
        )

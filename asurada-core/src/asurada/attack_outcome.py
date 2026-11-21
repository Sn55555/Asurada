"""Observe what happened to the two cars in one actionable attack window."""
from __future__ import annotations
from dataclasses import dataclass, field
import math

from .input_quality import valid_input


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def relative_position(player, rival, heading):
    values = (player.world_position_x, player.world_position_z, rival.world_position_x,
              rival.world_position_z, heading.get("x"), heading.get("z"),
              player.lap_distance_m, rival.lap_distance_m)
    if not all(finite(value) for value in values):
        return None
    px, pz, rx, rz, hx, hz, distance, rival_distance = values
    length = math.hypot(hx, hz)
    if not .85 <= length <= 1.01 or (px == pz == 0) or (rx == rz == 0):
        return None
    dx, dz = rx - px, rz - pz
    longitudinal = (dx * hx + dz * hz) / length
    lateral = (dz * hx - dx * hz) / length
    # Lap distance follows the circuit. Reject incompatible positions or mixed frames.
    if abs(longitudinal - (rival_distance - distance)) > 4 or abs(lateral) > 14:
        return None
    return longitudinal, lateral


LINES = {
    "following": "还在他后面，这段一直跟车。",
    "attempt_no_pass": "刚才已经并排，这次没过。",
    "passed": "超过去了，位置确认。",
    "uncertain": "刚才那次，遥测不足，结果不确定。",
}


@dataclass
class AttackRun:
    window_id: str
    target: int
    player: int
    initial_position: int
    lap: int
    opened_s: float
    end_m: float
    line_origin: tuple | None = None
    steering_s: float | None = None
    last_s: float | None = None
    last_m: float | None = None
    samples: int = 0
    initial_gap: float | None = None
    min_lead: float | None = None
    alongside_since: float | None = None
    side: int = 0
    attempt_s: float | None = None
    ahead_since: float | None = None
    behind_since: float | None = None
    event_s: float | None = None
    order_swapped: bool = False
    stayed_in_line: bool = True
    facts: dict = field(default_factory=dict)

    def result(self, kind, reason, now):
        return dict(window_id=self.window_id, target=self.target, player=self.player, lap=self.lap,
                    opened_s=self.opened_s, observed_s=now, samples=self.samples,
                    min_longitudinal_m=self.min_lead, initial_longitudinal_m=self.initial_gap,
                    attempt_s=self.attempt_s, overtake_event_s=self.event_s,
                    verdict=kind, reason=reason, **self.facts)

    def observe(self, state, now):
        if not finite(now):
            return self.result("uncertain", "missing_clock", self.last_s or self.opened_s)
        if self.last_s is not None:
            if now == self.last_s:
                return None
            if not 0 < now - self.last_s <= .55:
                return self.result("uncertain", "telemetry_discontinuity", now)
        self.last_s = now
        player = state.player
        targets = [r for r in state.rivals if r.car_index == self.target]
        if (len(targets) != 1 or player.car_index != self.player or state.lap_number != self.lap
                or player.lap != self.lap or targets[0].lap != self.lap):
            return self.result("uncertain", "target_or_lap_changed", now)
        rival = targets[0]
        raw = state.raw
        if (raw.get("session_paused") or raw.get("result_status") != 2 or raw.get("pit_status_code") != 0
                or rival.pit_status != "NONE" or state.safety_car != "NONE" or raw.get("marshal_zone_flag") not in (0, 1)):
            return self.result("uncertain", "race_control_or_pit_evidence", now)
        behind = (player.position, rival.position) == (self.initial_position, self.initial_position - 1)
        ahead = (player.position, rival.position) == (self.initial_position - 1, self.initial_position)
        if not (behind or ahead) or any(r.car_index != self.target and r.position in (player.position, rival.position)
                                         for r in state.rivals):
            return self.result("uncertain", "position_change_involving_other_car", now)
        position = relative_position(player, rival, raw.get("world_forward_dir") or {})
        throttle = valid_input("throttle", raw.get("throttle"))
        brake = valid_input("brake", raw.get("brake"))
        steer = valid_input("steer", raw.get("steer"))
        if (position is None or throttle is None or brake is None or steer is None
                or not finite(rival.speed_kph) or rival.speed_kph < 35
                or not finite(player.speed_kph) or player.speed_kph < 35):
            return self.result("uncertain", "missing_geometry_or_controls", now)
        dist = player.lap_distance_m
        if self.last_m is not None and dist < self.last_m - 1:
            return self.result("uncertain", "distance_rewind", now)
        self.last_m = dist
        lead, lateral = position
        self.samples += 1
        if self.initial_gap is None:
            self.initial_gap = lead
        self.min_lead = round(min(lead, self.min_lead if self.min_lead is not None else lead), 2)
        self.facts.update(last_longitudinal_m=round(lead, 2), positions=[player.position, rival.position])
        events = raw.get("recent_overtakes")
        reverse_s = None
        for event in events if isinstance(events, (list, tuple)) else ():
            if not isinstance(event, dict) or not finite(event.get("at_s")) or not self.opened_s <= event["at_s"] <= now:
                continue
            pair = event.get("overtaking_vehicle_idx"), event.get("being_overtaken_vehicle_idx")
            if not all(type(car) is int for car in pair):
                continue
            if pair == (self.player, self.target):
                self.event_s = max(self.event_s or self.opened_s, event["at_s"])
            elif pair == (self.target, self.player):
                reverse_s = max(reverse_s or self.opened_s, event["at_s"])
        if reverse_s is not None and self.event_s is not None and reverse_s >= self.event_s:
            self.facts["reverse_overtake_event_s"] = reverse_s
            return self.result("uncertain", "target_repassed_before_settlement", now)
        # Closing alone (including slipstream) never establishes an attempt.
        heading = raw["world_forward_dir"]
        if self.line_origin is None:
            norm = math.hypot(heading["x"], heading["z"])
            self.line_origin = (player.world_position_x, player.world_position_z, rival.world_position_x,
                                rival.world_position_z, heading["x"]/norm, heading["z"]/norm)
        px, pz, rx, rz, hx, hz = self.line_origin
        player_shift = (player.world_position_z - pz)*hx - (player.world_position_x - px)*hz
        rival_shift = (rival.world_position_z - rz)*hx - (rival.world_position_x - rx)*hz
        self.stayed_in_line &= abs(lateral) <= 1.5
        if abs(steer) >= .04:
            self.steering_s = now
        side = 1 if lateral > 0 else -1
        driver_changed_line = (-side * player_shift >= 1.2 and -side * player_shift - abs(rival_shift) >= .8
                               and self.steering_s is not None and now - self.steering_s <= 3.5
                               and hx * heading["x"] + hz * heading["z"] >= .98)
        alongside = (self.initial_gap >= 8 and abs(lead) <= 4 and 1.7 <= abs(lateral) <= 5
                     and driver_changed_line and (throttle >= .35 or brake >= .18))
        if alongside:
            if self.alongside_since is None or side != self.side:
                self.alongside_since, self.side = now, side
            if self.attempt_s is None and now - self.alongside_since >= .25:
                self.attempt_s = now
                self.facts.update(alongside_s=round(now-self.alongside_since, 3),
                                  lateral_m=round(lateral, 2), alongside_lead_m=round(lead, 2),
                                  throttle=throttle, brake=brake, steering_s=self.steering_s,
                                  player_shift_m=round(player_shift, 2), rival_shift_m=round(rival_shift, 2))
        else:
            self.alongside_since = None
        self.order_swapped |= ahead
        if ahead and lead <= -6:
            if self.ahead_since is None:
                self.ahead_since = now
            if self.event_s is not None and now - self.ahead_since >= .4:
                self.facts["confirmed_ahead_s"] = round(now - self.ahead_since, 3)
                return self.result("passed", "matching_overtake_and_stable_order", now)
        else:
            self.ahead_since = None
        if behind and lead >= 8:
            if self.behind_since is None:
                self.behind_since = now
        else:
            self.behind_since = None
        if dist >= self.end_m + 35 and now - self.opened_s >= 1.0:
            if self.behind_since is not None and now - self.behind_since >= .4 and not self.order_swapped and self.event_s is None:
                if self.attempt_s is not None:
                    return self.result("attempt_no_pass", "sustained_overlap_then_fell_behind", now)
                if self.min_lead >= 8 and self.stayed_in_line:
                    return self.result("following", "continuously_behind_through_window", now)
            # Allow timing and game events to arrive after the physical crossing.
            if dist >= self.end_m + 110:
                return self.result("uncertain", "unconfirmed_order_or_ambiguous_approach", now)
        if now - self.opened_s >= 18:
            return self.result("uncertain", "observation_timeout", now)
        return None

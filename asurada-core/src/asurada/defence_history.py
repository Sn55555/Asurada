"""Forecast a defence from completed, same-station telemetry traces."""
from bisect import bisect_left

from .attack_forecast import number
from .defence_approach import within_defence_horizon
from .track_model import load_track_profile


class DefenceHistory:
    def __init__(self):
        self.traces = {}
        self.segments = ()
        self.profile = None

    def record(self, state, now):
        if self.profile is None or self.profile.track != state.track:
            self.profile = load_track_profile(state.track)
            self.traces.clear()
            self.segments = tuple(self.profile.semantic_segments) if self.profile else ()
        if (now is None or state.raw.get("result_status") != 2 or state.raw.get("session_paused")
                or state.raw.get("current_lap_invalid") or state.safety_car != "NONE"
                or state.raw.get("marshal_zone_flag") not in (0, 1, None)):
            return
        minimum_lap = state.player.lap - 3
        for key in list(self.traces):
            if key[0] < minimum_lap:
                del self.traces[key]
        for car in (state.player, *state.rivals):
            distance, speed = number(car.lap_distance_m), number(car.speed_kph)
            if (car.lap < minimum_lap or car.pit_status != "NONE" or "not_racing" in car.status_tags
                    or distance is None or speed is None or not 0 < speed <= 380):
                continue
            key = car.lap, car.car_index
            trace = self.traces.setdefault(key, [])
            if trace and (not 0 < now - trace[-1][1] <= .45 or distance < trace[-1][0]):
                trace.clear()
            if not trace or distance > trace[-1][0]:
                brake = number(state.raw.get("brake")) if car is state.player else None
                trace.append((distance, now, speed, brake))

    def forecast(self, state, rear, now):
        p = state.player
        x, y = number(p.lap_distance_m), number(rear.lap_distance_m)
        player_speed, rear_speed = number(p.speed_kph), number(rear.speed_kph)
        gap = number(p.gap_behind_s)
        brake, steer = number(state.raw.get("brake")), number(state.raw.get("steer"))
        if (not self.profile or p.lap != rear.lap or x is None or y is None
                or not player_speed or not rear_speed or not 4 < x-y <= 250 or gap is None or not 0 < gap <= 2
                or p.gap_confidence_behind != "high" or brake is None or not 0 <= brake <= .18
                or steer is None or abs(steer) > .16 or state.raw.get("current_lap_invalid")):
            return None
        section = next((s for s in self.segments if s.start_m <= x < s.end_m), None)
        if not section or section.zone_type not in {"deployment_straight", "braking_entry", "high_load_management"}:
            return None
        predictions = []
        for lap in range(p.lap - 3, p.lap):
            player_trace = self.traces.get((lap, p.car_index))
            rear_trace = self.traces.get((lap, rear.car_index))
            if not player_trace or not rear_trace:
                continue
            player_anchor = sample_at(player_trace, x)
            rear_anchor = sample_at(rear_trace, y)
            if (not player_anchor or not rear_anchor or abs(player_anchor[1]-player_speed) > 15
                    or abs(rear_anchor[1]-rear_speed) > 15):
                continue
            brake_point = upcoming_brake(player_trace, x, section.end_m, player_anchor[0])
            if brake_point is None:
                return None  # A comparable lap without the predicted braking is contrary evidence.
            intercept = projected_contact(player_trace, rear_trace, x, section.end_m, player_anchor[0], rear_anchor[0])
            if not intercept or intercept[1] < brake_point:
                return None
            predictions.append((lap, *intercept, brake_point))
        if len(predictions) < 2:
            return None
        times = [item[1] for item in predictions]
        braking_points = [item[3] for item in predictions]
        locations = [item[2] for item in predictions]
        # Reserve half a spatial sampling interval and frame jitter in the delivery budget.
        earliest, latest = min(times) - .15, max(times) + .15
        if (not within_defence_horizon(latest) or latest-earliest > 1 or earliest <= 0
                or max(braking_points)-min(braking_points) > 20 or max(locations)-min(locations) > 40):
            return None
        if section.zone_type == "deployment_straight":
            text = "守主直道。" if section.name == "Main Straight" else "守直道。"
        else:
            text = "守弯中。"
        return dict(text=text, distance_m=x-y, rate_mps=(rear_speed-player_speed)/3.6,
                    earliest_s=earliest, latest_s=latest, length_m=self.profile.lap_length_m,
                    gate_m=section.end_m, gate_lap=p.lap, remaining_m=section.end_m-x,
                    corner=section.name, sudden_braking=False, history=predictions)


def sample_at(trace, station):
    i = bisect_left(trace, (station,))
    if i == len(trace):
        return None
    b = trace[i]
    if b[0] == station:
        return b[1:3]
    if not i:
        return None
    a = trace[i - 1]
    if not 0 < b[0]-a[0] <= 30 or not 0 < b[1]-a[1] <= .45:
        return None
    ratio = (station-a[0]) / (b[0]-a[0])
    return (a[1]+ratio*(b[1]-a[1]), a[2]+ratio*(b[2]-a[2]))


def upcoming_brake(trace, station, end, origin):
    index = bisect_left(trace, (station,))
    for i in range(index, len(trace)-2):
        a, b, c = trace[i:i+3]
        if c[0] >= end or c[1]-origin > 4.5:
            break
        if all(point[3] is not None and point[3] >= .45 for point in (a, b, c)) and a[2]-c[2] >= 8:
            return a[0]
    return None


def projected_contact(player, rear, start, end, player_origin, rear_origin):
    station = start + 5
    while station < end:
        p, r = sample_at(player, station), sample_at(rear, station - 4)
        if not p or not r or p[0]-player_origin > 4.5:
            return None
        if r[0]-rear_origin <= p[0]-player_origin:
            return p[0]-player_origin, station
        station += 5
    return None

"""Locate an approaching rear car on a mapped overtaking straight using only past samples."""
from collections import deque
from math import sqrt

from .attack_forecast import approaches, number
from .track_model import load_track_profile


def within_defence_horizon(seconds):
    # The same 4.5 s ETA can differ by floating-point roundoff when derived
    # from km/h versus successive positions in metres.
    return seconds <= 4.5 + 1e-12



def time_to_close(distance, rate, acceleration, sustained_for):
    """Project only a bounded period of acceleration, then hold the resulting speed."""
    gain = rate * sustained_for + .5 * acceleration * sustained_for ** 2
    if distance <= gain:
        return 2 * distance / (rate + sqrt(rate ** 2 + 2 * acceleration * distance))
    return sustained_for + (distance - gain) / (rate + acceleration * sustained_for)


def track_gap(state, rear, length):
    p = state.player
    if rear is None or rear.pit_status != "NONE":
        return None
    if any(number(value) is None or not 0 <= value <= length
           for value in (p.lap_distance_m, rear.lap_distance_m)):
        return None
    if type(p.lap) is not int or type(rear.lap) is not int:
        return None
    return (p.lap - rear.lap) * length + p.lap_distance_m - rear.lap_distance_m


class DefenceApproach:
    def __init__(self):
        self.key = None
        self.samples = deque(maxlen=80)

    def observe(self, state, rear, now, forecast):
        p = state.player
        profile = load_track_profile(state.track)
        turns = approaches(state.track)
        if not profile or not turns:
            return None
        length = profile.lap_length_m
        distance = track_gap(state, rear, length)
        if distance is None or not 5 < distance <= 300 or p.gap_confidence_behind != "high":
            self.samples.clear()
            return None
        turn = min(turns, key=lambda v: (v.entry - p.lap_distance_m) % length)
        remaining = (turn.entry - p.lap_distance_m) % length
        key = state.session_uid, state.session_epoch, state.track, rear.car_index, turn.name, p.lap + int(turn.entry < p.lap_distance_m)
        speeds = number(p.speed_kph), number(rear.speed_kph)
        if (remaining + distance > turn.length or any(s is None or not 0 < s <= 380 for s in speeds)
                or state.raw.get("current_lap_invalid")):
            self.samples.clear()
            return None
        if self.key != key or self.samples and not 0 < now - self.samples[-1][0] <= 0.25:
            self.samples.clear()
        self.key = key
        rate = (speeds[1] - speeds[0]) / 3.6
        self.samples.append((now, distance, rate, speeds[0], speeds[1]))
        while now - self.samples[0][0] > 0.55:
            self.samples.popleft()
        first, middle = self.samples[0], self.samples[len(self.samples) // 2]
        span = now - first[0]
        rapid_braking = self._rapid_braking(
            p, state, now, turn, remaining, length, distance, rate
        )
        if rapid_braking:
            return rapid_braking
        if span < 0.30 or not first[0] < middle[0] < now or rate < 10:
            return None
        brake = number(state.raw.get("brake"))
        acceleration = (rate - first[2]) / span
        # Outside the mapped braking zone a sudden player slowdown can reverse
        # the gap trend within this very sample window. Require corroboration
        # from both cars' speeds and the *observed* second-half distance gain.
        sudden = (brake is not None and brake >= 0.4 and acceleration >= 12
                  and speeds[0] <= first[3] - 18 and speeds[1] >= first[4]
                  and remaining > speeds[0] / 3.6 * 6 and middle[1] - distance >= 1.8)
        for a, b in ((first, middle), (middle, self.samples[-1])):
            change = a[1] - b[1]
            expected = (a[2] + b[2]) * 0.5 * (b[0] - a[0])
            if (change <= 0 and not sudden) or abs(expected - change) > 1.5:
                return None
        # Budget for accelerating closure over the next second. Also check the
        # slower, constant-speed estimate before naming a place.
        acceleration = max(0, min(20, acceleration))
        fast = (distance - 4 + acceleration / 2) / (rate + acceleration)
        slow = (distance - 4) / rate
        if not 1.8 <= fast <= slow <= 6 or not within_defence_horizon(fast):
            return None
        if brake is None or (brake > 0.18 and rate < (12 if sudden else 16)) or (not within_defence_horizon(slow) and acceleration < 6):
            return None
        speed = speeds[0] / 3.6
        main = profile.classify(p.lap_distance_m).zone_name == "Main Straight"
        if slow * speed < remaining - 30:
            text = "守主直道。" if main else "守直道。"
        elif (forecast and forecast["recommended"] and forecast["target"] == rear.car_index
              and forecast["corner"] == turn.name and fast * speed >= remaining - 65
              and slow * speed <= remaining + 65):
            text = "守一号弯。" if main and turn.name == "Corner 01 Braking" else "守直道尽头。"
        else:
            return None
        return dict(text=text, distance_m=distance, rate_mps=rate, observed_span_s=span, sudden_braking=sudden,
                    delta_m=first[1] - distance, earliest_s=fast, latest_s=slow, length_m=length,
                    gate_m=turn.entry, gate_lap=key[-1], remaining_m=remaining, corner=turn.name)


    def _rapid_braking(self, player, state, now, turn, remaining, length, distance, rate):
        # An off-braking-zone slowdown can reverse the gap before the usual
        # closing-rate threshold. Cross-check speed changes against LapData.
        if (load_track_profile(state.track).classify(player.lap_distance_m).zone_name != "Main Straight"
                or not .45 <= distance / (player.speed_kph / 3.6) <= 2.6
                or remaining <= player.speed_kph / 3.6 * 6
                or len(self.samples) < 3 or not 0 < rate < 18):
            return None
        a, b, c = tuple(self.samples)[-3:]
        braking = number(state.raw.get("brake"))
        steering = number(state.raw.get("steer"))
        if (braking is None or braking < .65 or steering is None or abs(steering) > .16
                or not .15 <= now - a[0] <= .3 or a[3] - c[3] < 16):
            return None
        rates = []
        for left, right in ((a, b), (b, c)):
            dt = right[0] - left[0]
            acceleration = (right[2] - left[2]) / dt
            measured = left[1] - right[1]
            expected = (left[2] + right[2]) * .5 * dt
            if (not 16 <= acceleration <= 45 or right[4] < left[4]
                    or abs(measured - expected) > .8):
                return None
            rates.append(acceleration)
        if b[1] - distance < .15:
            return None
        early = time_to_close(distance - 4, rate, max(rates), 1.8)
        late = time_to_close(distance - 4, rate, .65 * min(rates), 1.8)
        if not 1.8 <= early <= late or not within_defence_horizon(late):
            return None
        if late * (player.speed_kph / 3.6) >= remaining - 30:
            return None
        return dict(text="守主直道。", distance_m=distance, rate_mps=rate,
                    observed_span_s=now - a[0], sudden_braking=True, closing_acceleration=rates,
                    delta_m=a[1] - distance, earliest_s=early, latest_s=late, length_m=length,
                    gate_m=turn.entry, gate_lap=self.key[-1], remaining_m=remaining, corner=turn.name)


class PursuitPace:
    """Compare the pursuer to the player's earlier passage through the same point."""

    def __init__(self):
        self.player_trace = deque(maxlen=256)
        self.scope = None
        self.rear_sample = None
        self.confirmed_track_closure = False
        self.braking_recently = False

    def observe(self, state, rear, now):
        p = state.player
        profile = load_track_profile(state.track)
        speed, pos = number(p.speed_kph), number(p.lap_distance_m)
        scope = (state.session_uid, state.session_epoch, state.track)
        self.confirmed_track_closure = self.braking_recently = False
        if (not profile or pos is None or not 0 <= pos <= profile.lap_length_m
                or type(p.lap) is not int or speed is None or not 0 <= speed <= 380):
            self.player_trace.clear()
            self.rear_sample = None
            return None
        pos += p.lap * profile.lap_length_m
        if self.player_trace:
            dt = now - self.player_trace[-1][0]
            advance = pos - self.player_trace[-1][1]
            if scope != self.scope or not 0 < dt <= .35 or not 0 <= advance <= 125 * dt + 3:
                self.player_trace.clear()
                self.rear_sample = None
        self.scope = scope
        self.player_trace.append((now, pos, speed))
        while self.player_trace and now - self.player_trace[0][0] > 5:
            self.player_trace.popleft()
        # Lifting the brake for a frame during turn-in does not end the compression.
        self.braking_recently = any(v - speed >= 18 for t, _, v in reversed(self.player_trace) if now-t <= .75)
        gap = track_gap(state, rear, profile.lap_length_m)
        previous, self.rear_sample = self.rear_sample, None
        if gap is None or not 4 < gap <= 250:
            return None
        rv = number(rear.speed_kph)
        if rv is None or not 0 < rv <= 380:
            return None
        self.rear_sample = (rear.car_index, now, gap)
        if previous and previous[0] == rear.car_index and 0 < now - previous[1] <= .35:
            rate = (previous[2] - gap) / (now - previous[1])
            # Lap-distance changes and the independently reported speeds must agree.
            self.confirmed_track_closure = 1 < rate < 100 and abs(rate - (rv - speed) / 3.6) < max(4, .4 * rate)
        station = pos - gap
        later = self.player_trace[-1]
        for earlier in reversed(self.player_trace):
            if earlier[1] <= station < later[1]:
                f = (station - earlier[1]) / (later[1] - earlier[1])
                at = earlier[0] + f * (later[0] - earlier[0])
                same_speed = earlier[2] + f * (later[2] - earlier[2])
                if same_speed <= 0 or now <= at:
                    return None
                return dict(delay_s=now - at, gain_per_s=(rv - same_speed) / same_speed)
            later = earlier
        return None

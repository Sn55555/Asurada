"""Controlled three-pursuer field on Jeddah's main straight, independent of archived results."""
from dataclasses import replace

from asurada.attack_outcome import relative_position
from phase3_attack_mode_regression import _decision, _state


def replay(voice, backend, *, blocked=False, matching_speed=False, shift_gap=0.):
    frames = []
    for i in range(112):
        t = i / 20
        backend.now, backend.index = t, i
        state = _state(gap_ahead=5., drs_available=False)
        state.track = "Jeddah"
        p = state.player
        p.speed_kph, p.lap_distance_m = 180., 5820 + 50 * t
        p.pit_status = "NONE"
        p.world_position_x, p.world_position_z = p.lap_distance_m, 100.
        state.source_timestamp_ms = 10000 + round(t * 1000)
        state.raw.update(result_status=2, pit_status_code=0, session_time_s=t, brake=0.,
                         steer=0., marshal_zone_flag=1, world_forward_dir={"x": 1., "z": 0.})
        cars = []
        for target, name, initial, speed_gain, lane in (
            (16, "勒克莱尔", 4 + 12 * 4.78, 12., 2.5),
            (8, "劳森", 4 + 20 * 4.53, 20., 2.5 if blocked else -2.5),
            (7, "阿尔本", 99., 2., .1),
        ):
            rate = 0. if matching_speed else speed_gain
            distance = initial - t * rate
            car = replace(p, car_index=target, name=name, speed_kph=180 + 3.6 * rate,
                          lap_distance_m=p.lap_distance_m - distance,
                          world_position_x=p.world_position_x - distance, world_position_z=100 + lane)
            cars.append((distance, car))
        # In the blocked control Lawson stays behind Leclerc on the same line.
        if blocked and cars[1][0] < cars[0][0] + 6:
            dist, car = cars[0][0] + 6, cars[1][1]
            car.speed_kph = cars[0][1].speed_kph
            car.world_position_x = car.lap_distance_m = p.lap_distance_m - dist
            cars[1] = dist, car
        field = sorted([(0., p), *cars], key=lambda entry: entry[0])
        for rank, (distance, car) in enumerate(field, 2):
            car.position = rank
            pos = rank - 2
            if pos:
                car.gap_ahead_s = (distance - field[pos-1][0]) / 50 + (shift_gap if field[pos-1][1] is p else 0.)
                car.gap_confidence_ahead = "high"
            if car is p and pos + 1 < len(field):
                p.gap_behind_s = field[pos+1][0] / 50 + shift_gap
                p.gap_confidence_behind = "high"
        state.rivals = [car for _, car in cars]
        decision = _decision(code="NONE", detail="", setup_method="none", commit_method="none")
        decision.debug["defence_forecast"] = None
        voice.emit(decision, state=state, render=False)
        frames.append(dict(t=t, threats=decision.debug["defence_threats"],
                           geo={car.car_index: relative_position(p, car, state.raw["world_forward_dir"]) for _, car in cars}))
    return frames

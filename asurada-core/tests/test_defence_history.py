from dataclasses import replace

from asurada.defence_history import DefenceHistory
from phase3_attack_mode_regression import _state


def frame(lap, time, distance, speed, brake):
    state = _state(gap_ahead=4., drs_available=False)
    state.track = "Jeddah"
    player = state.player
    player.lap, player.lap_distance_m = lap, distance
    player.speed_kph, player.pit_status = speed, "NONE"
    player.gap_behind_s, player.gap_confidence_behind = 1.2, "high"
    state.raw.update(result_status=2, brake=brake, steer=0., session_time_s=time)
    rear = replace(player, car_index=8, position=player.position + 1, name="劳森",
                   lap_distance_m=5760+(time % 100)*74, speed_kph=266.4)
    state.rivals = [rear]
    return state, rear


def test_forecast_before_braking_uses_repeated_paths_from_both_cars():
    for brake_laps in ((10, 11), (10,)):
        history = DefenceHistory()
        for lap in (10, 11):
            for index in range(56):
                t = index / 10
                brake_age = max(0, min(t-2., 1.5)) if lap in brake_laps else 0.
                slowdown = 15*brake_age**2 + 45*max(0, t-3.5) if lap in brake_laps else 0.
                now = lap*100 + t
                state, _ = frame(lap, now, 5760+75*t-slowdown, 270-108*brake_age, .8 if brake_age else 0.)
                history.record(state, now)
        state, rear = frame(12, 1200, 5900, 270, 0)
        rear.lap_distance_m = 5805
        result = history.forecast(state, rear, 1200)
        if len(brake_laps) == 2:
            assert result["text"] == "守主直道。"
            assert [lap for lap, *_ in result["history"]] == [10, 11]
            assert 2.8 < result["earliest_s"] < result["latest_s"] < 4.5
            del history.traces[11, rear.car_index]
            assert history.forecast(state, rear, 1200) is None
        else:
            assert result is None

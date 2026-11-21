from types import SimpleNamespace as NS



from asurada.attack_forecast import AttackForecast, SectionTimes, stint


def car(idx, position, age):
    return NS(
        car_index=idx,
        name=str(idx),
        position=position,
        lap=4,
        tyre=NS(compound="C4", age_laps=age),
        pit_status="NONE",
        speed_kph=252,
        gap_confidence_ahead="high",
        drs_available=False,
    )


def predict(
    *, gap=0.43, drs=False, activation=None, energy=60, age=3, flag=1, historical_gain=None, official=None
):
    p, rival = car(9, 6, age), car(7, 5, 3)
    state = NS(
        player=p,
        rivals=[rival],
        track="Jeddah",
        weather="Dry",
        lap_number=4,
        session_epoch=0,
        session_uid="demo",
        safety_car="NONE",
        raw=dict(
            result_status=2,
            pit_status_code=0,
            marshal_zone_flag=flag,
            forecast_drs_allowed=drs,
            drs_activation_distance_m=activation,
            sector=0,
        ),
    )
    policy = AttackForecast()
    for i in range(22):
        t = i / 10
        p.lap_distance_m = 6 + 70 * t
        rival.lap_distance_m = p.lap_distance_m + 20
        p.gap_ahead_s = gap
        state.raw.update(session_time_s=t, ers_store_energy=energy * 40000 if energy is not None else None)
        if i == 1 and historical_gain is not None:
            key = "Corner 01 Braking", 3
            policy.sections.records[(9, *key)] = 8.0, stint(state, p)
            policy.sections.records[(7, *key)] = 8.0 + historical_gain, stint(state, rival)
        if i == 1 and official:
            policy.sections.completed[9, 3] = stint(state, p), [25, 25, 25, 75]
            policy.sections.completed[7, 3] = stint(state, rival), official
        signal = policy.observe(state, True)
    return signal


def test_resources_change_recommendation():
    assert not predict()["recommended"]
    assert predict(drs=True)["recommended"]
    assert predict(activation=80)["recommended"]
    assert not predict(activation=400)["recommended"]
    assert not predict(drs=True, energy=10)["recommended"]
    assert not predict(drs=True, energy=None)["recommended"]
    assert predict(drs=True, flag=3) is None


def test_stint_and_historical_speed_change_recommendation():
    assert not predict(drs=True, age=8)["recommended"]
    assert predict(drs=True, age=8, historical_gain=0.8)["recommended"]
    assert not predict(gap=0.47, drs=True, official=[18, 22, 23, 63])["recommended"]
    assert predict(gap=0.47, drs=True, official=[30, 29, 30, 89])["recommended"]


def test_official_splits_require_valid_completed_lap_and_match_stint():
    p = car(9, 6, 3)
    f = car(7, 5, 3)
    p.lap_distance_m = 12
    s = NS(player=p, weather="Dry", raw={})
    tracker = SectionTimes()
    for c in (p, f):
        c.lap_distance_m = 12
        for i in range(4):
            c.lap = 4 + int(i == 3)
            c.tyre.age_laps = c.lap - 1
            packet = dict(
                current_lap_num=c.lap,
                current_lap_invalid=False,
                sector=i % 3,
                sector1_time_ms=22000,
                sector2_time_ms=31000,
                last_lap_time_ms=85000,
            )
            tracker.observe_lap(c, packet, stint(s, c), i * 0.4)
    assert tracker.official_pairs(s, f)[0]["front_s"] == [22, 31, 32, 85]
    f.tyre.age_laps = 0
    assert not tracker.official_pairs(s, f)


def test_defence_uses_the_pursuers_pace_and_resources():
    player, rear = car(9, 4, 5), car(3, 5, 2)
    player.gap_behind_s = 0.43
    player.gap_confidence_behind = "high"
    player.gap_ahead_s = None
    rear.ers_pct = 60
    state = NS(
        player=player,
        rivals=[rear],
        track="Jeddah",
        weather="Dry",
        lap_number=4,
        session_epoch=0,
        session_uid="sample",
        safety_car="NONE",
        raw=dict(
            result_status=2,
            pit_status_code=0,
            marshal_zone_flag=1,
            forecast_drs_allowed=True,
            ers_store_energy=4000000,
        ),
    )

    def run(drs, rear_age=2, rear_section=7):
        rear.tyre.age_laps = rear_age
        rear.drs_available = drs
        forecaster = AttackForecast(rear=True)
        for i in range(21):
            state.raw["session_time_s"] = i / 10
            player.lap_distance_m = 45 + 5 * i
            rear.lap_distance_m = player.lap_distance_m - 28
            if i == 1:
                for c, elapsed in ((player, 7), (rear, rear_section)):
                    forecaster.sections.records[c.car_index, "Corner 01 Braking", 3] = (
                        elapsed,
                        stint(state, c),
                    )
            f = forecaster.observe(state, True)
        return f

    assert not run(False)["recommended"]
    signal = run(True)
    assert signal["target"] == rear.car_index and signal["recommended"] and signal["ers_pct"] == 60
    assert not run(True, rear_age=9)["recommended"]
    assert run(True, rear_age=9, rear_section=6.4)["recommended"]
    rear.position = player.position - 1
    assert run(True) is None

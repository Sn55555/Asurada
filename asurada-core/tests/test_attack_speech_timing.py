from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.output import ConsoleVoiceOutput
from asurada.speech_applicability import validate_assist_applicability
from phase3_attack_mode_regression import _decision, _state
from phase3_voice_regression import FakeSpeechBackend


class Radio:
    def __init__(self, *, defence=False):
        self.defence = defence
        self.output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
        self.clock = 0

    @property
    def handles(self):
        return self.output.backend._handles

    def frame(self, *, gap=0.2, candidate=True, primary="NONE", damage=40, rival=16, yellow=False, distance=None, brake=0.0, rear_speed_delta=0., lateral=2.):
        t = self.clock / 10
        self.clock += 1
        s = _state(gap_ahead=gap, drs_available=True)
        s.track = "Jeddah"
        s.player.lap_distance_m = 3300 + 60 * t
        s.player.pit_status = "NONE"
        s.player.gap_behind_s = 3.0
        s.player.gap_confidence_ahead = "high" if gap is not None else None
        s.source_timestamp_ms = 10000 + round(1000 * t)
        s.rivals = [
            replace(s.player, position=1, car_index=rival, name="劳森", lap_distance_m=s.player.lap_distance_m + 12)
        ]
        s.raw.update(
            result_status=2,
            pit_status_code=0,
            steer=0.0,
            brake=brake,
            session_time_s=t,
            marshal_zone_flag=3 if yellow else 1,
            wing_damage_pct={"front_left": damage, "front_right": 0},
        )
        d = _decision(code=primary, detail=primary, setup_method="none", commit_method="none")
        if primary == "FRONT_WING_DAMAGE":
            d.messages[0].title = "左前翼受损"
        if candidate:
            d.debug["attack_forecast"] = dict(
                id="test-window",
                clock_s=t,
                eta_s=10.0,
                target=16,
                recommended=True,
                label="直道尽头",
                gate_m=4230.0,
                gate_lap=s.player.lap,
                length_m=6174.0,
                remaining_m=4230.0 - s.player.lap_distance_m,
                gap_s=gap,
                trend_s_per_s=gap / 4.4 if gap else 0,
            )
        if self.defence:
            s.player.gap_ahead_s = 3.0
            s.player.gap_behind_s = gap
            s.player.gap_confidence_behind = "high" if gap is not None else None
            s.rivals[0].position = s.player.position + 1
            s.rivals[0].lap_distance_m = s.player.lap_distance_m - 12
            if distance is not None:
                s.raw["world_forward_dir"] = {"x": 1, "z": 0}
                s.player.world_position_x, s.player.world_position_z = 500, 100
                rear = s.rivals[0]
                rear.world_position_x, rear.world_position_z = 500 - distance, 100 + lateral
                rear.speed_kph += rear_speed_delta
                rear.lap_distance_m = s.player.lap_distance_m - distance
            d.debug["defence_forecast"] = d.debug.pop("attack_forecast", None)
            if d.debug["defence_forecast"]:
                d.debug["defence_forecast"]["eta_s"] = 4.4
        self.output.emit(d, state=s, render=False)
        return s, d

    def start_after_wing(self):
        self.frame(primary="FRONT_WING_DAMAGE", candidate=False)
        assert self.handles[-1]["job"]["action_code"] == "FRONT_WING_DAMAGE"
        assert not self.output._wing_completed
        self.output.backend.complete_all()
        self.output.tick()
        assert self.output._wing_completed == {"front_left": 40}
        for _ in range(7):
            s, _ = self.frame(primary="FRONT_WING_DAMAGE")
            if self.defence and self.handles[-1]["job"]["action_code"] == "DEFEND_WINDOW":
                break
        assert self.handles[-1]["job"]["action_code"] == (
            "DEFEND_WINDOW" if self.defence else "ATTACK_FORECAST"
        )
        job = self.output._active_envelope.job
        return s, job


def check_active_forecast_gap_and_safety(*, defence=False):
    cases = ("returns", "second_missing", "new_front", "new_damage", "yellow", "unstable")
    for case in cases:
        with (
            patch("asurada.output.approaching_wing_corner", return_value=None),
            TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "ASURADA_PERSONALITY_ENABLED": "1",
                    "ASURADA_PERSONALITY_LLM_MODE": "disabled",
                    "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
                },
            ),
        ):
            radio = Radio(defence=defence)
            state, job = radio.start_after_wing()
            # Exercise the authoritative pre-start guard with the previously heard warning.
            state.decision_record = type(
                "Bound", (), {"actions": [type("Action", (), {"code": "FRONT_WING_DAMAGE"})()]}
            )()
            validate_assist_applicability(
                job, state, state, wall_clock=lambda: state.source_timestamp_ms / 1000
            )
            active = radio.handles[-1]
            if case == "yellow" or case == "unstable":
                code = "LOCAL_YELLOW" if case == "yellow" else "DYNAMICS_UNSTABLE"
                radio.frame(gap=None, candidate=False, primary=code, yellow=case == "yellow")
                assert not active["active"] and radio.handles[-1]["job"]["action_code"] == code
            elif case == "new_damage":
                radio.frame(primary="FRONT_WING_DAMAGE", damage=41)
                assert not active["active"] and radio.handles[-1]["job"]["action_code"] == "FRONT_WING_DAMAGE"
            else:
                radio.frame(primary="FRONT_WING_DAMAGE", gap=None, candidate=False)
                assert active["active"]
                if case == "returns":
                    for _ in range(14):
                        radio.frame(primary="FRONT_WING_DAMAGE", candidate=False)
                        assert active["active"]
                    radio.frame(primary="FRONT_WING_DAMAGE")
                    radio.output.backend.complete_all()
                    assert radio.output.tick()["event"]["event_type"] == "complete"
                elif case == "second_missing":
                    radio.frame(primary="FRONT_WING_DAMAGE", gap=None, candidate=False)
                    assert not active["active"]
                else:
                    radio.frame(primary="FRONT_WING_DAMAGE", candidate=False, rival=8)
                    assert not active["active"]
            radio.output.shutdown()


def test_cut_wing_warning_is_retried():
    with (
        TemporaryDirectory() as tmp,
        patch.dict(
            "os.environ",
            {
                "ASURADA_PERSONALITY_ENABLED": "1",
                "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
            },
        ),
    ):
        radio = Radio()
        radio.frame(primary="FRONT_WING_DAMAGE", candidate=False)
        radio.frame(primary="LOCAL_YELLOW", yellow=True, candidate=False)
        assert not radio.output._wing_completed
        radio.output.backend.complete_all()
        radio.output.tick()
        radio.frame(primary="FRONT_WING_DAMAGE", candidate=False)
        assert [r["job"]["action_code"] for r in radio.handles] == [
            "FRONT_WING_DAMAGE",
            "LOCAL_YELLOW",
            "FRONT_WING_DAMAGE",
        ]
        radio.output.shutdown()


def test_active_forecast_gap_and_safety():
    check_active_forecast_gap_and_safety()


def test_active_defence_gap_and_safety():
    check_active_forecast_gap_and_safety(defence=True)


def test_target_swap_does_not_repeat_defence_or_erase_new_corner():
    with (
        TemporaryDirectory() as tmp,
        patch.dict(
            "os.environ",
            {
                "ASURADA_PERSONALITY_ENABLED": "1",
                "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
            },
        ),
    ):
        radio = Radio(defence=True)
        for target in (16, 7, 16):
            radio.frame(rival=target, primary="DEFEND_WINDOW", candidate=False)
            radio.output.backend.complete_all()
            radio.output.tick()
        assert not radio.handles
        # Keeping the same rear car close for several seconds can uncover a named braking point.
        for _ in range(58):
            radio.frame(primary="DEFEND_WINDOW")
            radio.output.backend.complete_all()
            radio.output.tick()
        spoken = [h["job"]["speak_text"] for h in radio.handles]
        assert spoken == ["后方劳森，守直道尽头。"], spoken
        radio.output.shutdown()

def test_short_defence_requires_identity_closing_and_runway():
    with TemporaryDirectory() as tmp, patch.dict("os.environ", {
        "ASURADA_PERSONALITY_ENABLED": "1",
        "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
    }):
        radio = Radio(defence=True)
        for n in range(20):
            radio.frame(primary="DEFEND_WINDOW", candidate=False, distance=20 + n)
        for n in range(12):
            radio.frame(primary="DEFEND_WINDOW", candidate=False, distance=35 - n, rival=n % 2 + 7)
        assert not radio.handles
        for n in range(12):
            radio.frame(primary="DEFEND_WINDOW", candidate=False, distance=40 - n, rival=8, brake=0.7)
        assert not radio.handles
        for n in range(10):
            state, _ = radio.frame(primary="NONE", candidate=False, distance=50 - n, rival=6, gap=1.4)
        assert len(radio.handles) == 1
        handle = radio.handles[0]
        assert handle["job"]["metadata"]["defence_window"]["target"] == 6
        from asurada.defence_radio import applicable
        meta = handle["job"]["metadata"]["defence_window"]
        # A delayed short alert has lost the runway even when the target stays the same.
        delayed = dict(meta, closing=dict(meta["closing"], earliest_s=1.9))
        state.raw["session_time_s"] = meta["clock_s"] + 0.5
        assert not applicable(delayed, state, "NONE")
        radio.frame(primary="LOCAL_YELLOW", candidate=False, rival=6, yellow=True, distance=30)
        assert not handle["active"] and radio.handles[-1]["job"]["action_code"] == "LOCAL_YELLOW"
        radio.output.shutdown()


def test_fast_renewed_approach_requires_separation_from_previous_call():
    with TemporaryDirectory() as tmp, patch.dict("os.environ", {
        "ASURADA_PERSONALITY_ENABLED": "1",
        "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
    }):
        radio = Radio(defence=True)

        def observe(distance):
            radio.frame(primary="NONE", candidate=False, gap=1.4, distance=distance)
            radio.output.backend.complete_all()
            radio.output.tick()

        # Call at long range, then the pursuer comes close and falls back, still
        # nearer than it was when the first line started.
        for n in range(12):
            observe(125 - 3 * n)
        assert len(radio.handles) == 1
        for _ in range(75):
            observe(28)
        for n in range(8):
            observe(34 - n)
        assert len(radio.handles) == 1
        for _ in range(15):
            observe(112)
        for n in range(15):
            observe(112 - 2.5 * n)
        assert len(radio.handles) == 2
        assert all(h["job"]["metadata"]["defence_window"]["target"] == 16 for h in radio.handles)
        radio.output.shutdown()


def test_defence_location_requires_two_speeds_and_a_mapped_encounter():
    from asurada.defence_approach import DefenceApproach

    def sample(start, measured_rate=20, driver_change=False, supported=False):
        detector = DefenceApproach()
        for i in range(6):
            t = i / 10
            s = _state(gap_ahead=2, drs_available=False)
            s.track = "Jeddah"
            s.raw.update(brake=0, current_lap_invalid=False)
            p = s.player
            p.speed_kph = 180
            p.gap_confidence_behind = "high"
            p.lap_distance_m = start + t * 50
            rear = replace(p, car_index=i if driver_change else 8, speed_kph=252,
                           lap_distance_m=p.lap_distance_m - (80 - t * measured_rate), pit_status="NONE")
            result = detector.observe(s, rear, t,
                        dict(recommended=supported, target=8, corner="Corner 01 Braking"))
        return result

    assert sample(5900)["text"] == "守主直道。"
    assert sample(180, supported=True)["text"] == "守一号弯。"
    assert sample(180, supported=False) is None
    assert sample(5900, measured_rate=0) is None
    assert sample(5900, driver_change=True) is None


def test_braking_on_straight_requires_measured_convergence():
    from asurada.defence_approach import DefenceApproach

    def approaching(start, frozen=False):
        detector = DefenceApproach()
        for i in range(6):
            t = i / 10
            s = _state(gap_ahead=2, drs_available=False)
            s.track = "Jeddah"
            s.raw.update(brake=0.8, current_lap_invalid=False)
            p = s.player
            p.gap_confidence_behind = "high"
            p.speed_kph = (75 - 27 * t) * 3.6
            p.lap_distance_m = start + 75 * t - 13.5 * t * t
            gap = 60 if frozen else 60 + 2 * t - 15 * t * t
            rear = replace(p, car_index=8, speed_kph=(73 + 3 * t) * 3.6,
                           lap_distance_m=p.lap_distance_m-gap, pit_status="NONE")
            result = detector.observe(s, rear, t, None)
        return result

    assert approaching(5950)["sudden_braking"]
    assert approaching(5950, frozen=True) is None
    assert approaching(300) is None


def test_mapped_defence_at_inclusive_4_5_second_boundary():
    from asurada.defence_approach import DefenceApproach

    def at_boundary(start, initial_gap):
        detector = DefenceApproach()
        for i in range(16):
            t = i / 10
            state = _state(gap_ahead=2, drs_available=False)
            state.track = "Jeddah"
            state.raw.update(brake=0, current_lap_invalid=False)
            player = state.player
            player.speed_kph = 180.0
            player.gap_confidence_behind = "high"
            player.lap_distance_m = start + 50 * t
            gap = initial_gap - 12 * t
            rear = replace(player, car_index=8, speed_kph=223.2, pit_status="NONE",
                           lap_distance_m=player.lap_distance_m - gap)
            forecast = dict(recommended=True, target=8, corner="Corner 01 Braking")
            result = detector.observe(state, rear, t, forecast)
        return result

    for start, text in ((5820, "守主直道。"), (90, "守一号弯。")):
        assert at_boundary(start, 76)["text"] == text
        assert at_boundary(start, 76.0001) is None


def test_battle_line_uses_current_opponent_and_time_to_contact():
    from asurada.battle_speech import battle_line

    state = _state(gap_ahead=.2, drs_available=True)
    state.raw.update(session_time_s=42., world_forward_dir={"x": 1, "z": 0})
    state.player.world_position_x, state.player.world_position_z = 500, 100
    rival = replace(state.player, car_index=8, position=1, name="斯特罗尔", speed_kph=275.)
    state.rivals = [rival]
    forecast = dict(target=8, label="主直道尽头", eta_s=10., gap_s=.2, trend_s_per_s=.025)
    meta = dict(front_car_index=8, phase="forecast", forecast=forecast)
    for distance, expected in ((2, None), (10, None), (24, "主直道尽头找机会。"),
                               (60, "主直道尽头找机会，你在追近斯特罗尔。")):
        rival.world_position_x, rival.world_position_z = 500 + distance, 103
        rival.lap_distance_m = state.player.lap_distance_m + distance
        text, _ = battle_line(state, "attack", meta, "先跟住。", None, None)
        assert text == expected, (distance, text)


def test_one_missing_rear_position_does_not_mask_urgent_instability():
    with TemporaryDirectory() as tmp, patch.dict("os.environ", {
        "ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
    }):
        radio = Radio(defence=True)
        for n in range(10):
            radio.frame(primary="NONE", candidate=False, distance=50 - n, rival=6, gap=1.4)
        active = radio.handles[-1]
        radio.frame(primary="NONE", candidate=False, distance=None, rival=6, gap=1.4)
        assert active["active"]
        radio.frame(primary="NONE", candidate=False, distance=28, rival=6, gap=1.4)
        assert active["active"]
        radio.frame(primary="DYNAMICS_UNSTABLE", candidate=False, distance=None, rival=6, gap=1.4)
        assert not active["active"] and radio.handles[-1]["job"]["action_code"] == "DYNAMICS_UNSTABLE"
        radio.output.shutdown()


def test_close_rear_car_substantiates_active_location_when_forecast_drops():
    with TemporaryDirectory() as tmp, patch.dict("os.environ", {
        "ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
    }):
        radio = Radio(defence=True)
        for _ in range(8):
            radio.frame(primary="DEFEND_WINDOW", distance=18, gap=.25)
        active = radio.handles[-1]
        for distance in (17., 16., 15., 14., 13., 12., 11., 10., 10., 10.1, 10.1):
            radio.frame(primary="DEFEND_WINDOW", candidate=False, distance=distance, gap=.25)
            assert active["active"]
        radio.frame(primary="NONE", candidate=False, distance=32, gap=.8)
        assert not active["active"]
        radio.output.shutdown()


def test_light_steering_during_attack_cannot_override_a_hazard():
    from asurada.attack_opportunity import _block

    state = _state(gap_ahead=.3, drs_available=True)
    state.raw.update(session_time_s=3., result_status=2, pit_status_code=0, brake=0., steer=.2)
    state.player.gap_behind_s = 5.
    state.player.gap_confidence_behind = "high"
    assert _block(state, "NONE") == "driver_busy"
    assert _block(state, "NONE", playing=True) is None
    assert _block(state, "DYNAMICS_UNSTABLE", playing=True) == "safety_or_pressure"
    state.raw["marshal_zone_flag"] = 3
    assert _block(state, "NONE", playing=True) == "safety_or_pressure"
    state.raw.update(marshal_zone_flag=1, brake=.8)
    assert _block(state, "NONE", playing=True) == "driver_busy"


def test_verified_track_closure_survives_lost_projection_but_yields_to_safety():
    for stop in ("lost_closure", "DYNAMICS_UNSTABLE", "LOCAL_YELLOW"):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", {
            "ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
        }):
            radio = Radio(defence=True)
            for n in range(10):
                radio.frame(candidate=False, distance=40-n, rival=6, gap=1.4, rear_speed_delta=36.)
            active = radio.handles[-1]
            for n in range(7):
                radio.frame(candidate=False, distance=30-n, rival=6, gap=1.4, rear_speed_delta=36., lateral=20.)
                assert active["active"]
            if stop == "lost_closure":
                radio.frame(candidate=False, distance=32, rival=6, gap=1.4, lateral=20.)
            else:
                radio.frame(candidate=False, primary=stop, distance=23, rival=6, gap=1.4,
                            rear_speed_delta=36., lateral=20., yellow=stop == "LOCAL_YELLOW")
                assert radio.handles[-1]["job"]["action_code"] == stop
            assert not active["active"]
            radio.output.shutdown()


def test_equal_station_pace_uses_past_passage_across_lap_line():
    from asurada.defence_approach import PursuitPace
    from asurada.track_model import load_track_profile

    pace = PursuitPace()
    state = _state(gap_ahead=2., drs_available=True)
    state.track = "Jeddah"
    length = load_track_profile(state.track).lap_length_m
    rear = replace(state.player, car_index=7, pit_status="NONE")
    history = []
    for n in range(26):
        speed = 270 - 5*n
        absolute = history[-1][0] + speed / 36 if history else length - 85
        history.append((absolute, speed))
        pos, rv = history[max(0, n-10)]
        state.player.lap = 1 + int(absolute >= length)
        state.player.lap_distance_m = absolute % length
        state.player.speed_kph = speed
        rear.lap = 1 + int(pos >= length)
        rear.lap_distance_m = pos % length
        rear.speed_kph = rv
        matched = pace.observe(state, rear, n / 10)
        if n >= 10:
            assert matched is not None and abs(matched["gain_per_s"]) < 1e-7
            assert abs(matched["delay_s"]-1) < 1e-7 and rv - speed == 50
    state.session_epoch += 1
    assert pace.observe(state, rear, 0.) is None and not pace.confirmed_track_closure


def test_braking_does_not_hide_genuinely_faster_rear_car():
    from asurada.defence_radio import DefenceRadio
    radio = DefenceRadio()
    state = _state(gap_ahead=3., drs_available=False)
    state.track = "Jeddah"
    p = state.player
    p.speed_kph = 216.
    p.gap_confidence_behind = "high"
    rear = replace(p, position=p.position+1, car_index=7, pit_status="NONE")
    state.rivals = [rear]
    state.raw.update(result_status=2, pit_status_code=0, brake=.45, steer=.2,
                     world_forward_dir={"x":1., "z":0.}, marshal_zone_flag=1)
    decision = _decision(code="NONE", detail="", setup_method="none", commit_method="none")
    for n in range(45):
        t = n/10
        state.raw["session_time_s"] = t
        distance = 110 - 3 * max(0, n-24)
        p.lap_distance_m = 1300 + 60*t
        p.world_position_x, p.world_position_z = p.lap_distance_m + 200, 100.
        rear.lap_distance_m = p.lap_distance_m-distance
        rear.world_position_x, rear.world_position_z = p.world_position_x-distance, 102.
        rear.speed_kph = 324. if n>24 else 216.
        p.gap_behind_s = distance/60
        cue = radio.observe(state, decision, {})
        if cue and cue["closing"] and not cue["approach"]:
            assert cue["passage_pace"]["gain_per_s"] > 0 and cue["target"] == 7
            return
    raise AssertionError("sustained same-station gain under braking should generate a warning")


def test_early_straight_closure_requires_speed_and_distance_agreement():
    from asurada.defence_approach import DefenceApproach

    for matched_distance, hard_braking in ((True, True), (False, True), (True, False)):
        detector = DefenceApproach()
        for index in range(4):
            time_s = index / 10
            state = _state(gap_ahead=2, drs_available=False)
            state.track = "Jeddah"
            state.raw.update(brake=.76 if hard_braking else 0., steer=.05, current_lap_invalid=False)
            player = state.player
            player.lap_distance_m = 6000 + 75 * time_s - 15 * time_s ** 2
            player.speed_kph = (75 - 30 * time_s) * 3.6
            player.gap_confidence_behind = "high"
            distance = 110 + 3 * time_s - 17 * time_s ** 2 if matched_distance else 110
            rear = replace(player, car_index=8, pit_status="NONE", speed_kph=(72 + 4 * time_s) * 3.6,
                           lap_distance_m=player.lap_distance_m - distance)
            approach = detector.observe(state, rear, time_s, None)
        if matched_distance and hard_braking:
            assert approach["text"] == "守主直道。"
            assert approach["rate_mps"] < 10  # Detected before the old speed-cutoff.
            assert 1.8 < approach["earliest_s"] < approach["latest_s"] <= 4.5
        else:
            assert approach is None

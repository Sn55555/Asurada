from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.output import ConsoleVoiceOutput
from asurada.packet_snapshot import CaptureSnapshotAssembler
from attack_forecast_archive_replay import RadioClock
from replay_defence_field import replay


def test_group_radio_uses_only_reachable_pursuers():
    class TimedBackend(RadioClock):
        def start(self, job):
            self.durations[job.speak_text] = 1.
            return super().start(job)

    for settings, expected in (({}, [8, 16]), ({"blocked": True}, [16]),
                               ({"matching_speed": True}, []), ({"shift_gap": 2.}, [])):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", {
                "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(tmp) / "mode.json"),
                "ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_PERSONALITY_LLM_MODE": "disabled"}):
            backend = TimedBackend({})
            voice = ConsoleVoiceOutput(backend=backend)
            try:
                replay(voice, backend, **settings)
                calls = [job for job in backend.starts if job["defence"]]
                assert len(calls) == int(bool(expected))
                if calls:
                    call = calls[0]
                    bound = call["defence"]
                    assert [car["target"] for car in bound["threats"]] == expected
                    assert bound["key_seconds"] + 1 <= bound["contact_s"]
                    assert "直道" in call["text"] and bound["name"] in call["text"]
                    assert ("他没被挡" in call["text"]) == (len(expected) == 2)
                    assert f"直道防{bound['name']}" in call["text"]
                    assert "追得快" not in call["text"]
                    assert ("两辆" in call["text"]) == (len(expected) == 2)
            finally:
                voice.shutdown()


def test_packet_keeps_rear_timing_chain_through_two_seconds():
    players = [dict(car_index=i, car_position=i + 1, current_lap_num=3, result_status=2,
                    lap_distance_m=900-i*20, total_distance_m=12900-i*20,
                    delta_to_car_in_front_ms=400) for i in range(12)]
    rivals, _ = CaptureSnapshotAssembler()._build_rivals(
        players[4], players, [], [], [], [], [], 4, 5, 180., 6000., 820., 12820., 15)
    positions = {car["position"] for car in rivals}
    assert {6, 7, 8, 9, 10} <= positions and 11 not in positions


def test_admission_requires_one_full_second_after_the_key():
    from asurada.battle_speech import defence_line, phrase_seconds

    key = "劳森在后"
    meta = dict(name="劳森", place="", threats=[{"target": 8}],
                contact_s=1. + phrase_seconds(key))
    assert defence_line(meta)[1] == key
    meta["contact_s"] -= .01
    assert defence_line(meta) is None



def test_multi_reason_requires_a_distinguishing_observation():
    from asurada.battle_speech import defence_line

    meta = dict(name="劳森", place="主直道", contact_s=4.23,
                threats=[{"contact_s": 4.23}, {"contact_s": 4.25}])
    assert defence_line(meta)[0] == "主直道防劳森。两辆。"
    meta["threats"][1]["contact_s"] = 4.49
    assert defence_line(meta)[0] == "直道防劳森。两辆，他会先到。"

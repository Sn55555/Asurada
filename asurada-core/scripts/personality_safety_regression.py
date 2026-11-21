"""Confirm wing evidence, risk preemption, and current-only repeat."""
from dataclasses import replace
import os
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from asurada.config import StrategyThresholds
from asurada.interaction import build_snapshot_query_input_event
from asurada.output import ConsoleVoiceOutput
from asurada.strategy import StrategyEngine
from asurada.wing_damage import approaching_wing_corner, wing_radio_text
from asurada.wheel_telemetry import tyre_alert
from phase3_voice_regression import FakeSpeechBackend, make_state, make_strategy_decision
from regression_support import emit_result


def scene(clock, right=0, left=0, **changes):
    state = make_state()
    state.source_timestamp_ms = 1000 + clock * 100
    state.raw.update(
        timing_mode="race_like", timing_support_level="official_preferred", session_type="Race",
        session_time_s=clock / 10, result_status=2, brake=0, steer=0,
        wing_damage_pct={"front_left": left, "front_right": right},
        tyres_damage_pct=[0, 0, 0, 0],
    )
    for key, value in changes.items():
        setattr(state, key, value)
    return state


def run():
    engine = StrategyEngine(StrategyThresholds())
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    states = []

    def submit(state):
        states.append(state)
        decision = engine.evaluate(state, states[-5:])
        output.emit(decision, state=state, render=False)
        return decision

    def complete():
        backend.complete_all()
        output.tick()

    submit(scene(0))
    submit(scene(1, right=31))
    no_first_sample = not backend._handles
    submit(scene(2, right=31))
    assert [handle["job"]["action_code"] for handle in backend._handles] == ["FRONT_WING_DAMAGE"]
    side = backend._handles[-1]["job"]["speak_text"]
    complete()
    submit(scene(3, right=31))
    held = len(backend._handles) == 1
    submit(scene(4))
    submit(scene(5))
    submit(scene(6, right=32))
    submit(scene(7, right=32))
    wing_rearmed = len(backend._handles) == 2
    prior = backend._handles[-1]

    safety = scene(8, right=32, safety_car="FULL")
    actual = submit(safety)
    assert actual.messages[0].code == "SAFETY_CAR"
    safety_started = len(backend._handles) == 3 and not prior["active"]
    complete()
    current = scene(9)
    submit(current)
    event = build_snapshot_query_input_event(state=current, query_kind="repeat_last")
    debug = output.emit_control_query_bundle(
        state=current, bundle={"structured_query": {"query_kind": "repeat_last"}, "input_event": event.to_dict()},
        render=False,
    )
    no_stale = debug["output_lifecycle"]["event"]["event_type"] != "start"
    output.shutdown()
    return {
        "one_sample_is_not_a_warning": no_first_sample,
        "right_side_is_spoken_without_claiming_loss_of_control": side.startswith("右前翼受损，损伤程度百分之三十一。")
        and "前轮抓地可能下降" in side and "左前翼" not in side,
        "continuous_damage_dedups": held,
        "repair_allows_new_warning": wing_rearmed,
        "urgent_warning_interrupts_wing": safety_started,
        "repeat_ignores_resolved_safety_warning": no_stale,
        **corner_checks(),
        **compensation_checks(),
        **compensation_checks(combined=True),
        **queued_wing_checks(),
        **tyre_wording_checks(),
    }


def corner_checks():
    engine = StrategyEngine(StrategyThresholds())
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    history = []

    def submit(clock, distance, *, track="Miami", damage=31, brake=0, tyre=None, weather=None):
        state = scene(clock, right=damage, track=track)
        state.raw["wing_damage_pct"]["rear"] = 0
        if tyre:
            state.player.tyre.compound = tyre
        if weather:
            state.weather = weather
        state.player.lap_distance_m = distance
        state.player.speed_kph = 277
        state.raw["brake"] = brake
        history.append(state)
        output.emit(engine.evaluate(state, history[-4:]), state=state, render=False)
        backend.complete_all()
        output.tick()
        return state

    try:
        submit(0, 1830)
        submit(1, 1840)
        submit(2, 2180)
        submit(3, 2190)
        second_straight = submit(4, 4000)
        after_entry = submit(5, 3015, brake=.6)
        unknown = submit(6, 2180, track="Unmapped")
        dry = submit(7, 2180, tyre="C4", weather="Overcast")
        wet = submit(8, 2180, tyre="C4", weather="LightRain")
        reference = wing_radio_text(("front_right",), approaching_wing_corner(dry), levels={"front_right": 31})
        fast = scene(9, right=31, track="Spa")
        fast.player.lap_distance_m = 685
        fast.player.speed_kph = 170
        fast_corner = approaching_wing_corner(fast)
        fast_text = wing_radio_text(("front_right",), fast_corner, levels={"front_right": 31})
        wings = [item["job"]["speak_text"] for item in backend._handles
                 if item["job"]["action_code"] == "FRONT_WING_DAMAGE"]
        return {
            "early_generic_then_one_named_cue": len(wings) == 2 and "号弯" not in wings[0]
            and "十一号弯，早点刹车" in wings[1] and "向左打方向" in wings[1]
            and "车头可能不跟方向" not in wings[1],
            "greater_damage_calls_for_slower_entry": "再慢一点入弯" in wing_radio_text(
                ("front_right",), approaching_wing_corner(second_straight), levels={"front_right": 45}),
            "second_straight_has_distinct_real_turn": approaching_wing_corner(second_straight)["label"] == "十七号弯",
            "past_entry_or_unmapped_never_claim_a_turn": approaching_wing_corner(after_entry) is None
            and approaching_wing_corner(unknown) is None,
            "miami_dry_c4_reference_keeps_order_and_front_wheel_units": reference.startswith(
                "右前翼受损，损伤程度百分之三十一。十一号弯，早点刹。")
            and "时速九十到九十五，前轮左转五到九度" in reference
            and not approaching_wing_corner(wet)["entry_reference"],
            "turn_response_warning_follows_corner_type_not_straight_speed": fast_corner["high_speed"]
            and "方向慢一点打" in fast_text and not approaching_wing_corner(dry)["high_speed"]
            and "方向慢一点打" not in reference,
        }
    finally:
        output.shutdown()


def compensation_checks(*, combined=False):
    engine = StrategyEngine(StrategyThresholds())
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)
    history = []

    def submit(clock, *, distance=689, ahead=4, behind=4, left=0, safety_car="NONE"):
        state = scene(clock, right=31, left=left, track="Spa", safety_car=safety_car)
        state.player.lap_distance_m = distance
        state.player.speed_kph = 170
        state.player.gap_ahead_s = ahead
        state.player.gap_behind_s = behind
        history.append(state)
        return output.emit(engine.evaluate(state, history[-4:]), state=state, render=False)["event"]

    try:
        distance = 689 if combined else 655
        submit(0, distance=distance)
        damage = submit(1, distance=distance)
        if combined:
            combined_text = backend._handles[-1]["job"]["speak_text"]
            submit(2)
            no_duplicate_during_playback = len(backend._handles) == 1
            backend.complete_all()
            output.tick()
            submit(3)
            no_duplicate_after_completion = len(backend._handles) == 1
            submit(4, left=35)
            new_warning = submit(5, left=35)
            second_handle = backend._handles[-1]
            second_side = second_handle["job"]["speak_text"]
            urgent = submit(6, left=35, safety_car="FULL")
            return {
                "damage_and_compensation_share_one_neutral_job": damage["action_code"] == "FRONT_WING_DAMAGE"
                and damage["priority"] == 60 and damage["metadata"].get("wing_compensation") == "combined"
                and combined_text == "右前翼受损，损伤程度百分之三十一。入弯前收油，方向慢一点打。",
                "combined_cue_is_not_repeated_during_or_after_playback":
                    no_duplicate_during_playback and no_duplicate_after_completion,
                "a_new_side_does_not_repeat_reported_damage": second_side.startswith("左前翼受损，")
                and "右前翼" not in second_side,
                "urgent_warning_interrupts_combined_compensation":
                    new_warning["metadata"].get("wing_compensation") == "combined"
                    and urgent["action_code"] == "SAFETY_CAR" and not second_handle["active"],
            }
        backend.complete_all()
        output.tick()
        attacking = submit(2, ahead=.4)
        defensive = submit(3, behind=.4)
        backend.complete_all()
        output.tick()
        neutral = submit(4)
        handle = backend._handles[-1]
        submit(5, behind=.4)
        backend.complete_all()
        output.tick()
        late = submit(6, distance=1000)
        return {
            "compensation_starts_as_separate_non_tactical_job": damage["action_code"] == "FRONT_WING_DAMAGE"
            and neutral["action_code"] == "FRONT_WING_ENTRY_COMPENSATION"
            and neutral["priority"] == 60,
            "standalone_compensation_only_says_the_action": handle["job"]["speak_text"] ==
                "入弯前收油，方向慢一点打。",
            "compensation_stays_silent_during_attack_and_defence": all(
                event["action_code"] != "FRONT_WING_ENTRY_COMPENSATION" for event in (attacking, defensive)),
            "defence_interrupts_active_compensation": not handle["active"],
            "missed_compensation_is_not_played_late": late["action_code"] != "FRONT_WING_ENTRY_COMPENSATION",
        }
    finally:
        output.shutdown()


def queued_wing_checks():
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)

    def submit(clock, left, right, *, code="FRONT_WING_DAMAGE", priority=71, interrupt=False):
        state = scene(clock, right=right, left=left)
        title = "、".join(side for side, value in (("左前翼", left), ("右前翼", right)) if value >= 30)
        decision = make_strategy_decision(state=state, code=code, priority=priority, title=title, detail="")
        decision.debug["arbiter_v2"]["output"]["final_voice_action"]["interrupt"] = interrupt
        return output.emit(decision, state=state, render=False)["event"]

    def finish():
        backend.complete_all()
        output.tick()

    try:
        submit(0, 0, 0, code="ERS_LOW", priority=80)
        submit(1, 88, 0)
        submit(2, 88, 31, priority=72)
        finish()
        merged = backend._handles[-1]
        text = merged["job"]["speak_text"]
        submit(3, 88, 55, priority=72, interrupt=True)
        still_playing = merged["active"] and len(backend._handles) == 2
        finish()
        right_update = backend._handles[-1]
        submit(4, 88, 55, code="DYNAMICS_UNSTABLE", priority=90, interrupt=True)
        return {
            "confirmed_sides_merge_while_waiting": text ==
                "左前翼受损，损伤程度百分之八十八。右前翼受损，损伤程度百分之三十一。前轮抓地可能下降。",
            "wing_update_waits_even_with_interrupt_flag": still_playing
                and right_update["job"]["speak_text"].startswith("右前翼受损，损伤程度百分之五十五。")
                and "左前翼" not in right_update["job"]["speak_text"],
            "instability_still_interrupts_wing": not right_update["active"]
                and backend._handles[-1]["job"]["action_code"] == "DYNAMICS_UNSTABLE",
        }
    finally:
        output.shutdown()


def tyre_wording_checks():
    from asurada.capability_definitions import CAPABILITIES

    state = scene(1, right=31)
    wheel = [27, 31, 28, 35]
    state.raw.update(tyres_damage_pct=wheel, tyres_wear_pct=wheel)
    message = StrategyEngine(StrategyThresholds()).evaluate(state).messages[0]
    query, _ = CAPABILITIES["damage_status"].invoke(state=state)
    worn = "右前这条胎，磨损百分之三十五。"
    return {
        "matched_channels_are_spoken_as_wear": message.code == "TYRE_WEAR_ALERT" and message.title == worn,
        "damage_summary_labels_wing_and_wear_separately": "前翼 31%" in query and worn in query,
        "separate_damage_above_quantization_is_spoken_as_damage": tyre_alert(
            [27, 31, 28, 48], wheel) == ("TYRE_DAMAGE", "轮胎受损。右前轮，百分之四十八。"),
        "one_point_or_missing_wear_is_not_independent_damage": tyre_alert(
            [27, 31, 28, 36], wheel) == ("TYRE_WEAR_ALERT", worn)
            and tyre_alert([27, 31, 28, 48], None) is None,
    }


if __name__ == "__main__":
    with TemporaryDirectory(dir="/tmp") as temp, patch.dict(os.environ, {
        "ASURADA_PERSONALITY_ENABLED": "1",
        "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(temp) / "attack.json"),
    }):
        emit_result(run())

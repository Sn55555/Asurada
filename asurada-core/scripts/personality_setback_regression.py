"""Verify evidence-based setback wording and scoped joke opt-out."""
from dataclasses import replace
from unittest.mock import patch

from asurada.assessment import assess_domain
from asurada.models import StrategyDecision
from asurada.output import ConsoleVoiceOutput
from asurada.personality_runtime import PersonalityRuntime
from asurada.personality_setback import ContactFollowup, damage_sample
from personality_acceptance_regression import low_load_state
from phase3_voice_regression import FakeSpeechBackend
from regression_support import emit_result


def damage(state, pct=0):
    state.raw.update(wing_damage_pct={"front_left": 0, "front_right": pct, "rear": 0},
                     tyres_damage_pct=[0, 0, 0, 0])
    return state


def test_contact():
    state = damage(low_load_state())
    base = damage_sample(state)
    known = ContactFollowup("minor", 10., base)
    unknown = ContactFollowup("unknown", 10., None)
    confirmed = ContactFollowup("severe", 10., base)
    checks = {
        "known_stable_damage_baseline": known.observe(state, 10.5)[0] == "contact_minor",
        "missing_baseline_keeps_uncertainty": unknown.observe(state, 10.5)[0] == "contact_unknown",
    }
    damage(state, 18)
    checks["new_damage_corroborates_impact"] = confirmed.observe(state, 10.5)[0] == "contact_severe"
    # A gap does not establish continuous recovery.
    checks["time_gap_does_not_confirm_recovery"] = confirmed.observe(state, 13.)[0] == "contact_severe"
    for t in [13.4, 13.8, 14.2, 14.6, 15.0]:
        recovery = confirmed.observe(state, t)
    checks["sustained_stability_confirms_recovery"] = recovery[0] == "contact_recovered"
    state.player.speed_kph = 35.
    state.raw.update(result_status=3, session_type="Race", session_time_s=101.)
    damage(state, 31)
    state.assessment = None
    assess_domain(state)
    state.personality = PersonalityRuntime().observe_snapshot(state, StrategyDecision([]))
    output = ConsoleVoiceOutput(backend=FakeSpeechBackend())
    result = output.emit(StrategyDecision([]), state=state, render=False)
    checks["damaged_finish_is_factual_not_joke"] = (
        result["event"]["action_code"] == "PERSONALITY_DAMAGED_FINISH"
        and not result["event"]["metadata"]["personality"]["humorous"])
    return checks


def test_jokes():
    state = low_load_state(stage=2)
    backend = FakeSpeechBackend()
    output = ConsoleVoiceOutput(backend=backend)

    def say(text, turn, clock):
        state.personality = replace(state.personality, clock_s=clock)
        result = output.emit_personality_reply(state=state, text=text, request_id=turn, render=False)
        return result["output_lifecycle"]["event"]

    first = say("计时器累了", "voice-1", 10)
    backend.complete_all()
    opt_out = say("这个别再提", "voice-2", 12)
    same = say("计时器累了", "voice-3", 160)
    other = say("你算慢了", "voice-4", 170)
    backend.complete_all()
    output.tick()
    state.personality = replace(state.personality, low_load=False)
    danger = say("你算慢了", "voice-5", 350)
    return {
        "driver_setup_matches_specific_low_load_response": first["event_type"] == "start"
        and "计时器" in first["speak_text"],
        "opt_out_mutes_only_named_previous_joke": opt_out["metadata"]["reason"] == "specific_joke_muted"
        and same["event_type"] == "suppress" and other["event_type"] == "start",
        "high_load_suppresses_driver_initiated_joke": danger["event_type"] == "suppress",
    }


if __name__ == "__main__":
    with patch.dict("os.environ", {"ASURADA_PERSONALITY_ENABLED": "1", "ASURADA_HUMOR_ENABLED": "1"}):
        emit_result({**test_contact(), **test_jokes()})

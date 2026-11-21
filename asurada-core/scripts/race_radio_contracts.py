"""Deterministic boundaries for natural radio turns, independent of model quality."""
from dataclasses import replace
import json
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.radio_grounding import explicit_advice_choice, ground
from asurada.radio_understanding import radio_intent
from asurada.voice_input import VoiceInputCoordinator
from phase3_semantic_voice_regression import _make_state, _make_turn
from race_radio_replay import Replay


def resumed_telemetry():
    replay = Replay(True)
    try:
        replay.strategy(wing=0)
        replay.finish()
        wing = replay.ask("wing", "给我查下车鼻右侧损伤百分比。")
        replay.strategy(flag=3)
        replay.finish()
        events = replay.output.read_events(limit=128)["events"]
        speech = next(row for row in events if row["event"]["event_type"] == "start"
                      and row["event"]["action_code"] == "QUERY_FRONT_WING_DAMAGE_STATUS")
        assert any(row["event"]["event_type"] == "cancel" and
                   row["event"]["output_event_id"] == speech["event"]["output_event_id"] for row in events)
        replay.interrupted_ref = speech["sequence"]

        def read_new_snapshot():
            replay.current[0].raw["wing_damage_pct"]["front_right"] = 42
            return replay.latest()

        replay.voice.race_radio.latest = read_new_snapshot
        resume = replay.ask("resume", "把刚才没讲完的接着说完。")
        assert wing["passed"] and "31%" in wing["output"]
        assert resume["passed"] and "42%" in resume["output"]
        return [wing["output"], resume["output"]]
    finally:
        replay.service.close()
        replay.tmp.cleanup()


def run():
    turn = _make_turn("test-turn", "我这圈就进站")
    anchor = dict(status="complete", pit_id="advice-1", ref=1)
    proposed = dict(act="commit", topic="pit", query="none", anchor=anchor)
    calls = []
    def save(**fields):
        calls.append(fields)
        return dict(status="queued")
    def verify(turn, text, **changes):
        return VoiceInputCoordinator._validate_radio_choice(
            dict(proposed, **changes), turn, text, _make_state(), save)["act"]
    assert verify(turn, turn.metadata["transcript_text"]) == "commit"
    assert calls[0]["interpretation"] == dict(id="advice-1",topic="pit",choice="accept")
    assert verify(turn, "我觉得这圈手感还好") == "clarify"
    assert verify(turn, "如果我这圈就进站呢") == "clarify"
    assert verify(turn, "我这圈就进站", anchor=dict(anchor,status="cancel")) == "clarify"
    assert verify(replace(turn,completion_reason="recognized_partial"), "我这圈就进站") == "clarify"
    assert verify(replace(turn,metadata={"transcript_hint":"我不进站"}),"我这圈就进站") == "clarify"
    assert len(calls) == 1
    assert explicit_advice_choice("我现在不节油","fuel","decline")
    assert not explicit_advice_choice("我现在不节油","fuel","accept")
    r = Replay(False)
    class TimeoutRadio:
        latest = None
        def interpret(self,*args):
            return None
    try:
        r.voice.race_radio = TimeoutRadio()
        r.strategy();r.finish()
        row=r.ask("commit","算了，我这圈就进去")
        assert row["query"]=="radio_reply" and row["act"]=="clarify",row
        r.finish()
        s,_=r.frame()
        expected=r.output._attack_subject(s)
        r.output.observe_attack_choice(s, {"radio_topic":"attack","radio_act":"hold"},s.source_timestamp_ms)
        assert expected and r.output.attack_deferred(s)
        r.output.observe_attack_choice(s, {"radio_topic":"attack","radio_act":"commit"},s.source_timestamp_ms+1)
        assert not r.output.attack_deferred(s)
        anchor=dict(rival=99, ref=1)
        intent=radio_intent("他呢",dict(act="ask",topic="attack",query="front_gap",anchor=anchor),s)
        assert intent.metadata["radio_act"]=="clarify"
        s.raw["marshal_zone_flag"] = 3
        intent = radio_intent("test", dict(act="commit",topic="attack",query="none",anchor=None),s)
        assert intent.query_kind == "race_control_status" and intent.metadata["radio_topic"] == "control"
        interrupted = dict(ref=12, code="QUERY_FRONT_WING_DAMAGE_STATUS", text="右前翼损伤 24%。")
        resume = ground("请继续", dict(act="resume", query="current_strategy", anchor={"ref":99}), interrupted)
        another = ground("这个弯继续防守？", dict(act="ask",query="why_defend",topic="defend",anchor=None), interrupted)
        assert another["act"] == "ask" and another["query"] == "why_defend"
        assert (resume["anchor"], resume["query"], resume["wing_side"]) == (
            interrupted, "front_wing_damage_status", "front_right")
    finally:
        r.service.close();r.tmp.cleanup()
    return dict(explicit_choice_preserves_original_and_id=True, partial_conflict_hypothesis_unfinished_blocked=True,
                compound_never_cancels_on_timeout=True, changed_rival_requires_clarification=True,
                delay_and_change_of_mind_update_same_opponent=True,
                yellow_blocks_attack_commit=True, resume_uses_interrupted_event_and_side=True,
                resumed_telemetry=resumed_telemetry())

if __name__=="__main__":
    with TemporaryDirectory() as tmp, patch.dict(os.environ, ASURADA_PERSONALITY_ENABLED="1",
                                                 ASURADA_ATTACK_MODE_STATE_PATH=tmp+"/attack.json",
                                                 ASURADA_PIT_EVIDENCE_DB=tmp+"/pit.db",
                                                 ASURADA_TRAINING_MEMORY_DB=tmp+"/training.db",
                                                 ASURADA_RELATIONSHIP_DB=tmp+"/growth.db"):
        print(json.dumps(run(),ensure_ascii=False,indent=2))

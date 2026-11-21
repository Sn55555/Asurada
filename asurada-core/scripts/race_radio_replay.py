"""Compare the normal voice entry point on identical synthetic race scenes and unseen transcripts."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from phase3_semantic_voice_regression import _make_turn
from phase3_voice_regression import FakeSpeechBackend
from personality_safety_regression import scene
from asurada.speech_service import SpeechService
from asurada.speech_client import SharedSpeechClient
from asurada.snapshot_contract import snapshot_payload
from asurada.config import StrategyThresholds
from asurada.output import ConsoleVoiceOutput
from asurada.radio_understanding import RaceRadio
from asurada.strategy import StrategyEngine
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_interrupt import VoiceTurnInterruption

# Expected interpretation is assigned from the scenario, before reading any utterances.
EXPECTED = dict(rear=("ask", "rear_gap"), wing=("ask", "front_wing_damage_status"),
                resume=("resume", "front_wing_damage_status"), flags=("ask", "race_control_status"),
                hold=("hold", "radio_reply"), commit=("commit", "radio_reply"),
                fuel=("ask", "fuel_status"), compound=("hold", "rear_gap"),
                report=("report", "radio_reply"), ers=("ask", "ers_status"))


class Replay:
    def __init__(self, enabled):
        self.backend = FakeSpeechBackend()
        self.output = ConsoleVoiceOutput(backend=self.backend)
        self.tmp = TemporaryDirectory(dir="/tmp")
        self.publication = Path(self.tmp.name) / "latest_snapshot.json"
        self.service = SpeechService(Path(self.tmp.name) / "voice.sock", output=self.output,
                                     session_source=self.publication).start()
        self.client = SharedSpeechClient(self.service.path)
        self.voice = VoiceInputCoordinator(race_radio=RaceRadio(latest=self.latest) if enabled else None,
                                           enable_llm_sidecar=False)
        self.interruption = VoiceTurnInterruption(self.client)
        self.interrupted_ref = None
        self.engine = StrategyEngine(StrategyThresholds())
        self.frames = []
        self.turns = []

    def frame(self, *, flag=0, wing=31):
        state = scene(len(self.frames)+1, right=wing)
        state.raw.update(marshal_zone_flag=flag, frame_identifier=100+len(self.frames),
                         overall_frame_identifier=100+len(self.frames))
        state.raw["source_timestamp_ms"] = state.source_timestamp_ms = int(time.time()*1000)
        # Same named front and rear targets in both variants.
        front = replace(state.player, car_index=7, position=state.player.position-1, name="前车")
        state.rivals = [r for r in state.rivals if r.position != front.position] + [front]
        self.frames.append(state)
        decision = self.engine.evaluate(state, self.frames[-5:])
        self.current = state, decision
        self.publish(state, decision)
        return state, decision

    def publish(self, state, decision):
        payload = snapshot_payload(state, decision)
        temp = self.publication.with_suffix(".tmp")
        temp.write_text(json.dumps(payload))
        temp.replace(self.publication)

    def latest(self):
        state, decision = self.current
        state.source_timestamp_ms = state.raw["source_timestamp_ms"] = int(time.time()*1000)
        decision = self.engine.evaluate(state, self.frames[-5:])
        self.publish(state, decision)
        return state, decision.messages[0] if decision.messages else None

    def strategy(self, **kwargs):
        state, decision = self.frame(**kwargs)
        self.client.emit(decision, state=state, render=False)
        return decision

    def finish(self):
        self.backend.complete_all()
        self.output.tick()

    def ask(self, goal, text):
        state, decision = self.frame()
        self.primary = decision.messages[0] if decision.messages else None
        now = int(time.time()*1000)
        turn = replace(_make_turn("radio-%d" % len(self.turns), text), started_at_ms=now, ended_at_ms=now)
        start = time.monotonic()
        context = self.interruption.begin(state=state)
        result = self.voice.process_completed_turn(state=state, turn=turn,
            voice_output=self.interruption.output_for(context), context=context,
            primary_message=self.primary, render=False)
        schema = (result.bundle or {}).get("structured_query", {})
        meta = schema.get("metadata", {}).get("semantic_metadata", {})
        lifecycle = (result.output_debug or {}).get("output_lifecycle", {}).get("event", {})
        query = schema.get("query_kind")
        act = meta.get("radio_act") or ("ask" if query not in {"open_fallback","cancel","stop",None} else None)
        expected_act, expected_query = EXPECTED[goal]
        side_ok = goal not in {"wing", "resume"} or "右前翼" in (lifecycle.get("speak_text") or "")
        target_ok = goal not in {"hold","commit","compound"} or meta.get("radio_topic") == "attack"
        reference_ok = goal != "resume" or (self.interrupted_ref is not None and
                                            meta.get("radio_reference") == self.interrupted_ref)
        passed = (reference_ok and query == expected_query and act == expected_act and side_ok and target_ok
                  and lifecycle.get("event_type") == "start")
        self.turns.append(dict(goal=goal, input=text, act=act, query=query, topic=meta.get("radio_topic"),
            reference=meta.get("radio_reference"), output=lifecycle.get("speak_text"), event=lifecycle.get("event_type"),
            expected=[expected_act,expected_query], passed=passed, latency_ms=round((time.monotonic()-start)*1000)))
        return self.turns[-1]


def run(rows, enabled):
    result, interruptions = [], []
    group_size = sum(row["goal"] == "rear" for row in rows)
    for index in range(group_size):
        r = Replay(enabled)
        try:
            def ask(goal):
                group = [row for row in rows if row["goal"] == goal]
                return r.ask(goal, group[index]["text"])
            r.strategy(wing=0)
            r.finish()
            for goal in ["rear", "hold", "commit", "compound"]:
                ask(goal)
                r.finish()
            r.strategy(wing=31)
            r.finish()
            r.strategy(wing=31)
            r.finish()
            wing = ask("wing")
            r.strategy(flag=3)
            page = r.output.read_events(limit=128)["events"]
            events = [row["event"] for row in page]
            starts = [row for row in page if row["event"]["event_type"] == "start"
                      and row["event"]["action_code"] == "QUERY_FRONT_WING_DAMAGE_STATUS"
                      and row["event"]["speak_text"] == wing["output"]]
            if starts and any(e["event_type"] == "cancel" and
                              e["output_event_id"] == starts[-1]["event"]["output_event_id"] for e in events):
                r.interrupted_ref = starts[-1]["sequence"]
            interrupted = any(e["event_type"] in {"cancel", "cancel_requested"} and
                              e["speak_text"] == wing["output"] for e in events)
            started = any(e["action_code"] == "LOCAL_YELLOW" and e["event_type"] == "start" for e in events)
            interruptions.append(dict(yellow_started=started, wing_interrupted=interrupted, wing_reference=r.interrupted_ref,
                                      events=[dict(kind=e["event_type"], code=e["action_code"]) for e in events[-5:]]))
            r.finish()
            for goal in ["resume", "flags", "fuel", "report", "ers"]:
                ask(goal)
                r.finish()
            result.extend(r.turns)
        finally:
            r.service.close()
            r.tmp.cleanup()
    return dict(turns=result, passed=sum(t["passed"] for t in result), interruptions=interruptions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    rows=json.loads(args.corpus.read_text())
    count = sum(r["goal"] == "rear" for r in rows)
    assert count and len(rows) == count * len(EXPECTED)
    assert all(sum(r["goal"] == goal for r in rows) == count for goal in EXPECTED)
    with TemporaryDirectory() as tmp, patch.dict(os.environ, {
        "ASURADA_ATTACK_MODE_STATE_PATH":tmp+"/attack.json","ASURADA_PERSONALITY_ENABLED":"1",
        "ASURADA_PIT_EVIDENCE_DB":tmp+"/pit.db",
        "ASURADA_TRAINING_MEMORY_DB":tmp+"/training.db","ASURADA_RELATIONSHIP_DB":tmp+"/growth.db"}):
        result = {}
        for name in ["baseline","candidate"]:
            result[name]=run(rows,name=="candidate")
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
            print(name,result[name]["passed"],flush=True)

if __name__=="__main__":
    main()

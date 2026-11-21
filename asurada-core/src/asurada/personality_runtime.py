"""Read-only race personality projection, shared by live UDP and capture replay."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import time

from .output_contracts import CAUTION_SPEECH_CODES, strategy_speech_band
from .personality_setback import ContactFollowup, SETBACK_LINES, damage_sample
from .personality_memory import Relationship, RelationshipStore
from .persona_registry import get_default_persona
from .wheel_telemetry import tyre_alert

RACE_SESSIONS = {"Race", "SprintRaceLike(15)", "FeatureRaceLike(16)"}
POSITIVE_EVENTS = {"overtake", "fastest_lap"}
# F1 25 Event appendices: warning, and minor running-wide infringement.
WARNING_PENALTY = 5
MINOR_RUNNING_WIDE = 27


def personality_enabled() -> bool:
    return os.getenv("ASURADA_PERSONALITY_ENABLED", "0") == "1"


@dataclass(frozen=True)
class PersonalitySnapshot:
    session_uid: str
    session_epoch: int
    source_timestamp_ms: int
    snapshot_id: str
    clock_s: float
    tone: str
    concern: float
    tyre_concern: float
    excitement: float
    trigger: str | None
    event_id: str | None
    opportunity: str | None
    opportunity_age_s: float | None
    low_load: bool
    stage: int
    memory_kind: str | None
    pit_cooperation: dict | None = None

    def __post_init__(self) -> None:
        if (type(self.stage) is not int or not 0 <= self.stage <= 3 or type(self.low_load) is not bool
                or self.tone not in ("calm", "firm", "concerned", "excited")
                or self.opportunity not in (None, "finish", "overtake", "fastest_lap", "minor_offtrack", *SETBACK_LINES)):
            raise ValueError("invalid_personality_snapshot")
        values = (self.clock_s, self.concern, self.tyre_concern, self.excitement)
        if self.opportunity_age_s is not None:
            values += (self.opportunity_age_s,)
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("invalid_personality_timing_or_emotion")
        if self.pit_cooperation is not None and (not isinstance(self.pit_cooperation, dict)
                or any(not isinstance(self.pit_cooperation.get(key), str) or not self.pit_cooperation[key]
                       for key in ("race_id", "recommendation_id", "driver_id"))):
            raise ValueError("invalid_personality_pit_cooperation")

    def matches(self, state) -> bool:
        if (self.session_uid, self.session_epoch, self.source_timestamp_ms) != (
                state.session_uid, state.session_epoch, state.source_timestamp_ms):
            return False
        assessment = state.assessment
        if assessment is None:
            return False
        return self.snapshot_id == assessment.snapshot_id


@dataclass(frozen=True)
class RacePersonalityEvent:
    id: str
    kind: str
    time_s: float


class PersonalityRuntime:
    def __init__(self, *, relationship_db: Path | None = None) -> None:
        self.memory = RelationshipStore(relationship_db) if relationship_db is not None else None
        self.next_memory_refresh = time.monotonic() + 2
        self.reconcile_cooperation_at = None
        self.profile = get_default_persona()
        self.scope = None
        self.state = None
        self.timeline: deque[RacePersonalityEvent] = deque(maxlen=4096)
        self.seen: set[str] = set()
        self.positive_events: dict[str, RacePersonalityEvent] = {}
        self.tyre_risk = None
        self.tyre_signature = None
        self.in_pit = False
        self.finish = None
        self.finish_window_at = None
        self.contact_followup = None
        self.latest_time = 0.0
        self.rewind_to = None

    def close(self) -> None:
        if self.memory is not None:
            drained = self.memory.close()
            print(f"[ASURADA][PERSONALITY-STORE] drained={drained} health={self.memory.health()}")

    def _add(self, kind: str, time_s: float, identity: str) -> None:
        if identity in self.seen:
            return
        event = RacePersonalityEvent(identity, kind, time_s)
        if len(self.timeline) == self.timeline.maxlen:
            self.seen.discard(self.timeline[0].id)
        self.timeline.append(event)
        self.seen.add(identity)
        if kind in POSITIVE_EVENTS and len(self.positive_events) < 256:
            self.positive_events[identity] = event

    def observe_packet(self, envelope, epoch: int, *, replay: bool) -> None:
        """Only called for assembler-accepted packets. Finish need not have a following physics frame."""
        if self.state is None or str(envelope.session_uid) != self.scope[0]:
            return
        header = envelope.payload["header"]
        body = envelope.payload["body"]
        time_s = header.get("session_time_s")
        frame = header.get("overall_frame_identifier")
        if not isinstance(time_s, (float, int)) or not math.isfinite(time_s) or type(frame) is not int:
            return
        code = body.get("event_code")
        detail = body.get("event_detail") or {}
        if envelope.kind == "Event" and code == "FLBK":
            target = detail.get("flashback_session_time_s")
            if isinstance(target, (float, int)) and math.isfinite(target) and target >= 0:
                self.rewind_to = target
            return
        if epoch != self.scope[1] or self.rewind_to is not None or time_s < self.latest_time - 2.0:
            return
        identity = f"{self.scope[0]}:{epoch}:packet:{frame}"
        if envelope.kind == "FinalClassification":
            self._finish_race(body.get("player") or {}, time_s, f"{identity}:finish", replay,
                              source="final_classification")
            return
        if envelope.kind == "LapData":
            self._finish_from_lap(header.get("player_car_index"), body.get("result_status"),
                                  body.get("current_lap_num"), body.get("car_position"),
                                  time_s, identity, replay)
            return
        if self.state.raw.get("session_paused") or time_s > self.latest_time + 5.0:
            return
        car = self.state.player.car_index
        if envelope.kind == "Event":
            if code == "COLL" and car in (detail.get("vehicle_1_idx"), detail.get("vehicle_2_idx")):
                event_id = f"{identity}:COLL"
                if event_id not in self.seen:
                    baseline = damage_sample(self.state) if 0 <= time_s - self.latest_time <= 1 else None
                    self.contact_followup = ContactFollowup(event_id, time_s, baseline)
                self._add("collision", time_s, event_id)
            elif code == "OVTK" and detail.get("overtaking_vehicle_idx") == car:
                self._add("overtake", time_s, f"{identity}:OVTK")
            elif (code == "PENA" and detail.get("vehicle_idx") == car
                  and detail.get("penalty_type") == WARNING_PENALTY
                  and detail.get("infringement_type") == MINOR_RUNNING_WIDE):
                self._add("minor_offtrack", time_s, f"{identity}:minor_offtrack")
            elif code == "FTLP" and detail.get("vehicle_idx") == car and detail.get("lap_time_s", 0) > 0:
                self._add("fastest_lap", time_s, f"{identity}:FTLP")

    def _finish_from_lap(self, car, status, laps, position, time_s, identity, replay):
        # LapData can report a finish even when classification or a full final frame is absent.
        if status == 3:
            self._finish_race(dict(car_index=car, result_status=status, num_laps=laps, position=position),
                              time_s, f"{identity}:finish", replay, source="lap_data")

    def _finish_race(self, player: dict, time_s: float, identity: str, replay: bool, *, source: str) -> None:
        if (self.finish is not None or self.state.raw.get("session_type") not in RACE_SESSIONS
                or player.get("car_index") != self.state.player.car_index
                or player.get("result_status") != 3
                or type(player.get("num_laps")) is not int or player["num_laps"] <= 0
                or type(player.get("position")) is not int or not 1 <= player["position"] <= 22):
            return
        self.finish = identity
        self._add("finish", time_s, identity)
        if self.memory is not None and not replay:
            data = dict(race_id=self.scope[0], epoch=self.scope[1], finish_id=identity, source=source,
                        laps=player["num_laps"], position=player["position"],
                        positive_events=[asdict(event) for event in self.positive_events.values()])
            if not self.memory.record_race(data):
                self.finish = None
            else:
                # The audio service owns the other SQLite writer. Recheck at
                # the next safe boundary if its finishing write was still queued.
                self.reconcile_cooperation_at = time.monotonic() + 2

    def observe_snapshot(self, state, decision, *, replay: bool = True) -> PersonalitySnapshot | None:
        if state.assessment is None:
            return None
        scope = state.session_uid, state.session_epoch
        now = state.raw.get("session_time_s")
        if not isinstance(now, (float, int)) or not math.isfinite(now) or now < 0:
            return None
        if self.memory is not None and not replay and time.monotonic() >= self.next_memory_refresh:
            self.memory.refresh()
            self.next_memory_refresh = time.monotonic() + 2
        paused = bool(state.raw.get("session_paused", False))
        scope_changed = scope != self.scope
        if self.memory is not None and not replay and self.reconcile_cooperation_at is not None:
            due = time.monotonic() >= self.reconcile_cooperation_at
            if (due or scope_changed) and self.memory.reconcile() and due:
                self.reconcile_cooperation_at = None
        if self.rewind_to is not None and not scope_changed and now > self.rewind_to + .1:
            return None
        if scope_changed or self.rewind_to is not None or now < self.latest_time:
            same_session = self.scope is not None and scope[0] == self.scope[0]
            if not same_session:
                self.timeline.clear()
                self.positive_events.clear()
            else:
                # At a rewind retain only evidence from before the retained timeline.
                # With no explicit flashback target use the first accepted frame's time.
                target = min(now, self.rewind_to) if self.rewind_to is not None else now
                self.timeline = deque((e for e in self.timeline if e.time_s < target), maxlen=4096)
                self.positive_events = {key: e for key, e in self.positive_events.items() if e.time_s < target}
            self.seen = {event.id for event in self.timeline}
            self.tyre_risk = None
            self.tyre_signature = None
            self.in_pit = False
            self.finish = None
            self.finish_window_at = None
            self.contact_followup = None
            self.rewind_to = None

        self.state, self.scope, self.latest_time = state, scope, now
        labels = state.assessment.labels
        risky = labels.tyre_state in {"manage", "box_now"}
        signature = state.player.tyre.compound, state.player.tyre.age_laps
        pit = state.raw.get("pit_status_code")
        frame = state.raw.get("overall_frame_identifier", state.source_timestamp_ms)
        identity = f"{scope[0]}:{scope[1]}:snapshot:{frame}"
        self._finish_from_lap(state.player.car_index, state.raw.get("result_status"), state.lap_number,
                              state.player.position, now, identity, replay)
        if not paused and pit in {0, 1, 2}:
            valid_tyre = labels.tyre_state != "unavailable" and signature[0] not in {"", "unknown", "Unknown"}
            if valid_tyre:
                if self.tyre_risk is False and risky:
                    self._add("tyre_risk", now, f"{identity}:tyre_risk")
                if self.in_pit and self.tyre_signature is not None and (
                        signature[1] < self.tyre_signature[1] or signature[0] != self.tyre_signature[0]):
                    self._add("tyre_recovered", now, f"{identity}:tyre_recovered")
                self.tyre_signature = signature
                self.tyre_risk = risky
            self.in_pit = pit != 0

        recent = []
        for event in reversed(self.timeline):
            if event.time_s < now - 242:
                # Accepted event timestamps can trail the latest frame by up to two seconds.
                break
            if 0 <= now - event.time_s <= 240:
                recent.append(event)
        # Preserve insertion order on equal timestamps, including tyre recovery.
        recent = sorted(reversed(recent), key=lambda event: event.time_s)
        emotion = dict(concern=0.0, tyre_concern=0.0, excitement=0.0)
        opportunity = None
        amounts = {"collision": ("concern", .85), "tyre_risk": ("tyre_concern", .75),
                   "overtake": ("excitement", .70), "fastest_lap": ("excitement", .9)}
        for event in recent:
            if event.kind == "tyre_recovered":
                emotion["tyre_concern"] = 0.0
            elif event.kind in amounts:
                field, amount = amounts[event.kind]
                emotion[field] += amount * 2 ** (-(now - event.time_s) / 30)
            age = now - event.time_s
            if (event.kind in POSITIVE_EVENTS and age <= 2
                    or event.kind == "minor_offtrack" and .75 <= age <= 2):
                opportunity = event
        emotion = {key: round(min(1.0, value), 4) for key, value in emotion.items()}
        top = decision.messages[0] if decision.messages else None
        voice_action = ((decision.debug.get("arbiter_v2") or {}).get("output") or {}).get("final_voice_action") or {}
        band = strategy_speech_band(top.code, voice_action.get("interrupt", False)) if top else 0
        caution = (band >= 3 or (top and top.code in CAUTION_SPEECH_CODES)
                   or labels.dynamics_state == "unstable")
        tone = ("concerned" if emotion["concern"] * self.profile.empathy >= .25 else
                "firm" if caution or risky or emotion["tyre_concern"] * self.profile.stubbornness >= .23 else
                "excited" if emotion["excitement"] * self.profile.competitiveness >= .30 else "calm")
        gaps = state.player.gap_ahead_s, state.player.gap_behind_s
        brake = state.raw.get("brake")
        steer = state.raw.get("steer")
        settled_finish = self.finish is not None and state.player.speed_kph <= 40
        light_driving = (pit == 0 and state.raw.get("result_status") == 2 and all(g is not None and g >= 1.25 for g in gaps)
                         and labels.attack_state == "closed" and labels.defend_state == "clear")
        safe_output = (not paused and labels.race_state == "green" and labels.dynamics_state == "stable"
                    and labels.tyre_state == "stable" and not tyre_alert(
                        state.raw.get("tyres_damage_pct"), state.raw.get("tyres_wear_pct"))
                    and brake is not None and 0 <= brake <= .12
                    and steer is not None and abs(steer) <= .12 and band < 3 and (light_driving or settled_finish))
        low_load = safe_output and emotion["concern"] * self.profile.empathy < .25
        opportunity_at = opportunity.time_s if opportunity else None
        contact = self.contact_followup.observe(state, now) if self.contact_followup else None
        if contact is not None and safe_output and 0 <= now - contact[1] <= 2:
            kind, opportunity_at = contact
            opportunity = RacePersonalityEvent(f"{self.contact_followup.event_id}:{kind}", kind, opportunity_at)
            low_load = True
        finish_event = next((event for event in reversed(recent) if event.id == self.finish), None)
        damage = damage_sample(state)
        damaged_finish = settled_finish and damage is not None and max(damage) >= 30
        if finish_event is not None and (low_load or damaged_finish and safe_output) and now - finish_event.time_s <= 30:
            if self.finish_window_at is None:
                self.finish_window_at = now
            if now - self.finish_window_at <= 2:
                opportunity = (RacePersonalityEvent(f"{finish_event.id}:damage", "damaged_finish", finish_event.time_s)
                               if damaged_finish else finish_event)
                opportunity_at = self.finish_window_at
                low_load = True
        relation = self.memory.current if self.memory else Relationship()
        event = opportunity or (recent[-1] if recent else None)
        return PersonalitySnapshot(
            *scope, state.source_timestamp_ms, state.assessment.snapshot_id, now, tone,
            **emotion, trigger=event.kind if event else None, event_id=event.id if event else None,
            opportunity=opportunity.kind if opportunity else None,
            opportunity_age_s=now - opportunity_at if opportunity_at is not None else None,
            low_load=low_load, stage=relation.stage, memory_kind=relation.memory_kind,
            pit_cooperation=relation.last_cooperation,
        )

"""Scoped driving preferences and evidence-backed personal radio cues."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import time

from .brake_habit import BrakeProbe, race_context, race_time, track_profile
from .input_quality import valid_input
from .interaction import SpeechJob
from .output_contracts import _SpeechEnvelope
from .training_memory import TrainingMemory

PREFERENCE_KEY = "radio_long_reason_straight"
EXPLAINERS = frozenset({"why_not_attack", "why_not_pit"})
_REASON = re.compile(r"\s+(?:因为|理由是)\s+")
_STRAIGHTS = frozenset({"straight", "deployment_straight", "attack_straight"})
_CUE_ZONES = _STRAIGHTS | {"exit_traction"}
_RISK = frozenset({"DYNAMICS_UNSTABLE", "SAFETY_CAR", "RED_FLAG", "DEFEND_WINDOW"})
_IMMEDIATE_REASONS = ("缺少", "不能可靠", "无法判断", "无法确认", "不足以", "可信度", "处罚", "管制")


def driver_id():
    return os.getenv("ASURADA_DRIVER_ID", "local").strip() or "local"


def radio_experience_command(text):
    return {
        "长解释留到直道": "enable",
        "取消直道解释": "disable",
        "那几圈是在跟车": "correct_habit",
    }.get(str(text or "").strip().rstrip("。！!?？"))


def _cue_zone(state):
    profile = track_profile(state.track)
    position = state.player.lap_distance_m
    if profile is None or type(position) not in (int, float) or not 0 <= position < float("inf"):
        return None
    return next((zone.zone_type for zone in profile.semantic_segments
                 if zone.start_m <= position < zone.end_m), None)


def _basis(state, query):
    assessment = state.assessment
    if assessment is None:
        return None
    labels = assessment.labels
    record = state.decision_record
    primary = record.actions[0].code if record and record.actions else None
    if query == "why_not_pit":
        raw = state.raw
        tyre = state.player.tyre
        return (
            primary, labels.race_state, labels.tyre_state, state.weather,
            raw.get("pit_status"), raw.get("num_pit_stops"), raw.get("num_unserved_drive_through_pens"),
            raw.get("num_unserved_stop_go_pens"), raw.get("pit_stop_should_serve_pen"),
            tyre.compound, round(tyre.wear_pct, 1),
        )
    front = next((rival for rival in state.rivals if rival.position == state.player.position - 1), None)
    gap = state.player.gap_ahead_s
    return (primary, labels.race_state, labels.attack_state, labels.defend_state,
            labels.dynamics_state, state.player.drs_available, state.player.position,
            front.car_index if front else None, front.pit_status if front else None,
            round(gap, 3) if gap is not None else None)


@dataclass
class _Explanation:
    scope: tuple
    query: str
    request: str
    text: str
    basis: tuple
    expires: float
    completed: bool = False


class RadioExperience:
    def __init__(self, memory=None, *, driver="local", clock=time.time):
        self.memory, self.driver, self.clock = memory, driver, clock
        self.scope = None
        self.pending = None
        self.habit_cue = None
        self.last_habit = None
        self.probe = BrakeProbe()
        self.habits = {}
        self.offered_habits = set()
        self.preference_expires_at = 0
        if memory is not None:
            self._load_preference()
            self.habits = {(row["track"], row["corner"]): row["record"]
                           for row in memory.brake_habits(driver=driver)}

    @classmethod
    def from_env(cls):
        path = os.getenv("ASURADA_TRAINING_MEMORY_DB")
        driver = driver_id()
        return cls(TrainingMemory(Path(path).expanduser()), driver=driver) if path else cls(driver=driver)

    def _load_preference(self):
        records = self.memory.query(driver=self.driver, kind="user_preference")
        self.preference_expires_at = next((record["expires_at"] for record in records
                                            if record["key"] == PREFERENCE_KEY and record["value"] is True), 0)

    def preference_active(self):
        return self.preference_expires_at > self.clock()

    def set_preference(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("radio_preference_requires_boolean")
        if self.memory is None:
            return {"status": "unavailable", "reason": "driver_memory_not_configured"}
        if enabled:
            self.memory.set_radio_straight(driver=self.driver)
        else:
            self.memory.revoke_radio_straight(driver=self.driver)
            self.pending = None
        self._load_preference()
        return {"status": "applied", "driver_id": self.driver, "straight_explanations": self.preference_active()}

    def bind(self, scope):
        if self.scope != scope:
            self.scope = scope
            self.cancel()
            self.last_habit = None
            self.probe.reset()
            self.offered_habits.clear()

    def cancel(self):
        self.pending = self.habit_cue = None

    def maybe_defer(self, state, query, text, *, request_id):
        self.pending = None
        if (query not in EXPLAINERS or not self.preference_active()
                or not race_context(state) or self._safe(state, _STRAIGHTS)):
            return text
        now, basis = race_time(state), _basis(state, query)
        if now is None or basis is None:
            return text
        if any(cue in text for cue in _IMMEDIATE_REASONS):
            return text
        if (match := _REASON.search(text)) is not None:
            conclusion, reason = text[:match.start()], text[match.end():]
        else:
            conclusion, _, reason = text.partition("。")
        if not any(word in conclusion for word in ("先继续", "继续比赛", "先留在赛道", "暂不建议", "没有给出进攻窗口")):
            return text
        reason = reason.lstrip()
        if len(reason) < 18 or not conclusion.strip() or (state.session_uid, state.session_epoch) != self.scope:
            return text
        self.pending = _Explanation(self.scope, query, request_id, reason, basis, now + 15)
        return conclusion.rstrip("。 ，") + "。"

    def _current(self, state, *, live=False):
        return ((state.session_uid, state.session_epoch) == self.scope and race_context(state)
                and (not live or 0 <= self.clock() * 1000 - state.source_timestamp_ms <= 1000))

    def _safe(self, state, zones, *, live=False):
        hint = state.personality
        brake = valid_input("brake", state.raw.get("brake"))
        steer = valid_input("steer", state.raw.get("steer"))
        return (self._current(state, live=live) and hint is not None and hint.matches(state) and hint.low_load
                and brake is not None and brake < .18 and steer is not None and abs(steer) <= .12
                and _cue_zone(state) in zones)

    def observe(self, state, primary_code):
        if self.memory is None:
            return
        now = race_time(state)
        if now is None or not self._current(state) or primary_code in _RISK:
            self.cancel()
            self.probe.reset()
            return
        pending = self.pending
        if pending is not None and (not self.preference_active() or now > pending.expires
                                    or _basis(state, pending.query) != pending.basis):
            self.pending = None
        if not self.habits:
            return
        if self.habit_cue is not None and not self._matches_habit(state, self.habit_cue):
            self.habit_cue = None
        observed = self.probe.observe(state)
        if observed is None:
            return
        identity = observed.track, observed.corner
        if identity in self.offered_habits:
            return
        reference = self.habits.get(identity)
        if (reference is None or (reference["weather"], reference["tyre"]) != (observed.weather, observed.tyre)
                or observed.session in {sample["session"] for sample in reference["training"] + reference["holdout"]}):
            return
        if observed.onset_m + observed.uncertainty_m < reference["onset_low_m"]:
            direction = "更早"
        elif observed.onset_m - observed.uncertainty_m > reference["onset_high_m"]:
            direction = "更晚"
        else:
            return
        self.habit_cue = {
            "track": observed.track, "corner": observed.corner, "lap": observed.lap,
            "weather": observed.weather, "tyre": observed.tyre, "expires": now + 7,
            "direction": direction,
        }

    def _matches_habit(self, state, cue):
        now = race_time(state)
        return (now is not None and now <= cue["expires"]
                and state.raw.get("marshal_zone_flag") in (0, 1)
                and (state.track, state.lap_number, state.weather, state.player.tyre.compound) ==
                (cue["track"], cue["lap"], cue["weather"], cue["tyre"])
                and (cue["track"], cue["corner"]) in self.habits)

    def build_envelope(self, state, *, live, event, task, output_id, persona):
        pending = self.pending
        hint = state.personality
        if pending and pending.completed and self._safe(state, _STRAIGHTS, live=live):
            self.pending = None
            kind = "deferred_reason"
            text = pending.text
            request = pending.request + ":explanation"
            context = {"query": pending.query, "basis": pending.basis, "expires": pending.expires}
        elif self.habit_cue and hint is not None and hint.stage >= 1 and self._safe(state, _CUE_ZONES, live=live):
            kind = "brake_habit"
            context, self.habit_cue = self.habit_cue, None
            self.offered_habits.add((context["track"], context["corner"]))
            text = f"刚才这个弯，这圈比你平时{context['direction']}开始刹车。"
            request = f"habit:{state.session_uid}:{state.session_epoch}:{context['lap']}:{context['corner']}"
        else:
            return None
        job = SpeechJob(output_event_id=output_id(),
                        interaction_session_id=str(event.get("interaction_session_id") or f"runtime:{state.session_uid}"),
                        turn_id=str(event.get("turn_id") or request), request_id=request,
                        snapshot_binding_id=hint.snapshot_id, source_kind="personality_optional",
                        action_code="PERSONALITY_" + kind.upper(), priority=0, speak_text=text,
                        cancelable=True, persona_id=persona.persona_id, voice_profile_id=persona.voice_profile_id,
                        metadata={"optional_personality": True, "repeatable": False, "experience_kind": kind,
                                  "experience_context": context,
                                  "personality": {"tone": "calm", "stage": hint.stage},
                                  "personality_variant_key": kind,
                                  "personality_clock": hint.clock_s})
        return _SpeechEnvelope(job, event, task)

    def applicable(self, state, job, *, live=False):
        context = job.metadata["experience_context"]
        if job.metadata["experience_kind"] == "deferred_reason":
            now = race_time(state)
            return (self.preference_active() and now is not None and now <= context["expires"]
                    and self._safe(state, _STRAIGHTS, live=live)
                    and _basis(state, context["query"]) == context["basis"])
        return (state.personality is not None and state.personality.stage >= 1
                and self._safe(state, _CUE_ZONES, live=live) and self._matches_habit(state, context))

    def completed(self, job):
        if self.pending is not None and job.request_id == self.pending.request:
            self.pending.completed = True
        if job.metadata.get("experience_kind") == "brake_habit":
            context = job.metadata["experience_context"]
            self.last_habit = context["track"], context["corner"]

    def correct_last_habit(self):
        if self.memory is None or self.last_habit is None:
            return {"status": "rejected", "reason": "no_brake_habit_reference"}
        track, corner = self.last_habit
        self.memory.revoke_brake_habit(driver=self.driver, track=track, corner=corner)
        self.habits.pop((track, corner), None)
        self.habit_cue = self.last_habit = None
        return {"status": "applied", "track": track, "corner": corner}

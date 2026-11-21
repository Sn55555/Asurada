"""Classify a confirmed contact conservatively from subsequent telemetry."""
from __future__ import annotations

from dataclasses import dataclass
import math


SETBACK_LINES = {
    "contact_unknown": "刚才有碰撞，车况还没确认。",
    "contact_minor": "刚才有接触，目前未见新增损伤。",
    "contact_severe": "刚才撞击后的车况异常已确认，先留余量。",
    "contact_recovered": "车辆动态已连续稳定，继续留意车损。",
    "damaged_finish": "完赛确认。仍有车损，赛后看一下。",
}


def damage_sample(state):
    wings = state.raw.get("wing_damage_pct")
    tyres = state.raw.get("tyres_damage_pct")
    if not isinstance(wings, dict) or not isinstance(tyres, (list, tuple)) or len(tyres) != 4:
        return None
    values = (wings.get("front_left"), wings.get("front_right"), wings.get("rear"), *tyres)
    if not all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 for value in values):
        return None
    return values


@dataclass
class ContactFollowup:
    event_id: str
    contact_s: float
    baseline: tuple | None
    kind: str | None = None
    kind_at: float | None = None
    last_observation: float | None = None
    stable_since: float | None = None
    severe: bool = False

    def observe(self, state, now):
        if not .45 <= now - self.contact_s <= 30 or state.raw.get("session_paused"):
            return None
        labels = state.assessment.labels
        damage = damage_sample(state)
        known = damage is not None and self.baseline is not None
        delta = max(after - before for before, after in zip(self.baseline, damage)) if known else None
        previous = self.last_observation
        if previous is not None and now <= previous:
            return self.kind_at and (self.kind, self.kind_at)
        self.last_observation = now
        stable = labels.dynamics_state == "stable"
        if labels.dynamics_state == "unstable" or (delta is not None and delta >= 10):
            self.severe = True
        if not stable or previous is None or now - previous > .55:
            self.stable_since = now if stable else None
        elif self.stable_since is None:
            self.stable_since = now
        if self.severe:
            if self.stable_since is not None and now - self.stable_since >= 2:
                self._transition("contact_recovered", now)
            elif self.kind != "contact_recovered":
                self._transition("contact_severe", now)
        elif self.kind is None:
            self._transition("contact_minor" if stable and delta is not None and delta <= 0
                             else "contact_unknown", now)
        return (self.kind, self.kind_at) if self.kind and self.kind_at is not None else None

    def _transition(self, kind, now):
        if self.kind != kind:
            self.kind, self.kind_at = kind, now

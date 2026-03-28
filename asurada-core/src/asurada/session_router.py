from __future__ import annotations

from dataclasses import dataclass

from .models import SessionState


@dataclass
class SessionRoute:
    """Resolved session-mode routing policy for the current frame."""

    session_mode: str
    allowed_action_codes: set[str]
    allow_timing_actions: bool
    allow_race_resource_actions: bool
    route_reason: str


class SessionModeRouter:
    """Route strategy/action outputs by validated session semantics."""

    _RACE_ACTIONS = {
        "NONE",
        "SAFETY_CAR",
        "LOW_FUEL",
        "BOX_WINDOW",
        "TYRE_MANAGE",
        "ERS_LOW",
        "ATTACK_WINDOW",
        "DEFEND_WINDOW",
        "DYNAMICS_UNSTABLE",
        "FRONT_LOAD",
    }
    _RACE_NO_TIMING = {
        "NONE",
        "SAFETY_CAR",
        "LOW_FUEL",
        "BOX_WINDOW",
        "TYRE_MANAGE",
        "ERS_LOW",
        "DYNAMICS_UNSTABLE",
        "FRONT_LOAD",
    }
    _QUALI_ACTIONS = {"NONE", "DYNAMICS_UNSTABLE", "FRONT_LOAD"}

    def resolve(self, state: SessionState) -> SessionRoute:
        raw = state.raw
        timing_mode = str(raw.get("timing_mode") or "unknown")
        timing_support_level = str(raw.get("timing_support_level") or "unknown")
        session_type = str(raw.get("session_type") or "unknown")

        if timing_mode == "race_like" and timing_support_level == "official_preferred":
            return SessionRoute(
                session_mode=f"{session_type}:{timing_mode}",
                allowed_action_codes=set(self._RACE_ACTIONS),
                allow_timing_actions=True,
                allow_race_resource_actions=True,
                route_reason="race_like_official",
            )
        if timing_mode == "session_type_estimated":
            return SessionRoute(
                session_mode=f"{session_type}:{timing_mode}",
                allowed_action_codes=set(self._RACE_NO_TIMING),
                allow_timing_actions=False,
                allow_race_resource_actions=True,
                route_reason="estimated_session_no_timing_actions",
            )
        return SessionRoute(
            session_mode=f"{session_type}:{timing_mode}",
            allowed_action_codes=set(self._QUALI_ACTIONS),
            allow_timing_actions=False,
            allow_race_resource_actions=False,
            route_reason="non_race_session",
        )

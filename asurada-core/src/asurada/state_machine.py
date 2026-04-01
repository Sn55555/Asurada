from __future__ import annotations

from dataclasses import dataclass

from .models import ContextProfile, SessionState, StateAssessment


@dataclass
class TacticalStateResolution:
    """Resolved tactical state for the current frame."""

    previous_tactical_state: str
    tactical_state: str
    state_transition: str
    state_priority_hint: str | None
    state_lock: bool
    recommended_action: str
    position_lost_recently: bool
    position_gain_recently: bool
    history_hold_applied: bool
    history_anchor_action: str | None


class TacticalStateMachine:
    """Rule-based tactical state machine for stage-two mainline control."""

    def resolve(
        self,
        *,
        state: SessionState,
        previous_state: SessionState | None,
        previous_resolution: TacticalStateResolution | None,
        last_output_action: str | None,
        assessment: StateAssessment,
        context: ContextProfile,
    ) -> TacticalStateResolution:
        previous_tactical_state = (
            previous_resolution.tactical_state
            if previous_resolution is not None
            else self._infer_base_state(previous_state, previous_state, None, None) if previous_state else "neutral"
        )
        tactical_state = self._infer_base_state(state, previous_state, assessment, context)
        history_hold_applied = False

        if previous_tactical_state in {"defence_prepare", "defence_active"} and tactical_state == "neutral":
            gap_behind = state.player.gap_behind_s
            if gap_behind is not None and gap_behind <= 0.95:
                tactical_state = "defence_prepare"
                history_hold_applied = True
        if previous_tactical_state in {"counterattack_prepare", "counterattack_active"} and tactical_state == "neutral":
            gap_ahead = state.player.gap_ahead_s
            if gap_ahead is not None and gap_ahead <= 1.1:
                tactical_state = "counterattack_prepare"
                history_hold_applied = True

        position_lost_recently = False
        position_gain_recently = False
        if previous_state is not None:
            position_lost_recently = state.player.position > previous_state.player.position
            position_gain_recently = state.player.position < previous_state.player.position
            if position_lost_recently and tactical_state in {"attack_prepare", "neutral"}:
                tactical_state = "counterattack_prepare"
            if position_gain_recently and tactical_state == "defence_prepare":
                tactical_state = "neutral"

        if tactical_state == "counterattack_prepare":
            gap_ahead = state.player.gap_ahead_s
            if state.player.drs_available and gap_ahead is not None and gap_ahead <= 0.6:
                tactical_state = "counterattack_active"

        if tactical_state == "neutral" and previous_tactical_state in {
            "defence_prepare",
            "defence_active",
            "attack_prepare",
            "counterattack_prepare",
            "counterattack_active",
        }:
            tactical_state = self._apply_output_history_hold(
                state=state,
                previous_tactical_state=previous_tactical_state,
                last_output_action=last_output_action,
            )
            history_hold_applied = tactical_state != "neutral"

        state_priority_hint = self._priority_hint(tactical_state)
        state_lock = tactical_state in {"defence_active", "counterattack_active"}
        recommended_action = last_output_action if history_hold_applied and last_output_action else (state_priority_hint or "NONE")
        state_transition = (
            "stable" if tactical_state == previous_tactical_state else f"{previous_tactical_state}->{tactical_state}"
        )

        return TacticalStateResolution(
            previous_tactical_state=previous_tactical_state,
            tactical_state=tactical_state,
            state_transition=state_transition,
            state_priority_hint=state_priority_hint,
            state_lock=state_lock,
            recommended_action=recommended_action,
            position_lost_recently=position_lost_recently,
            position_gain_recently=position_gain_recently,
            history_hold_applied=history_hold_applied,
            history_anchor_action=last_output_action if history_hold_applied else None,
        )

    def _infer_base_state(
        self,
        state: SessionState | None,
        previous_state: SessionState | None,
        assessment: StateAssessment | None,
        context: ContextProfile | None,
    ) -> str:
        if state is None:
            return "neutral"

        if assessment is None:
            gap_behind = state.player.gap_behind_s
            gap_ahead = state.player.gap_ahead_s
            if gap_behind is not None and gap_behind <= 0.7:
                return "defence_prepare"
            if gap_ahead is not None and gap_ahead <= 0.8 and state.player.drs_available:
                return "counterattack_prepare"
            return "neutral"

        if assessment.defend_state == "urgent":
            gap_behind = state.player.gap_behind_s
            if gap_behind is not None and gap_behind <= 0.45:
                return "defence_active"
            return "defence_prepare"

        position_lost_recently = previous_state is not None and state.player.position > previous_state.player.position
        if position_lost_recently:
            gap_ahead = state.player.gap_ahead_s
            if state.player.drs_available and gap_ahead is not None and gap_ahead <= 0.6:
                return "counterattack_active"
            return "counterattack_prepare"

        if assessment.attack_state == "available":
            if context is not None and context.track_zone in {"deployment_straight", "exit_traction"}:
                return "attack_prepare"

        return "neutral"

    def _priority_hint(self, tactical_state: str) -> str | None:
        if tactical_state in {"defence_prepare", "defence_active"}:
            return "DEFEND_WINDOW"
        if tactical_state in {"attack_prepare", "counterattack_prepare", "counterattack_active"}:
            return "ATTACK_WINDOW"
        return None

    def _apply_output_history_hold(
        self,
        *,
        state: SessionState,
        previous_tactical_state: str,
        last_output_action: str | None,
    ) -> str:
        if last_output_action == "DEFEND_WINDOW":
            gap_behind = state.player.gap_behind_s
            if gap_behind is not None and gap_behind <= 1.05:
                return "defence_prepare" if previous_tactical_state == "defence_prepare" else "defence_active"
        if last_output_action == "ATTACK_WINDOW":
            gap_ahead = state.player.gap_ahead_s
            if gap_ahead is not None and gap_ahead <= 1.3:
                if previous_tactical_state == "attack_prepare":
                    return "attack_prepare"
                return "counterattack_prepare" if previous_tactical_state == "counterattack_prepare" else "counterattack_active"
        return "neutral"

from __future__ import annotations

from dataclasses import dataclass

from .arbiter import FallbackContext, ModelCandidate, OutputControl, RuleCandidate, TacticalContext
from .confidence import ConfidenceResolution
from .models import ContextProfile, SessionState
from .session_router import SessionRoute


@dataclass
class FallbackPolicyResolution:
    """Resolved fallback/output-control policy before arbiter execution."""

    fallback_context: FallbackContext
    output_control: OutputControl
    policy_name: str
    policy_reasons: list[str]


class StrategyFallbackPolicy:
    """Rule-based fallback policy for stage-two mainline execution."""

    _TIMING_DEPENDENT_CODES = {"ATTACK_WINDOW", "DEFEND_WINDOW"}

    def resolve(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        session_route: SessionRoute,
        confidence_resolution: ConfidenceResolution,
        tactical_context: TacticalContext,
        rule_candidates: list[RuleCandidate],
        model_candidates: list[ModelCandidate],
    ) -> FallbackPolicyResolution:
        reasons: list[str] = []
        fallback_context = FallbackContext(
            fallback_mode=confidence_resolution.fallback_context.fallback_mode,
            voice_allowed=confidence_resolution.fallback_context.voice_allowed,
            hud_only=confidence_resolution.fallback_context.hud_only,
        )
        output_control = OutputControl(
            cooldown_hint=0,
            last_emitted_action=None,
            suppression_window=0,
        )

        model_codes = {candidate.code for candidate in model_candidates}
        rule_codes = {candidate.code for candidate in rule_candidates}
        timing_sensitive = bool((model_codes | rule_codes) & self._TIMING_DEPENDENT_CODES)

        if confidence_resolution.fallback_recommended and fallback_context.fallback_mode != "none":
            reasons.append(f"uncertainty:{confidence_resolution.fallback_reason}")

        if timing_sensitive and not session_route.allow_timing_actions:
            fallback_context = FallbackContext(
                fallback_mode="rule_only",
                voice_allowed=False,
                hud_only=True,
            )
            reasons.append("session_route_disables_timing")

        if (
            confidence_resolution.confidence_context.confidence_level == "low"
            and tactical_context.tactical_state != "neutral"
        ):
            fallback_context = FallbackContext(
                fallback_mode="rule_only",
                voice_allowed=False,
                hud_only=True,
            )
            reasons.append("low_confidence_tactical_lock")

        if (
            fallback_context.fallback_mode == "none"
            and context.recent_unstable_ratio >= 0.65
            and tactical_context.tactical_state in {"defence_active", "counterattack_active"}
        ):
            fallback_context = FallbackContext(
                fallback_mode="none",
                voice_allowed=False,
                hud_only=True,
            )
            reasons.append("hud_only_due_to_instability")

        if tactical_context.state_lock:
            output_control = OutputControl(
                cooldown_hint=72,
                last_emitted_action=None,
                suppression_window=0,
            )
            reasons.append("state_lock_priority_boost")
        elif tactical_context.tactical_state in {"defence_prepare", "counterattack_prepare"}:
            output_control = OutputControl(
                cooldown_hint=65,
                last_emitted_action=None,
                suppression_window=0,
            )
            reasons.append("tactical_prepare_priority_floor")

        policy_name = "fallback_policy_v1"
        if not reasons:
            reasons.append("pass_through")
        return FallbackPolicyResolution(
            fallback_context=fallback_context,
            output_control=output_control,
            policy_name=policy_name,
            policy_reasons=reasons,
        )

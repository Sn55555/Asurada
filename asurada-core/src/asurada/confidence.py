from __future__ import annotations

from dataclasses import dataclass

from .arbiter import ConfidenceContext, FallbackContext, ModelCandidate
from .models import ContextProfile, SessionState


@dataclass
class ConfidenceResolution:
    """Resolved confidence and fallback routing for the current frame."""

    confidence_context: ConfidenceContext
    fallback_context: FallbackContext
    fallback_recommended: bool
    fallback_reason: str
    session_mode: str


class StrategyUncertaintyLayer:
    """Rule-based uncertainty layer for stage-two mainline gating."""

    _TIMING_DEPENDENT_CODES = {"DEFEND_WINDOW", "ATTACK_WINDOW"}

    def evaluate(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        model_candidates: list[ModelCandidate],
        tactical_state: str,
    ) -> ConfidenceResolution:
        raw = state.raw
        timing_support_level = str(raw.get("timing_support_level") or "unknown")
        session_mode = self._session_mode(raw)
        candidate_codes = {candidate.code for candidate in model_candidates}
        timing_dependent = bool(candidate_codes & self._TIMING_DEPENDENT_CODES) or tactical_state in {
            "defence_prepare",
            "defence_active",
            "counterattack_prepare",
            "counterattack_active",
        }

        score = 1.0
        reasons: list[str] = []

        if not model_candidates:
            score -= 0.18
            reasons.append("no_model_candidates")

        if timing_dependent:
            if timing_support_level == "disabled":
                score -= 0.55
                reasons.append("timing_disabled")
            elif timing_support_level == "estimated_only":
                score -= 0.40
                reasons.append("timing_estimated_only")

            ahead_conf = str(raw.get("official_gap_confidence_ahead") or "none")
            behind_conf = str(raw.get("official_gap_confidence_behind") or "none")
            if "ATTACK_WINDOW" in candidate_codes and ahead_conf != "high":
                score -= 0.18
                reasons.append(f"attack_gap_confidence_{ahead_conf}")
            if "DEFEND_WINDOW" in candidate_codes and behind_conf != "high":
                score -= 0.18
                reasons.append(f"defend_gap_confidence_{behind_conf}")

        if context.recent_unstable_ratio >= 0.75:
            score -= 0.10
            reasons.append("high_recent_instability")

        score = max(min(score, 1.0), 0.0)
        if score >= 0.85:
            level = "high"
        elif score >= 0.60:
            level = "medium"
        else:
            level = "low"

        mainline_allowed = True
        fallback_mode = "none"
        fallback_reason = "none"

        if timing_dependent and timing_support_level in {"disabled", "estimated_only"}:
            mainline_allowed = False
            fallback_mode = "rule_only"
            fallback_reason = timing_support_level
        elif level == "low" and timing_dependent:
            fallback_mode = "rule_only"
            mainline_allowed = False
            fallback_reason = "low_confidence_tactical"

        voice_allowed = level != "low"
        hud_only = mainline_allowed and not voice_allowed

        return ConfidenceResolution(
            confidence_context=ConfidenceContext(
                confidence_score=round(score, 3),
                confidence_level=level,
                mainline_allowed=mainline_allowed,
            ),
            fallback_context=FallbackContext(
                fallback_mode=fallback_mode,
                voice_allowed=voice_allowed,
                hud_only=hud_only,
            ),
            fallback_recommended=fallback_mode != "none" or hud_only,
            fallback_reason=fallback_reason if fallback_mode != "none" else (reasons[0] if reasons else "none"),
            session_mode=session_mode,
        )

    def _session_mode(self, raw: dict[str, object]) -> str:
        timing_mode = str(raw.get("timing_mode") or "unknown")
        session_type = str(raw.get("session_type") or "unknown")
        timing_support_level = str(raw.get("timing_support_level") or "unknown")
        return f"{session_type}:{timing_mode}:{timing_support_level}"

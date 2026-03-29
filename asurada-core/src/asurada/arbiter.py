from __future__ import annotations

from dataclasses import dataclass, field

from .models import StrategyCandidate


@dataclass
class RuleCandidate:
    """Normalized rule-side candidate consumed by StrategyArbiterV2."""

    code: str
    priority: int
    title: str
    detail: str
    source: str = "rule_engine"
    expires_in_frames: int | None = None

    @classmethod
    def from_strategy_candidate(
        cls,
        candidate: StrategyCandidate,
        *,
        source: str = "rule_engine",
        expires_in_frames: int | None = None,
    ) -> "RuleCandidate":
        return cls(
            code=candidate.code,
            priority=candidate.priority,
            title=candidate.title,
            detail=candidate.detail,
            source=source,
            expires_in_frames=expires_in_frames,
        )


@dataclass
class ModelCandidate:
    """Normalized model-side candidate consumed by StrategyArbiterV2."""

    code: str
    score: float
    rank: int
    source_model: str
    title: str
    detail: str


@dataclass
class TacticalContext:
    """Current tactical state and arbitration hints."""

    tactical_state: str
    state_priority_hint: str | None = None
    state_lock: bool = False
    state_transition: str | None = None


@dataclass
class ConfidenceContext:
    """Confidence gating produced by the uncertainty layer."""

    confidence_score: float
    confidence_level: str
    mainline_allowed: bool


@dataclass
class FallbackContext:
    """Fallback routing flags resolved before final output."""

    fallback_mode: str = "none"
    voice_allowed: bool = True
    hud_only: bool = False


@dataclass
class OutputControl:
    """Output cooldown and suppression state."""

    cooldown_hint: int = 0
    last_emitted_action: str | None = None
    suppression_window: int = 0


@dataclass
class HudAction:
    """Final HUD action after arbitration."""

    code: str
    reason: str
    source: str


@dataclass
class VoiceAction:
    """Final voice action after arbitration."""

    code: str
    speak_text: str
    priority: int
    interrupt: bool


@dataclass
class StrategyStack:
    """Primary and secondary decisions retained for debugging and UI."""

    primary: str
    secondary: str | None
    tactical_state: str
    confidence_level: str


@dataclass
class SuppressedAction:
    """Candidate removed by fallback, cooldown, or tactical alignment rules."""

    code: str
    suppression_reason: str


@dataclass
class ResolvedAction:
    """Ordered post-arbitration action used by downstream output layers."""

    code: str
    title: str
    detail: str
    priority: int
    source: str


@dataclass
class ArbiterInput:
    """Complete StrategyArbiterV2 input contract."""

    rule_candidates: list[RuleCandidate] = field(default_factory=list)
    model_candidates: list[ModelCandidate] = field(default_factory=list)
    tactical_context: TacticalContext = field(default_factory=lambda: TacticalContext(tactical_state="neutral"))
    confidence_context: ConfidenceContext = field(
        default_factory=lambda: ConfidenceContext(
            confidence_score=1.0,
            confidence_level="high",
            mainline_allowed=True,
        )
    )
    fallback_context: FallbackContext = field(default_factory=FallbackContext)
    output_control: OutputControl = field(default_factory=OutputControl)
    sidecar_scores: dict[str, object] = field(default_factory=dict)


@dataclass
class ArbiterOutput:
    """Complete StrategyArbiterV2 output contract."""

    final_hud_action: HudAction
    final_voice_action: VoiceAction | None
    final_strategy_stack: StrategyStack
    ordered_actions: list[ResolvedAction] = field(default_factory=list)
    suppressed_actions: list[SuppressedAction] = field(default_factory=list)


@dataclass
class _RankedAction:
    code: str
    title: str
    detail: str
    score: float
    output_priority: int
    source: str


class StrategyArbiterV2:
    """Arbitrate top-k model candidates with rule candidates and tactical context."""

    _TACTICAL_CODE_HINTS = {
        "rear_threat_building": "DEFEND_WINDOW",
        "defence_prepare": "DEFEND_WINDOW",
        "defence_active": "DEFEND_WINDOW",
        "counterattack_prepare": "ATTACK_WINDOW",
        "counterattack_active": "ATTACK_WINDOW",
    }
    _MODEL_PRIORITY_FLOORS = {
        "NONE": 0,
        "LOW_FUEL": 78,
        "DEFEND_WINDOW": 76,
        "DYNAMICS_UNSTABLE": 74,
        "ATTACK_WINDOW": 62,
        "BOX_WINDOW": 82,
        "TYRE_MANAGE": 68,
        "ERS_LOW": 70,
        "FRONT_LOAD": 66,
        "SAFETY_CAR": 90,
    }

    def arbitrate(self, payload: ArbiterInput) -> ArbiterOutput:
        """Resolve final HUD/voice actions from normalized rule and model inputs."""

        suppressed: list[SuppressedAction] = []
        rule_candidates = list(payload.rule_candidates)
        model_candidates = list(payload.model_candidates)

        if payload.fallback_context.fallback_mode == "rule_only" or not payload.confidence_context.mainline_allowed:
            for candidate in model_candidates:
                suppressed.append(
                    SuppressedAction(
                        code=candidate.code,
                        suppression_reason="fallback_rule_only",
                    )
                )
            model_candidates = []

        ranked = self._rank_candidates(
            rule_candidates=rule_candidates,
            model_candidates=model_candidates,
            tactical_context=payload.tactical_context,
            sidecar_scores=payload.sidecar_scores,
        )

        if payload.output_control.last_emitted_action and payload.output_control.suppression_window > 0:
            filtered: list[_RankedAction] = []
            for item in ranked:
                if item.code == payload.output_control.last_emitted_action:
                    suppressed.append(
                        SuppressedAction(
                            code=item.code,
                            suppression_reason="cooldown_window",
                        )
                    )
                    continue
                filtered.append(item)
            if filtered:
                ranked = filtered

        if not ranked:
            neutral = _RankedAction(
                code="NONE",
                title="无策略变化",
                detail="当前无高优先级动作需要输出。",
                score=0.0,
                output_priority=0,
                source="arbiter_default",
            )
            ranked = [neutral]

        primary = ranked[0]
        secondary = ranked[1] if len(ranked) > 1 else None

        final_hud_action = HudAction(
            code=primary.code,
            reason=primary.detail,
            source=primary.source,
        )
        final_voice_action = None
        if payload.fallback_context.voice_allowed and not payload.fallback_context.hud_only:
            final_voice_action = VoiceAction(
                code=primary.code,
                speak_text=primary.title,
                priority=max(int(primary.score), payload.output_control.cooldown_hint),
                interrupt=self._should_interrupt(
                    primary_code=primary.code,
                    tactical_context=payload.tactical_context,
                ),
            )

        return ArbiterOutput(
            final_hud_action=final_hud_action,
            final_voice_action=final_voice_action,
            final_strategy_stack=StrategyStack(
                primary=primary.code,
                secondary=secondary.code if secondary is not None else None,
                tactical_state=payload.tactical_context.tactical_state,
                confidence_level=payload.confidence_context.confidence_level,
            ),
            ordered_actions=[
                ResolvedAction(
                    code=item.code,
                    title=item.title,
                    detail=item.detail,
                    priority=item.output_priority,
                    source=item.source,
                )
                for item in ranked
            ],
            suppressed_actions=suppressed,
        )

    def _rank_candidates(
        self,
        *,
        rule_candidates: list[RuleCandidate],
        model_candidates: list[ModelCandidate],
        tactical_context: TacticalContext,
        sidecar_scores: dict[str, object],
    ) -> list[_RankedAction]:
        ranked: list[_RankedAction] = []

        for candidate in rule_candidates:
            ranked.append(
                _RankedAction(
                    code=candidate.code,
                    title=candidate.title,
                    detail=candidate.detail,
                    score=float(candidate.priority),
                    output_priority=int(candidate.priority),
                    source=candidate.source,
                )
            )

        for candidate in model_candidates:
            score = float(candidate.score) * 100.0
            ranked.append(
                _RankedAction(
                    code=candidate.code,
                    title=candidate.title,
                    detail=candidate.detail,
                    score=score,
                    output_priority=self._model_output_priority(code=candidate.code, score=score),
                    source=candidate.source_model,
                )
            )

        preferred_code = tactical_context.state_priority_hint or self._TACTICAL_CODE_HINTS.get(tactical_context.tactical_state)
        if preferred_code:
            for item in ranked:
                if item.code == preferred_code:
                    bonus = 15.0 if tactical_context.state_lock else 8.0
                    item.score += bonus
                    item.output_priority += int(round(bonus))

        self._apply_sidecar_biases(ranked=ranked, sidecar_scores=sidecar_scores, tactical_context=tactical_context)
        ranked = sorted(ranked, key=lambda item: (item.score, item.code), reverse=True)
        return self._dedupe_ranked_actions(ranked)

    def _should_interrupt(self, *, primary_code: str, tactical_context: TacticalContext) -> bool:
        if tactical_context.state_lock:
            return True
        if tactical_context.tactical_state in {"defence_active", "counterattack_active"}:
            return True
        return primary_code in {"SAFETY_CAR", "DEFEND_WINDOW", "ATTACK_WINDOW"}

    def _model_output_priority(self, *, code: str, score: float) -> int:
        floor = self._MODEL_PRIORITY_FLOORS.get(code, 60)
        if code == "NONE":
            return min(25, max(0, int(round(score * 0.5))))
        scaled_bonus = int(round(max(0.0, score - 50.0) / 5.0))
        return floor + scaled_bonus

    def _dedupe_ranked_actions(self, ranked: list[_RankedAction]) -> list[_RankedAction]:
        deduped: list[_RankedAction] = []
        seen_codes: set[str] = set()
        for item in ranked:
            if item.code in seen_codes:
                continue
            seen_codes.add(item.code)
            deduped.append(item)
        return deduped

    def _apply_sidecar_biases(
        self,
        *,
        ranked: list[_RankedAction],
        sidecar_scores: dict[str, object],
        tactical_context: TacticalContext,
    ) -> None:
        resource_models = sidecar_scores.get("resource_models") or {}
        rival_pressure_models = sidecar_scores.get("rival_pressure_models") or {}
        defence_cost_model = sidecar_scores.get("defence_cost_model") or {}
        driving_quality_models = sidecar_scores.get("driving_quality_models") or {}
        tyre_trend_models = sidecar_scores.get("tyre_degradation_trend_models") or {}

        fuel_risk = self._extract_score(resource_models, "fuel_risk")
        dynamics_risk = self._extract_score(resource_models, "dynamics_risk")
        rear_pressure = self._extract_score(rival_pressure_models, "rear_pressure")
        defence_cost = self._extract_score({"defence_cost": defence_cost_model}, "defence_cost")
        entry_quality = self._extract_score(driving_quality_models, "entry_quality")
        apex_quality = self._extract_score(driving_quality_models, "apex_quality")
        exit_traction = self._extract_score(driving_quality_models, "exit_traction")
        tyre_wear_trend = self._extract_score(tyre_trend_models, "future_tyre_wear_delta")
        grip_drop = self._extract_score(tyre_trend_models, "future_grip_drop_score")

        poor_corner_quality = min(entry_quality, apex_quality) if entry_quality and apex_quality else 0.0
        strong_corner_quality = min(entry_quality, apex_quality) if entry_quality and apex_quality else 0.0

        for item in ranked:
            bonus = 0.0
            if item.code == "LOW_FUEL":
                if fuel_risk >= 85.0:
                    bonus += 12.0
                elif fuel_risk <= 35.0:
                    bonus -= 10.0
            elif item.code == "DYNAMICS_UNSTABLE":
                if dynamics_risk >= 65.0:
                    bonus += 10.0
                elif dynamics_risk <= 25.0:
                    bonus -= 8.0
                if poor_corner_quality and poor_corner_quality <= 35.0:
                    bonus += 8.0
                elif strong_corner_quality >= 72.0 and exit_traction >= 72.0:
                    bonus -= 5.0
            elif item.code == "DEFEND_WINDOW":
                if rear_pressure >= 55.0:
                    bonus += 8.0
                if defence_cost >= 65.0 and tactical_context.tactical_state not in {"defence_active", "defence_prepare"}:
                    bonus -= 6.0
                if poor_corner_quality and poor_corner_quality <= 32.0 and not tactical_context.state_lock:
                    bonus -= 4.0
                elif exit_traction >= 75.0 and rear_pressure >= 45.0:
                    bonus += 3.0
            elif item.code == "ATTACK_WINDOW":
                if rear_pressure <= 20.0:
                    bonus += 4.0
                if grip_drop >= 6.0:
                    bonus -= 5.0
                if tyre_wear_trend >= 0.45:
                    bonus -= 4.0
                if exit_traction >= 72.0 and strong_corner_quality >= 55.0 and grip_drop <= 3.5:
                    bonus += 6.0
                if poor_corner_quality and poor_corner_quality <= 35.0:
                    bonus -= 6.0
                if exit_traction <= 42.0:
                    bonus -= 5.0
            elif item.code == "FRONT_LOAD":
                if poor_corner_quality and poor_corner_quality <= 30.0:
                    bonus += 7.0
                elif strong_corner_quality >= 70.0 and exit_traction >= 68.0:
                    bonus -= 4.0

            if bonus:
                item.score += bonus
                item.output_priority += int(round(bonus))

    def _extract_score(self, payload: dict[str, object], key: str) -> float:
        item = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            return 0.0
        try:
            return float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CONTROL_QUERY_KINDS = frozenset({"repeat_last", "stop", "cancel"})

STRUCTURED_QUERY_KINDS = frozenset(
    {
        "fuel_status",
        "damage_status",
        "damage_pit_advice",
        "front_wing_damage_status",
        "floor_damage_status",
        "engine_damage_status",
        "front_gap",
        "front_rival_drs_status",
        "rear_gap",
        "rear_rival_drs_status",
        "tyre_status",
        "drs_status",
        "ers_status",
        "weather_status",
        "race_control_status",
        "penalty_status",
        "pit_status",
        "pit_penalty_plan",
        "penalty_handling_strategy",
        "current_strategy",
    }
)

EXPLAINER_QUERY_KINDS = frozenset(
    {
        "overall_situation",
        "attack_or_defend_summary",
        "attack_defend_tradeoff",
        "main_risk_summary",
        "next_lap_focus",
        "tyre_wear_outlook",
        "risk_severity_followup",
        "risk_escalation_timing",
        "rear_pressure_relief_outlook",
        "pit_delay_consequence",
        "pit_one_lap_delay_consequence",
        "tyre_management_advice",
        "fuel_management_advice",
        "defend_outcome_projection",
        "attack_outcome_projection",
        "why_defend",
        "why_not_attack",
        "why_current_strategy",
        "why_not_pit",
        "open_fallback",
    }
)


@dataclass(frozen=True)
class CapabilityCheck:
    allowed: bool
    reason: str
    lane: str
    llm_sidecar_eligible: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityRegistry:
    """Central allow/deny boundary for transcript routing and future LLM sidecar use."""

    DEFAULT_DISALLOWED_PATTERNS: tuple[str, ...] = (
        "帮我决定",
        "替我决定",
        "直接让我进站",
        "现在让我进站",
        "改成进攻",
        "改成防守",
        "这圈怎么开",
        "这圈该怎么开",
        "替我开",
        "帮我开",
    )

    def __init__(
        self,
        *,
        disallowed_patterns: tuple[str, ...] | None = None,
    ) -> None:
        self.disallowed_patterns = tuple(item for item in (disallowed_patterns or self.DEFAULT_DISALLOWED_PATTERNS) if item)

    def evaluate(self, *, query_kind: str | None, normalized_text: str) -> CapabilityCheck:
        text = str(normalized_text or "").strip().lower()
        if self.is_disallowed_domain(text):
            return CapabilityCheck(
                allowed=False,
                reason="disallowed_domain",
                lane="reject",
                llm_sidecar_eligible=False,
                metadata={"matched_pattern": self._matched_disallowed_pattern(text)},
            )

        if query_kind is None:
            return CapabilityCheck(
                allowed=False,
                reason="missing_query_kind",
                lane="reject",
                llm_sidecar_eligible=False,
            )

        if query_kind in CONTROL_QUERY_KINDS:
            return CapabilityCheck(
                allowed=True,
                reason="control_query",
                lane="control",
                llm_sidecar_eligible=False,
            )

        if query_kind in STRUCTURED_QUERY_KINDS:
            return CapabilityCheck(
                allowed=True,
                reason="structured_query",
                lane="structured",
                llm_sidecar_eligible=False,
            )

        if query_kind in EXPLAINER_QUERY_KINDS:
            return CapabilityCheck(
                allowed=True,
                reason="explainer_query",
                lane="explainer",
                llm_sidecar_eligible=True,
            )

        return CapabilityCheck(
            allowed=False,
            reason="unsupported_query_kind",
            lane="reject",
            llm_sidecar_eligible=False,
            metadata={"query_kind": query_kind},
        )

    def is_disallowed_domain(self, normalized_text: str) -> bool:
        return self._matched_disallowed_pattern(normalized_text) is not None

    def _matched_disallowed_pattern(self, normalized_text: str) -> str | None:
        source = str(normalized_text or "")
        for pattern in self.disallowed_patterns:
            if pattern in source:
                return pattern
        return None

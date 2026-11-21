from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


from .capability_definitions import CAPABILITIES, CONTROL_QUERY_KINDS, STRUCTURED_QUERY_KINDS, EXPLAINER_QUERY_KINDS


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

    def tool_catalog(self) -> list[dict[str, Any]]:
        """Read-only tools only; speech controls are not exposed to model tool calls."""
        return [spec.tool_schema() for spec in CAPABILITIES.values() if spec.handler_name is not None]

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

        spec = CAPABILITIES.get(query_kind)
        if spec is not None and spec.lane == 'analysis_tool':
            return CapabilityCheck(False,'requires_tool_execution','reject',False)
        if spec is not None:
            return CapabilityCheck(allowed=True, reason=f"{spec.lane}_query", lane=spec.lane,
                                   llm_sidecar_eligible=spec.lane == "explainer",
                                   metadata={"capability_version":spec.version, "permission":spec.permission})

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

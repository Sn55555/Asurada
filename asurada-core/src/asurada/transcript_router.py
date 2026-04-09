from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .asr_fast import FastIntentResult
from .capability_registry import CapabilityCheck, CapabilityRegistry
from .models import SessionState
from .runtime_context import RuntimeContextDetector
from .semantic_normalizer import SemanticIntentResult


@dataclass(frozen=True)
class TranscriptRouteDecision:
    status: str
    lane: str
    query_kind: str | None
    llm_sidecar_eligible: bool
    should_call_core: bool
    should_call_llm_sidecar: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TranscriptRouter:
    """Route one normalized transcript into control, structured, explainer, or reject."""

    def __init__(self, *, capability_registry: CapabilityRegistry | None = None) -> None:
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.runtime_context_detector = RuntimeContextDetector()

    def route(
        self,
        *,
        state: SessionState,
        fast_intent: FastIntentResult,
        semantic_intent: SemanticIntentResult,
    ) -> TranscriptRouteDecision:
        runtime_context = self.runtime_context_detector.detect(state=state)
        normalized_text = str(
            semantic_intent.normalized_query_text
            or fast_intent.transcript_text
            or fast_intent.normalized_text
            or ""
        ).strip()

        if (
            runtime_context.racing_active is False
            and semantic_intent.query_kind in {"repeat_last", "stop", "cancel"}
        ):
            capability = self.capability_registry.evaluate(
                query_kind=semantic_intent.query_kind,
                normalized_text=normalized_text,
            )
            return TranscriptRouteDecision(
                status="routed",
                lane="control",
                query_kind=semantic_intent.query_kind,
                llm_sidecar_eligible=False,
                should_call_core=True,
                should_call_llm_sidecar=False,
                reason=capability.reason,
                metadata={
                    "capability_check": capability.to_dict(),
                    "semantic_reason": semantic_intent.reason,
                    "response_style": semantic_intent.response_style,
                    "normalized_text": normalized_text,
                    "runtime_context": runtime_context.to_dict(),
                },
            )

        if runtime_context.racing_active is False and normalized_text:
            query_kind = semantic_intent.query_kind or "open_fallback"
            return TranscriptRouteDecision(
                status="routed",
                lane="companion",
                query_kind=query_kind,
                llm_sidecar_eligible=True,
                should_call_core=False,
                should_call_llm_sidecar=True,
                reason="companion_mode_inactive_race",
                metadata={
                    "semantic_status": semantic_intent.status,
                    "semantic_reason": semantic_intent.reason,
                    "normalized_text": normalized_text,
                    "runtime_context": runtime_context.to_dict(),
                    "original_query_kind": semantic_intent.query_kind,
                },
            )

        if semantic_intent.status != "matched" or semantic_intent.query_kind is None:
            return TranscriptRouteDecision(
                status="reject",
                lane="reject",
                query_kind=None,
                llm_sidecar_eligible=False,
                should_call_core=False,
                should_call_llm_sidecar=False,
                reason="semantic_unmatched",
                metadata={
                    "semantic_status": semantic_intent.status,
                    "semantic_reason": semantic_intent.reason,
                    "normalized_text": normalized_text,
                    "runtime_context": runtime_context.to_dict(),
                },
            )

        capability = self.capability_registry.evaluate(
            query_kind=semantic_intent.query_kind,
            normalized_text=normalized_text,
        )
        if not capability.allowed:
            return TranscriptRouteDecision(
                status="reject",
                lane="reject",
                query_kind=semantic_intent.query_kind,
                llm_sidecar_eligible=False,
                should_call_core=False,
                should_call_llm_sidecar=False,
                reason=capability.reason,
                metadata={
                    "capability_check": capability.to_dict(),
                    "semantic_reason": semantic_intent.reason,
                    "normalized_text": normalized_text,
                    "runtime_context": runtime_context.to_dict(),
                },
            )

        return TranscriptRouteDecision(
            status="routed",
            lane=capability.lane,
            query_kind=semantic_intent.query_kind,
            llm_sidecar_eligible=capability.llm_sidecar_eligible,
            should_call_core=True,
            should_call_llm_sidecar=False,
            reason=capability.reason,
            metadata={
                "capability_check": capability.to_dict(),
                "semantic_reason": semantic_intent.reason,
                "response_style": semantic_intent.response_style,
                "normalized_text": normalized_text,
                "runtime_context": runtime_context.to_dict(),
            },
        )

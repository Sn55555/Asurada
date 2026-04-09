from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_LLM_RESPONSE_STATUS = frozenset({"answerable", "needs_clarification", "unsupported", "unsafe"})


@dataclass(frozen=True)
class LlmResponse:
    status: str
    answer_text: str
    confidence: float
    reason_fields: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_llm_response(payload: dict[str, Any]) -> tuple[bool, str]:
    status = str(payload.get("status") or "")
    if status not in ALLOWED_LLM_RESPONSE_STATUS:
        return False, "invalid_status"

    answer_text = payload.get("answer_text")
    if not isinstance(answer_text, str):
        return False, "invalid_answer_text"

    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        return False, "invalid_confidence"
    if confidence < 0.0 or confidence > 1.0:
        return False, "confidence_out_of_range"

    reason_fields = payload.get("reason_fields") or []
    if not isinstance(reason_fields, list) or not all(isinstance(item, str) for item in reason_fields):
        return False, "invalid_reason_fields"

    requires_confirmation = payload.get("requires_confirmation", False)
    if not isinstance(requires_confirmation, bool):
        return False, "invalid_requires_confirmation"

    metadata = payload.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        return False, "invalid_metadata"

    return True, "valid"


def coerce_llm_response(payload: dict[str, Any]) -> LlmResponse:
    valid, reason = validate_llm_response(payload)
    if not valid:
        raise ValueError(f"invalid_llm_response:{reason}")
    return LlmResponse(
        status=str(payload["status"]),
        answer_text=str(payload["answer_text"]),
        confidence=float(payload["confidence"]),
        reason_fields=list(payload.get("reason_fields") or []),
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        metadata=dict(payload.get("metadata") or {}),
    )

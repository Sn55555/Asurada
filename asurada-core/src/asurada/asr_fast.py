from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .voice_turn import VoiceTurn


@dataclass(frozen=True)
class FastIntentResult:
    """Structured output of the fast intent lane."""

    lane: str
    status: str
    transcript_text: str
    normalized_text: str
    query_kind: str | None
    confidence: float
    matched_phrase: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FastIntentASR:
    """Abstract fast-lane recognizer for structured racing queries."""

    def recognize_turn(self, turn: VoiceTurn) -> FastIntentResult:
        raise NotImplementedError


class KeywordFastIntentASR(FastIntentASR):
    """Text-first recognizer using constrained phrases and aliases."""

    DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
        "fuel_status": ("燃油", "油量", "还剩多少油", "燃油怎么样"),
        "rear_gap": ("后车", "后面", "后方差距", "后车差距", "后车多近"),
        "tyre_status": ("轮胎", "胎况", "轮胎状态", "胎怎么样", "胎温"),
        "current_strategy": ("当前策略", "当前战术", "现在策略", "现在怎么跑", "策略怎么样"),
        "repeat_last": ("重复", "再说一遍", "重说", "重复上一条"),
        "stop": ("停止", "停下", "别说了", "闭嘴"),
        "cancel": ("取消", "算了", "不用了", "不用回答"),
    }

    def __init__(self, *, aliases: dict[str, tuple[str, ...]] | None = None, threshold: float = 0.6) -> None:
        self.aliases = aliases or self.DEFAULT_ALIASES
        self.threshold = threshold

    def recognize_turn(self, turn: VoiceTurn) -> FastIntentResult:
        transcript_text = str(
            turn.metadata.get("transcript_text")
            or turn.metadata.get("transcript_hint")
            or ""
        ).strip()
        normalized_text = " ".join(transcript_text.lower().split())
        if not normalized_text:
            return FastIntentResult(
                lane="fast_intent",
                status="no_transcript",
                transcript_text=transcript_text,
                normalized_text=normalized_text,
                query_kind=None,
                confidence=0.0,
                matched_phrase=None,
                metadata={"turn_id": turn.turn_id},
            )

        best_query_kind: str | None = None
        best_phrase: str | None = None
        best_score = 0.0
        for query_kind, phrases in self.aliases.items():
            for phrase in phrases:
                score = self._score_phrase(normalized_text, phrase.lower())
                if score > best_score:
                    best_score = score
                    best_query_kind = query_kind
                    best_phrase = phrase

        status = "matched" if best_query_kind is not None and best_score >= self.threshold else "fallback"
        return FastIntentResult(
            lane="fast_intent",
            status=status,
            transcript_text=transcript_text,
            normalized_text=normalized_text,
            query_kind=best_query_kind if status == "matched" else None,
            confidence=round(best_score, 4),
            matched_phrase=best_phrase if status == "matched" else None,
            metadata={"turn_id": turn.turn_id, "threshold": self.threshold},
        )

    def _score_phrase(self, normalized_text: str, phrase: str) -> float:
        if normalized_text == phrase:
            return 1.0
        if phrase in normalized_text:
            return min(0.95, max(len(phrase) / max(len(normalized_text), 1), 0.65))
        overlap = len(set(normalized_text) & set(phrase))
        union = len(set(normalized_text) | set(phrase)) or 1
        return overlap / union

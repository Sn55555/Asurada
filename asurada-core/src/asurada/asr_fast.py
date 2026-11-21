from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .voice_turn import VoiceTurn
from .capability_definitions import fast_intent_aliases


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

    DEFAULT_ALIASES: dict[str, tuple[str, ...]] = fast_intent_aliases()

    def __init__(self, *, aliases: dict[str, tuple[str, ...]] | None = None, threshold: float = 0.6) -> None:
        self.aliases = aliases or fast_intent_aliases()
        self.threshold = threshold

    def recognize_turn(self, turn: VoiceTurn) -> FastIntentResult:
        transcript_text = str(turn.metadata.get("transcript_text") or "").strip()
        transcript_hint = str(turn.metadata.get("transcript_hint") or "").strip()
        primary_text = transcript_text or transcript_hint
        primary_normalized = " ".join(primary_text.lower().split())
        if not primary_normalized:
            return FastIntentResult(
                lane="fast_intent",
                status="no_transcript",
                transcript_text=primary_text,
                normalized_text=primary_normalized,
                query_kind=None,
                confidence=0.0,
                matched_phrase=None,
                metadata={"turn_id": turn.turn_id},
            )

        chosen_text = primary_text
        chosen_normalized = primary_normalized
        chosen_source = "transcript_text" if transcript_text else "transcript_hint"
        best_query_kind, best_phrase, best_score = self._best_match_for_text(primary_normalized)

        if transcript_hint:
            hint_normalized = " ".join(transcript_hint.lower().split())
            hint_query_kind, hint_phrase, hint_score = self._best_match_for_text(hint_normalized)
            if hint_score > best_score:
                chosen_text = transcript_hint
                chosen_normalized = hint_normalized
                chosen_source = "transcript_hint"
                best_query_kind = hint_query_kind
                best_phrase = hint_phrase
                best_score = hint_score

        status = "matched" if best_query_kind is not None and best_score >= self.threshold else "fallback"
        return FastIntentResult(
            lane="fast_intent",
            status=status,
            transcript_text=chosen_text,
            normalized_text=chosen_normalized,
            query_kind=best_query_kind if status == "matched" else None,
            confidence=round(best_score, 4),
            matched_phrase=best_phrase if status == "matched" else None,
            metadata={
                "turn_id": turn.turn_id,
                "threshold": self.threshold,
                "transcript_source": chosen_source,
                "original_transcript_text": transcript_text,
                "transcript_hint": transcript_hint,
            },
        )

    def _best_match_for_text(self, normalized_text: str) -> tuple[str | None, str | None, float]:
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
        return best_query_kind, best_phrase, best_score

    def _score_phrase(self, normalized_text: str, phrase: str) -> float:
        if normalized_text == phrase:
            return 1.0
        if phrase in normalized_text:
            return min(0.95, max(len(phrase) / max(len(normalized_text), 1), 0.65))
        overlap = len(set(normalized_text) & set(phrase))
        union = len(set(normalized_text) | set(phrase)) or 1
        return overlap / union

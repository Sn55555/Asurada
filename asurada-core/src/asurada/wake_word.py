from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .voice_turn import VoiceTurn


@dataclass(frozen=True)
class WakeWordResult:
    status: str
    transcript_text: str
    normalized_text: str
    matched_phrase: str | None
    activation_expires_at_ms: int | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WakeWordGate:
    """Optional wake-word gate layered ahead of semantic query routing."""

    DEFAULT_PHRASES: tuple[str, ...] = ("阿斯拉达", "asurada")
    DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
        "阿斯拉达": (
            "饿死拉倒",
            "艾斯拉达",
            "阿思拉达",
            "阿斯拉到",
            "阿斯拉道",
            "阿斯兰达",
        ),
        "asurada": ("阿斯拉达",),
    }

    def __init__(
        self,
        *,
        enabled: bool = False,
        phrases: tuple[str, ...] | None = None,
        aliases: dict[str, tuple[str, ...]] | None = None,
        activation_window_ms: int = 8_000,
    ) -> None:
        self.enabled = enabled
        self.phrases = tuple(item for item in (phrases or self.DEFAULT_PHRASES) if item)
        self.aliases = aliases or self.DEFAULT_ALIASES
        self.activation_window_ms = activation_window_ms
        self._active_until_ms = 0
        self._active_source: str | None = None
        self._active_phrase: str | None = None

    def evaluate(self, turn: VoiceTurn) -> WakeWordResult:
        transcript_text = str(
            turn.metadata.get("transcript_text")
            or turn.metadata.get("transcript_hint")
            or ""
        ).strip()
        transcript_hint = str(turn.metadata.get("transcript_hint") or "").strip()
        normalized_text = " ".join(transcript_text.lower().split())
        timestamp_ms = int(turn.ended_at_ms or turn.started_at_ms or 0)

        if not self.enabled:
            return WakeWordResult(
                status="disabled_passthrough",
                transcript_text=transcript_text,
                normalized_text=normalized_text,
                matched_phrase=None,
                activation_expires_at_ms=None,
                reason="wake_word_disabled",
            )

        if self._is_within_active_window(timestamp_ms):
            self._arm(
                timestamp_ms=timestamp_ms,
                source=self._active_source or "wake_window_active",
                matched_phrase=self._active_phrase,
            )
            return WakeWordResult(
                status="active_window",
                transcript_text=transcript_text,
                normalized_text=normalized_text,
                matched_phrase=self._active_phrase,
                activation_expires_at_ms=self._active_until_ms,
                reason="wake_window_active",
                metadata={
                    "activation_source": self._active_source,
                    "activation_phrase": self._active_phrase,
                },
            )

        matched_phrase, remainder, matched_source = self._match_with_hint(
            transcript_text=transcript_text,
            transcript_hint=transcript_hint,
        )
        if matched_phrase is None:
            return WakeWordResult(
                status="ignored_missing_wake_word",
                transcript_text=transcript_text,
                normalized_text=normalized_text,
                matched_phrase=None,
                activation_expires_at_ms=None,
                reason="wake_word_required",
                metadata={"phrases": list(self.phrases)},
            )

        self._arm(
            timestamp_ms=timestamp_ms,
            source="wake_word_match",
            matched_phrase=matched_phrase,
        )
        trimmed_remainder = remainder.strip()
        if not trimmed_remainder:
            return WakeWordResult(
                status="wake_only",
                transcript_text="",
                normalized_text="",
                matched_phrase=matched_phrase,
                activation_expires_at_ms=self._active_until_ms,
                reason="wake_word_armed",
                metadata={"phrases": list(self.phrases)},
            )

        return WakeWordResult(
            status="inline_query",
            transcript_text=trimmed_remainder,
            normalized_text=" ".join(trimmed_remainder.lower().split()),
            matched_phrase=matched_phrase,
            activation_expires_at_ms=self._active_until_ms,
            reason="wake_word_inline_query",
            metadata={"phrases": list(self.phrases), "matched_source": matched_source},
        )

    def preview_match(self, transcript_text: str) -> tuple[str | None, str]:
        matched_phrase, remainder = self._match_prefix(transcript_text)
        if matched_phrase is None:
            return None, str(transcript_text or "").strip()
        return matched_phrase, remainder.strip()

    def arm_from_preview(self, *, timestamp_ms: int, matched_phrase: str | None) -> int | None:
        if not self.enabled or timestamp_ms <= 0:
            return None
        self._arm(
            timestamp_ms=timestamp_ms,
            source="partial_preview",
            matched_phrase=matched_phrase,
        )
        return self._active_until_ms

    def _is_within_active_window(self, timestamp_ms: int) -> bool:
        return timestamp_ms > 0 and timestamp_ms <= self._active_until_ms

    def _arm(self, *, timestamp_ms: int, source: str, matched_phrase: str | None) -> None:
        self._active_until_ms = timestamp_ms + self.activation_window_ms
        self._active_source = source
        self._active_phrase = matched_phrase

    def _match_prefix(self, transcript_text: str) -> tuple[str | None, str]:
        source = transcript_text.strip()
        lowered = source.lower()
        candidates: list[tuple[str, str]] = []
        for phrase in self.phrases:
            canonical = phrase.strip()
            if not canonical:
                continue
            candidates.append((canonical, canonical))
            for alias in self.aliases.get(canonical, ()):
                alias_text = alias.strip()
                if alias_text:
                    candidates.append((canonical, alias_text))

        # Prefer longer aliases/canonicals first to avoid partial shadowing.
        for canonical, candidate in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
            lowered_phrase = candidate.lower()
            if lowered == lowered_phrase:
                return canonical, ""
            if lowered.startswith(lowered_phrase):
                remainder = source[len(candidate) :]
                remainder = remainder.lstrip(" \t,.;:!?，。！？、：；")
                return canonical, remainder
        return None, source

    def _match_with_hint(self, *, transcript_text: str, transcript_hint: str) -> tuple[str | None, str, str | None]:
        matched_phrase, remainder = self._match_prefix(transcript_text)
        if matched_phrase is not None:
            return matched_phrase, remainder, "transcript_text"
        if transcript_hint:
            hint_match, hint_remainder = self._match_prefix(transcript_hint)
            if hint_match is not None:
                if transcript_text.strip():
                    return hint_match, transcript_text.strip(), "transcript_hint"
                return hint_match, hint_remainder, "transcript_hint"
        return None, transcript_text, None

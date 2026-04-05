from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .audio_io import AudioChunk, AudioFormat
from .vad import VadActivity, VadDecision


@dataclass(frozen=True)
class VoiceTurn:
    """Completed audio turn ready for ASR or routing."""

    turn_id: str
    started_at_ms: int
    ended_at_ms: int
    audio_format: AudioFormat
    pcm_s16le: bytes
    chunk_count: int
    source: str
    completion_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return max(self.ended_at_ms - self.started_at_ms, 0)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pcm_bytes"] = len(self.pcm_s16le)
        payload.pop("pcm_s16le", None)
        payload["duration_ms"] = self.duration_ms
        return payload


@dataclass(frozen=True)
class VoiceTurnEvent:
    """Lifecycle event emitted by the voice turn manager."""

    event_type: str
    timestamp_ms: int
    turn_id: str | None
    ptt_pressed: bool
    reason: str
    vad_activity: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceTurnManager:
    """PTT + VAD coordinator that forms complete audio turns."""

    def __init__(
        self,
        *,
        require_ptt: bool = True,
        max_turn_ms: int = 12_000,
    ) -> None:
        self.require_ptt = require_ptt
        self.max_turn_ms = max_turn_ms
        self._ptt_pressed = False
        self._armed_since_ms: int | None = None
        self._active_turn_id: str | None = None
        self._turn_started_at_ms: int | None = None
        self._turn_source = "ptt"
        self._turn_chunks: list[AudioChunk] = []
        self._turn_counter = 0

    def set_ptt_pressed(self, pressed: bool, *, timestamp_ms: int) -> list[VoiceTurnEvent]:
        events: list[VoiceTurnEvent] = []
        if pressed == self._ptt_pressed:
            return events

        self._ptt_pressed = pressed
        if pressed:
            self._armed_since_ms = timestamp_ms
            events.append(
                VoiceTurnEvent(
                    event_type="ptt_armed",
                    timestamp_ms=timestamp_ms,
                    turn_id=self._active_turn_id,
                    ptt_pressed=True,
                    reason="ptt_pressed",
                    vad_activity="n/a",
                )
            )
            return events

        if self._active_turn_id is not None:
            events.append(
                VoiceTurnEvent(
                    event_type="turn_finalize_requested",
                    timestamp_ms=timestamp_ms,
                    turn_id=self._active_turn_id,
                    ptt_pressed=False,
                    reason="ptt_released",
                    vad_activity="n/a",
                )
            )
        else:
            self._armed_since_ms = None
            events.append(
                VoiceTurnEvent(
                    event_type="ptt_released",
                    timestamp_ms=timestamp_ms,
                    turn_id=None,
                    ptt_pressed=False,
                    reason="ptt_released_without_turn",
                    vad_activity="n/a",
                )
            )
        return events

    def ingest_chunk(
        self,
        *,
        chunk: AudioChunk,
        vad_decision: VadDecision,
        vad_activity: VadActivity,
    ) -> tuple[list[VoiceTurnEvent], VoiceTurn | None]:
        events: list[VoiceTurnEvent] = []
        completed_turn: VoiceTurn | None = None

        if self.require_ptt and not self._ptt_pressed and self._active_turn_id is None:
            return (
                [
                    VoiceTurnEvent(
                        event_type="chunk_ignored",
                        timestamp_ms=chunk.timestamp_ms,
                        turn_id=None,
                        ptt_pressed=False,
                        reason="ptt_not_pressed",
                        vad_activity=vad_activity.event_type,
                        metadata={"speech_probability": vad_decision.speech_probability},
                    )
                ],
                None,
            )

        if self._active_turn_id is None and vad_activity.event_type == "speech_start":
            self._turn_counter += 1
            self._active_turn_id = f"voice-turn:{self._turn_counter}"
            self._turn_started_at_ms = chunk.timestamp_ms
            self._turn_chunks = []
            events.append(
                VoiceTurnEvent(
                    event_type="turn_started",
                    timestamp_ms=chunk.timestamp_ms,
                    turn_id=self._active_turn_id,
                    ptt_pressed=self._ptt_pressed,
                    reason="vad_speech_start",
                    vad_activity=vad_activity.event_type,
                    metadata={"speech_probability": vad_decision.speech_probability},
                )
            )

        if self._active_turn_id is None:
            return events, None

        self._turn_chunks.append(chunk)
        events.append(
            VoiceTurnEvent(
                event_type="turn_chunk",
                timestamp_ms=chunk.timestamp_ms,
                turn_id=self._active_turn_id,
                ptt_pressed=self._ptt_pressed,
                reason="chunk_buffered",
                vad_activity=vad_activity.event_type,
                metadata={
                    "speech_probability": vad_decision.speech_probability,
                    "chunk_sequence_id": chunk.sequence_id,
                },
            )
        )

        should_finalize = False
        reason = ""
        started_at_ms = self._turn_started_at_ms or chunk.timestamp_ms
        if not self._ptt_pressed:
            should_finalize = True
            reason = "ptt_released"
        elif vad_activity.event_type == "speech_end":
            should_finalize = True
            reason = "vad_speech_end"
        elif chunk.timestamp_ms - started_at_ms >= self.max_turn_ms:
            should_finalize = True
            reason = "max_turn_ms"

        if should_finalize:
            completed_turn = self._finalize_turn(timestamp_ms=chunk.timestamp_ms, reason=reason)
            events.append(
                VoiceTurnEvent(
                    event_type="turn_completed",
                    timestamp_ms=chunk.timestamp_ms,
                    turn_id=completed_turn.turn_id,
                    ptt_pressed=self._ptt_pressed,
                    reason=reason,
                    vad_activity=vad_activity.event_type,
                    metadata={
                        "duration_ms": completed_turn.duration_ms,
                        "chunk_count": completed_turn.chunk_count,
                    },
                )
            )

        return events, completed_turn

    def _finalize_turn(self, *, timestamp_ms: int, reason: str) -> VoiceTurn:
        if not self._turn_chunks or self._active_turn_id is None or self._turn_started_at_ms is None:
            raise RuntimeError("cannot finalize an empty voice turn")
        audio_format = self._turn_chunks[0].audio_format
        pcm = b"".join(chunk.pcm_s16le for chunk in self._turn_chunks)
        completed = VoiceTurn(
            turn_id=self._active_turn_id,
            started_at_ms=self._turn_started_at_ms,
            ended_at_ms=timestamp_ms,
            audio_format=audio_format,
            pcm_s16le=pcm,
            chunk_count=len(self._turn_chunks),
            source=self._turn_source,
            completion_reason=reason,
            metadata={
                "ptt_required": self.require_ptt,
                "armed_since_ms": self._armed_since_ms,
            },
        )
        self._active_turn_id = None
        self._turn_started_at_ms = None
        self._turn_chunks = []
        self._armed_since_ms = None if not self._ptt_pressed else timestamp_ms
        return completed

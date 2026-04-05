from __future__ import annotations

import audioop
from dataclasses import asdict, dataclass, field
from typing import Any

from .audio_io import AudioChunk


@dataclass(frozen=True)
class VadDecision:
    """Single-chunk VAD output."""

    timestamp_ms: int
    duration_ms: int
    speech_probability: float
    speech_detected: bool
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VadActivity:
    """Smoothed VAD state used by the turn manager."""

    timestamp_ms: int
    event_type: str
    speech_active: bool
    speech_probability: float
    silence_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VadBackend:
    """Abstract VAD backend."""

    def analyze(self, chunk: AudioChunk) -> VadDecision:
        raise NotImplementedError


class EnergyVadBackend(VadBackend):
    """Deterministic PCM energy VAD used as the default fallback."""

    def __init__(self, *, rms_threshold: int = 900) -> None:
        self.rms_threshold = rms_threshold

    def analyze(self, chunk: AudioChunk) -> VadDecision:
        if not chunk.pcm_s16le:
            probability = 0.0
            rms = 0
        else:
            rms = audioop.rms(chunk.pcm_s16le, chunk.audio_format.sample_width_bytes)
            probability = max(0.0, min(float(rms) / float(max(self.rms_threshold, 1) * 2.0), 1.0))
        return VadDecision(
            timestamp_ms=chunk.timestamp_ms,
            duration_ms=chunk.duration_ms,
            speech_probability=round(probability, 4),
            speech_detected=rms >= self.rms_threshold,
            backend=type(self).__name__,
            metadata={"rms": rms, "rms_threshold": self.rms_threshold},
        )


class VoiceActivityDetector:
    """Smoothed VAD coordinator with start hysteresis and stop hangover."""

    def __init__(
        self,
        *,
        backend: VadBackend | None = None,
        start_trigger_count: int = 2,
        end_silence_ms: int = 320,
    ) -> None:
        self.backend = backend or EnergyVadBackend()
        self.start_trigger_count = start_trigger_count
        self.end_silence_ms = end_silence_ms
        self._speech_active = False
        self._consecutive_speech = 0
        self._silence_ms = 0

    def reset(self) -> None:
        self._speech_active = False
        self._consecutive_speech = 0
        self._silence_ms = 0

    def process_chunk(self, chunk: AudioChunk) -> tuple[VadDecision, VadActivity]:
        decision = self.backend.analyze(chunk)
        event_type = "silence"

        if decision.speech_detected:
            self._consecutive_speech += 1
            self._silence_ms = 0
            if self._speech_active:
                event_type = "speech_continue"
            elif self._consecutive_speech >= self.start_trigger_count:
                self._speech_active = True
                event_type = "speech_start"
            else:
                event_type = "speech_candidate"
        else:
            self._consecutive_speech = 0
            if self._speech_active:
                self._silence_ms += decision.duration_ms
                if self._silence_ms >= self.end_silence_ms:
                    self._speech_active = False
                    event_type = "speech_end"
                    self._silence_ms = 0
                else:
                    event_type = "speech_hold"
            else:
                event_type = "silence"

        activity = VadActivity(
            timestamp_ms=decision.timestamp_ms,
            event_type=event_type,
            speech_active=self._speech_active,
            speech_probability=decision.speech_probability,
            silence_ms=self._silence_ms,
            metadata={"backend": decision.backend},
        )
        return decision, activity

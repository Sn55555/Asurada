from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AudioFormat:
    """Canonical PCM format used by the voice module."""

    sample_rate_hz: int = 16_000
    channels: int = 1
    sample_width_bytes: int = 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate_hz * self.channels * self.sample_width_bytes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AudioChunk:
    """Single captured PCM chunk."""

    sequence_id: int
    timestamp_ms: int
    pcm_s16le: bytes
    audio_format: AudioFormat = field(default_factory=AudioFormat)
    source: str = "microphone"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        if self.audio_format.bytes_per_second <= 0:
            return 0
        return int(round((len(self.pcm_s16le) / self.audio_format.bytes_per_second) * 1000.0))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pcm_bytes"] = len(self.pcm_s16le)
        payload.pop("pcm_s16le", None)
        return payload


@dataclass(frozen=True)
class AudioDeviceDescriptor:
    """Minimal device descriptor for future device routing."""

    device_id: str
    name: str
    direction: str
    default_format: AudioFormat = field(default_factory=AudioFormat)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AudioInputBackend:
    """Abstract audio capture backend."""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def read_chunk(self) -> AudioChunk | None:
        raise NotImplementedError

    def is_active(self) -> bool:
        raise NotImplementedError


class AudioOutputBackend:
    """Abstract audio playback backend."""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def play_chunk(self, chunk: AudioChunk) -> None:
        raise NotImplementedError

    def is_active(self) -> bool:
        raise NotImplementedError


class NullAudioInputBackend(AudioInputBackend):
    """No-op input backend used in regression and dry-run flows."""

    def __init__(self) -> None:
        self._active = False

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def read_chunk(self) -> AudioChunk | None:
        return None

    def is_active(self) -> bool:
        return self._active


class NullAudioOutputBackend(AudioOutputBackend):
    """No-op playback backend used until device playback is wired in."""

    def __init__(self) -> None:
        self._active = False
        self._played_chunks = 0

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def play_chunk(self, chunk: AudioChunk) -> None:
        if self._active:
            self._played_chunks += 1

    def is_active(self) -> bool:
        return self._active


class AudioIO:
    """Thin coordinator for audio capture/output backends."""

    def __init__(
        self,
        *,
        input_backend: AudioInputBackend | None = None,
        output_backend: AudioOutputBackend | None = None,
    ) -> None:
        self.input_backend = input_backend or NullAudioInputBackend()
        self.output_backend = output_backend or NullAudioOutputBackend()

    def start(self) -> None:
        self.input_backend.start()
        self.output_backend.start()

    def stop(self) -> None:
        self.input_backend.stop()
        self.output_backend.stop()

    def read_input_chunk(self) -> AudioChunk | None:
        return self.input_backend.read_chunk()

    def play_output_chunk(self, chunk: AudioChunk) -> None:
        self.output_backend.play_chunk(chunk)

    def describe(self) -> dict[str, Any]:
        return {
            "input_backend": type(self.input_backend).__name__,
            "output_backend": type(self.output_backend).__name__,
            "input_active": self.input_backend.is_active(),
            "output_active": self.output_backend.is_active(),
        }

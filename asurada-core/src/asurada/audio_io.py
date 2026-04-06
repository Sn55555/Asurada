from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
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


@dataclass(frozen=True)
class AlsaAudioInputConfig:
    """Configuration for ALSA `arecord` capture."""

    audio_format: AudioFormat = field(default_factory=AudioFormat)
    period_ms: int = 40
    device: str | None = None
    arecord_binary: str = "arecord"
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlsaAudioOutputConfig:
    """Configuration for ALSA `aplay` playback."""

    audio_format: AudioFormat = field(default_factory=AudioFormat)
    device: str | None = None
    aplay_binary: str = "aplay"
    extra_args: tuple[str, ...] = ()


class AlsaArecordInputBackend(AudioInputBackend):
    """Linux/ALSA microphone capture backend using `arecord`."""

    def __init__(self, config: AlsaAudioInputConfig | None = None) -> None:
        self.config = config or AlsaAudioInputConfig()
        self._process: subprocess.Popen[bytes] | None = None
        self._sequence_id = 0

    @classmethod
    def from_env(cls) -> "AlsaArecordInputBackend":
        fmt = AudioFormat(
            sample_rate_hz=int(os.getenv("ASURADA_AUDIO_SAMPLE_RATE_HZ", "16000")),
            channels=int(os.getenv("ASURADA_AUDIO_CHANNELS", "1")),
            sample_width_bytes=int(os.getenv("ASURADA_AUDIO_SAMPLE_WIDTH_BYTES", "2")),
        )
        extra = tuple(shlex.split(str(os.getenv("ASURADA_ARECORD_EXTRA_ARGS", ""))))
        return cls(
            AlsaAudioInputConfig(
                audio_format=fmt,
                period_ms=int(os.getenv("ASURADA_AUDIO_PERIOD_MS", "40")),
                device=os.getenv("ASURADA_ARECORD_DEVICE") or None,
                arecord_binary=os.getenv("ASURADA_ARECORD_BINARY", "arecord"),
                extra_args=extra,
            )
        )

    def start(self) -> None:
        if self.is_active():
            return
        self._process = subprocess.Popen(
            self._build_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1.0)
        self._process = None

    def read_chunk(self) -> AudioChunk | None:
        if not self.is_active() or self._process is None or self._process.stdout is None:
            return None
        chunk_bytes = self._chunk_size_bytes()
        pcm = self._process.stdout.read(chunk_bytes)
        if not pcm:
            return None
        self._sequence_id += 1
        return AudioChunk(
            sequence_id=self._sequence_id,
            timestamp_ms=int(time.time() * 1000),
            pcm_s16le=pcm,
            audio_format=self.config.audio_format,
            source="alsa_arecord",
            metadata={
                "device": self.config.device,
                "backend": type(self).__name__,
            },
        )

    def is_active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _build_command(self) -> list[str]:
        fmt = self.config.audio_format
        cmd = [
            self.config.arecord_binary,
            "-q",
            "-t",
            "raw",
            "-f",
            _alsa_format(fmt),
            "-c",
            str(fmt.channels),
            "-r",
            str(fmt.sample_rate_hz),
        ]
        if self.config.device:
            cmd.extend(["-D", self.config.device])
        cmd.extend(self.config.extra_args)
        return cmd

    def _chunk_size_bytes(self) -> int:
        fmt = self.config.audio_format
        return max(int(round((fmt.bytes_per_second * self.config.period_ms) / 1000.0)), 1)


class AlsaAplayOutputBackend(AudioOutputBackend):
    """Linux/ALSA speaker output backend using `aplay`."""

    def __init__(self, config: AlsaAudioOutputConfig | None = None) -> None:
        self.config = config or AlsaAudioOutputConfig()
        self._process: subprocess.Popen[bytes] | None = None

    @classmethod
    def from_env(cls) -> "AlsaAplayOutputBackend":
        fmt = AudioFormat(
            sample_rate_hz=int(os.getenv("ASURADA_AUDIO_SAMPLE_RATE_HZ", "16000")),
            channels=int(os.getenv("ASURADA_AUDIO_CHANNELS", "1")),
            sample_width_bytes=int(os.getenv("ASURADA_AUDIO_SAMPLE_WIDTH_BYTES", "2")),
        )
        extra = tuple(shlex.split(str(os.getenv("ASURADA_APLAY_EXTRA_ARGS", ""))))
        return cls(
            AlsaAudioOutputConfig(
                audio_format=fmt,
                device=os.getenv("ASURADA_APLAY_DEVICE") or None,
                aplay_binary=os.getenv("ASURADA_APLAY_BINARY", "aplay"),
                extra_args=extra,
            )
        )

    def start(self) -> None:
        if self.is_active():
            return
        self._process = subprocess.Popen(
            self._build_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except BrokenPipeError:
                pass
        if self._process.poll() is None:
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        self._process = None

    def play_chunk(self, chunk: AudioChunk) -> None:
        if not self.is_active() or self._process is None or self._process.stdin is None:
            return
        try:
            self._process.stdin.write(chunk.pcm_s16le)
            self._process.stdin.flush()
        except BrokenPipeError:
            self.stop()

    def is_active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _build_command(self) -> list[str]:
        fmt = self.config.audio_format
        cmd = [
            self.config.aplay_binary,
            "-q",
            "-t",
            "raw",
            "-f",
            _alsa_format(fmt),
            "-c",
            str(fmt.channels),
            "-r",
            str(fmt.sample_rate_hz),
        ]
        if self.config.device:
            cmd.extend(["-D", self.config.device])
        cmd.extend(self.config.extra_args)
        return cmd


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


def resolve_default_audio_io() -> AudioIO:
    """Resolve a platform-aware AudioIO pair without forcing device startup."""

    if _alsa_env_ready():
        return AudioIO(
            input_backend=AlsaArecordInputBackend.from_env(),
            output_backend=AlsaAplayOutputBackend.from_env(),
        )
    return AudioIO()


def _alsa_format(audio_format: AudioFormat) -> str:
    if audio_format.sample_width_bytes == 2:
        return "S16_LE"
    raise ValueError(f"unsupported ALSA sample width: {audio_format.sample_width_bytes}")


def _alsa_env_ready() -> bool:
    if os.name != "posix":
        return False
    arecord_binary = os.getenv("ASURADA_ARECORD_BINARY", "arecord")
    aplay_binary = os.getenv("ASURADA_APLAY_BINARY", "aplay")
    return shutil.which(arecord_binary) is not None and shutil.which(aplay_binary) is not None

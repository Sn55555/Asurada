from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class MacOSAudioStreamConfig:
    swift_binary: str
    script_path: str
    listen_timeout_s: float = 8.0
    silence_timeout_s: float = 1.2
    command_timeout_s: float = 20.0
    level_threshold: float = 0.010


@dataclass(frozen=True)
class MacOSAudioStreamEvent:
    type: str
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    duration_ms: int | None = None
    status: str | None = None
    audio_base64: str | None = None
    rms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MacOSAudioStreamCapture:
    def __init__(self, config: MacOSAudioStreamConfig | None = None) -> None:
        self.config = config or self.from_env().config

    @classmethod
    def from_env(cls) -> "MacOSAudioStreamCapture":
        script_path = os.getenv("ASURADA_MACOS_AUDIO_STREAM_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_audio_stream.swift"
        )
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or shutil.which("swift") or "/usr/bin/swift"
        return cls(
            MacOSAudioStreamConfig(
                swift_binary=swift_binary,
                script_path=script_path,
                listen_timeout_s=float(os.getenv("ASURADA_MACOS_LISTEN_TIMEOUT_S", "8.0")),
                silence_timeout_s=float(os.getenv("ASURADA_MACOS_SILENCE_TIMEOUT_S", "1.2")),
                command_timeout_s=float(os.getenv("ASURADA_MACOS_COMMAND_TIMEOUT_S", "20.0")),
                level_threshold=float(os.getenv("ASURADA_MACOS_AUDIO_LEVEL_THRESHOLD", "0.010")),
            )
        )

    @classmethod
    def env_ready(cls) -> bool:
        if sys.platform != "darwin":
            return False
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or "swift"
        script_path = os.getenv("ASURADA_MACOS_AUDIO_STREAM_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_audio_stream.swift"
        )
        return shutil.which(swift_binary) is not None and Path(script_path).exists()

    def iter_events(self) -> Iterator[MacOSAudioStreamEvent]:
        process = subprocess.Popen(
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                raw = line.strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                yield MacOSAudioStreamEvent(
                    type=str(payload.get("type") or "unknown"),
                    started_at_ms=_optional_int(payload.get("started_at_ms")),
                    ended_at_ms=_optional_int(payload.get("ended_at_ms")),
                    duration_ms=_optional_int(payload.get("duration_ms")),
                    status=_optional_str(payload.get("status")),
                    audio_base64=_optional_str(payload.get("audio_base64")),
                    rms=_optional_float(payload.get("rms")),
                    metadata=dict(payload.get("metadata") or {}),
                )
        finally:
            try:
                process.wait(timeout=self.config.command_timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
                raise RuntimeError("macOS audio stream timed out")
            stderr = process.stderr.read().strip() if process.stderr is not None else ""
            if process.returncode != 0:
                raise RuntimeError(
                    "macOS audio stream failed: "
                    f"code={process.returncode} stderr={stderr}"
                )

    def _command(self) -> list[str]:
        cfg = self.config
        return [
            cfg.swift_binary,
            cfg.script_path,
            "--listen-timeout",
            str(cfg.listen_timeout_s),
            "--silence-timeout",
            str(cfg.silence_timeout_s),
            "--level-threshold",
            str(cfg.level_threshold),
        ]


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "MacOSAudioStreamCapture",
    "MacOSAudioStreamConfig",
    "MacOSAudioStreamEvent",
]

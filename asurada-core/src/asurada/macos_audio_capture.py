from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MacOSAudioCaptureConfig:
    swift_binary: str
    script_path: str
    listen_timeout_s: float = 6.0
    silence_timeout_s: float = 1.0
    command_timeout_s: float = 20.0
    level_threshold: float = 0.010


@dataclass(frozen=True)
class MacOSAudioCaptureResult:
    status: str
    audio_file_path: str
    started_at_ms: int
    ended_at_ms: int
    duration_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MacOSAudioCapture:
    """Development-only macOS microphone capture for local ASR backends."""

    def __init__(self, config: MacOSAudioCaptureConfig | None = None) -> None:
        self.config = config or self.from_env().config

    @classmethod
    def from_env(cls) -> "MacOSAudioCapture":
        script_path = os.getenv("ASURADA_MACOS_AUDIO_CAPTURE_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_audio_capture.swift"
        )
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or shutil.which("swift") or "/usr/bin/swift"
        return cls(
            MacOSAudioCaptureConfig(
                swift_binary=swift_binary,
                script_path=script_path,
                listen_timeout_s=float(os.getenv("ASURADA_MACOS_LISTEN_TIMEOUT_S", "6.0")),
                silence_timeout_s=float(os.getenv("ASURADA_MACOS_SILENCE_TIMEOUT_S", "1.0")),
                command_timeout_s=float(os.getenv("ASURADA_MACOS_COMMAND_TIMEOUT_S", "20.0")),
                level_threshold=float(os.getenv("ASURADA_MACOS_AUDIO_LEVEL_THRESHOLD", "0.010")),
            )
        )

    @classmethod
    def env_ready(cls) -> bool:
        if sys.platform != "darwin":
            return False
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or "swift"
        script_path = os.getenv("ASURADA_MACOS_AUDIO_CAPTURE_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_audio_capture.swift"
        )
        return shutil.which(swift_binary) is not None and Path(script_path).exists()

    def capture_once(self) -> MacOSAudioCaptureResult:
        completed = subprocess.run(
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.config.command_timeout_s,
        )
        stdout = completed.stdout.strip()
        if completed.returncode != 0:
            raise RuntimeError(
                "macOS audio capture failed: "
                f"code={completed.returncode} stderr={completed.stderr.strip()}"
            )
        if not stdout:
            raise RuntimeError("macOS audio capture returned empty stdout")
        payload = json.loads(stdout)
        return MacOSAudioCaptureResult(
            status=str(payload.get("status") or "unknown"),
            audio_file_path=str(payload.get("audio_file_path") or ""),
            started_at_ms=int(payload.get("started_at_ms") or 0),
            ended_at_ms=int(payload.get("ended_at_ms") or 0),
            duration_ms=int(payload.get("duration_ms") or 0),
            metadata=dict(payload.get("metadata") or {}),
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

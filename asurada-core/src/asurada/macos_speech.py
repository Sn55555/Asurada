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
class MacOSSpeechRecognizerConfig:
    swift_binary: str
    script_path: str
    locale: str = "zh-CN"
    listen_timeout_s: float = 6.0
    silence_timeout_s: float = 1.0
    command_timeout_s: float = 20.0


@dataclass(frozen=True)
class MacOSSpeechRecognitionResult:
    status: str
    transcript_text: str
    confidence: float | None
    started_at_ms: int
    ended_at_ms: int
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MacOSSpeechRecognizer:
    """Development-only macOS microphone recognizer backed by Swift Speech APIs."""

    def __init__(self, config: MacOSSpeechRecognizerConfig | None = None) -> None:
        self.config = config or self.from_env().config

    @classmethod
    def from_env(cls) -> "MacOSSpeechRecognizer":
        script_path = os.getenv("ASURADA_MACOS_SPEECH_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_speech_capture.swift"
        )
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or shutil.which("swift") or "/usr/bin/swift"
        return cls(
            MacOSSpeechRecognizerConfig(
                swift_binary=swift_binary,
                script_path=script_path,
                locale=os.getenv("ASURADA_MACOS_SPEECH_LOCALE", "zh-CN"),
                listen_timeout_s=float(os.getenv("ASURADA_MACOS_LISTEN_TIMEOUT_S", "6.0")),
                silence_timeout_s=float(os.getenv("ASURADA_MACOS_SILENCE_TIMEOUT_S", "1.0")),
                command_timeout_s=float(os.getenv("ASURADA_MACOS_COMMAND_TIMEOUT_S", "20.0")),
            )
        )

    @classmethod
    def env_ready(cls) -> bool:
        if sys.platform != "darwin":
            return False
        swift_binary = os.getenv("ASURADA_SWIFT_BINARY") or "swift"
        script_path = os.getenv("ASURADA_MACOS_SPEECH_SCRIPT") or str(
            Path(__file__).resolve().parents[2] / "scripts" / "macos_speech_capture.swift"
        )
        return shutil.which(swift_binary) is not None and Path(script_path).exists()

    def listen_once(self) -> MacOSSpeechRecognitionResult:
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
                "macOS speech capture failed: "
                f"code={completed.returncode} stderr={completed.stderr.strip()}"
            )
        if not stdout:
            raise RuntimeError("macOS speech capture returned empty stdout")
        payload = json.loads(stdout)
        return MacOSSpeechRecognitionResult(
            status=str(payload.get("status") or "unknown"),
            transcript_text=str(payload.get("transcript_text") or ""),
            confidence=_optional_float(payload.get("confidence")),
            started_at_ms=int(payload.get("started_at_ms") or 0),
            ended_at_ms=int(payload.get("ended_at_ms") or 0),
            locale=str(payload.get("locale") or self.config.locale),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _command(self) -> list[str]:
        cfg = self.config
        return [
            cfg.swift_binary,
            cfg.script_path,
            "--locale",
            cfg.locale,
            "--listen-timeout",
            str(cfg.listen_timeout_s),
            "--silence-timeout",
            str(cfg.silence_timeout_s),
        ]


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

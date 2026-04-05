from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from .interaction import SpeechJob


class SpeechBackend:
    """Abstract speech backend used by the unified output coordinator."""

    def start(self, job: SpeechJob) -> Any:
        raise NotImplementedError

    def is_active(self, handle: Any) -> bool:
        raise NotImplementedError

    def stop(self, handle: Any) -> None:
        raise NotImplementedError


class NullSpeechBackend(SpeechBackend):
    """Fallback backend used when real TTS is unavailable."""

    def start(self, job: SpeechJob) -> Any:
        return None

    def is_active(self, handle: Any) -> bool:
        return False

    def stop(self, handle: Any) -> None:
        return None


class MacOSSayBackend(SpeechBackend):
    """macOS `say` backend for first-wave real downlink speech."""

    def __init__(self, say_binary: str | None = None) -> None:
        self.say_binary = say_binary or shutil.which("say") or "/usr/bin/say"

    def start(self, job: SpeechJob) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [self.say_binary, job.speak_text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def is_active(self, handle: subprocess.Popen[str] | None) -> bool:
        return handle is not None and handle.poll() is None

    def stop(self, handle: subprocess.Popen[str] | None) -> None:
        if handle is None or handle.poll() is not None:
            return
        handle.terminate()


@dataclass(frozen=True)
class PiperBackendConfig:
    piper_binary: str
    model_path: str
    config_path: str | None = None
    player_binary: str = "aplay"
    player_args: tuple[str, ...] = ()
    python_binary: str = sys.executable


class PiperBackend(SpeechBackend):
    """Device-side local TTS backend using the `piper` CLI and a WAV player."""

    def __init__(self, config: PiperBackendConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> "PiperBackend":
        model_path = os.getenv("ASURADA_PIPER_MODEL_PATH")
        if not model_path:
            raise ValueError("ASURADA_PIPER_MODEL_PATH is required for PiperBackend")

        piper_binary = os.getenv("ASURADA_PIPER_BINARY") or shutil.which("piper") or "piper"
        player_binary = (
            os.getenv("ASURADA_PIPER_PLAYER_BINARY")
            or shutil.which("aplay")
            or shutil.which("paplay")
            or shutil.which("ffplay")
            or "aplay"
        )
        player_args = tuple(shlex.split(os.getenv("ASURADA_PIPER_PLAYER_ARGS", "")))
        config_path = os.getenv("ASURADA_PIPER_CONFIG_PATH") or None
        python_binary = os.getenv("ASURADA_PIPER_PYTHON_BINARY") or sys.executable
        _validate_executable(piper_binary, "piper binary")
        _validate_executable(player_binary, "player binary")
        return cls(
            PiperBackendConfig(
                piper_binary=piper_binary,
                model_path=model_path,
                config_path=config_path,
                player_binary=player_binary,
                player_args=player_args,
                python_binary=python_binary,
            )
        )

    @classmethod
    def env_ready(cls) -> bool:
        if not os.getenv("ASURADA_PIPER_MODEL_PATH"):
            return False
        if shutil.which(os.getenv("ASURADA_PIPER_BINARY", "piper")) is None:
            return False
        player_binary = os.getenv("ASURADA_PIPER_PLAYER_BINARY")
        if player_binary:
            return shutil.which(player_binary) is not None
        return any(shutil.which(candidate) is not None for candidate in ("aplay", "paplay", "ffplay"))

    def start(self, job: SpeechJob) -> subprocess.Popen[str]:
        return subprocess.Popen(
            self._runner_command(job),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )

    def is_active(self, handle: subprocess.Popen[str] | None) -> bool:
        return handle is not None and handle.poll() is None

    def stop(self, handle: subprocess.Popen[str] | None) -> None:
        if handle is None or handle.poll() is not None:
            return
        try:
            os.killpg(handle.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _runner_command(self, job: SpeechJob) -> list[str]:
        cfg = self.config
        return [
            cfg.python_binary,
            "-c",
            _PIPER_RUNNER_SCRIPT,
            job.speak_text,
            cfg.piper_binary,
            cfg.model_path,
            cfg.config_path or "",
            cfg.player_binary,
            *cfg.player_args,
        ]


def resolve_default_speech_backend() -> SpeechBackend:
    forced_backend = str(os.getenv("ASURADA_TTS_BACKEND") or "").strip().lower()
    if forced_backend == "null":
        return NullSpeechBackend()
    if forced_backend == "piper":
        try:
            return PiperBackend.from_env()
        except ValueError:
            return NullSpeechBackend()
    if forced_backend == "say":
        if sys.platform == "darwin" and shutil.which("say") is not None:
            return MacOSSayBackend()
        return NullSpeechBackend()

    if sys.platform == "darwin" and shutil.which("say") is not None:
        return MacOSSayBackend()
    if sys.platform.startswith("linux") and PiperBackend.env_ready():
        try:
            return PiperBackend.from_env()
        except ValueError:
            return NullSpeechBackend()
    return NullSpeechBackend()


def _validate_executable(path_or_name: str, label: str) -> None:
    if os.path.isabs(path_or_name):
        if os.path.exists(path_or_name):
            return
        raise ValueError(f"{label} does not exist: {path_or_name}")
    if shutil.which(path_or_name) is not None:
        return
    raise ValueError(f"{label} is not available: {path_or_name}")


_PIPER_RUNNER_SCRIPT = """
import os
import subprocess
import sys
import tempfile

text, piper_binary, model_path, config_path, player_binary, *player_args = sys.argv[1:]
fd, wav_path = tempfile.mkstemp(prefix="asurada-piper-", suffix=".wav")
os.close(fd)
try:
    synth_cmd = [piper_binary, "--model", model_path]
    if config_path:
        synth_cmd.extend(["--config", config_path])
    synth_cmd.extend(["--output_file", wav_path])
    synth = subprocess.run(
        synth_cmd,
        input=text,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if synth.returncode != 0:
        sys.exit(synth.returncode)
    play = subprocess.run(
        [player_binary, *player_args, wav_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sys.exit(play.returncode)
finally:
    try:
        os.unlink(wav_path)
    except FileNotFoundError:
        pass
"""

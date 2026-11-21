"""Local Asurada voice routing under the shared speech scheduler."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import subprocess
from typing import Any

from .output_contracts import strategy_speech_band
from .personality_voice_worker import DELIVERIES, cache_filename, valid_voice_file
from .wing_damage import has_wing_compensation


def voice_cache_path(root: Path, text: str) -> Path:
    return root / "cache" / cache_filename(text)


def voice_delivery(job, *, urgent: bool) -> tuple[str, bool]:
    metadata = job.metadata or {}
    tone = (metadata.get("personality") or {}).get("tone")
    if urgent:
        return "urgent", False
    if metadata.get("pit_follow_up") or job.action_code in {"BOX_WINDOW", "BOX_NOW", "PIT_NOW"}:
        return "firm", False
    if tone in DELIVERIES:
        return tone, True
    return "calm", False


@dataclass(frozen=True)
class _VoiceHandle:
    process: Any
    local: bool


class AsuradaPersonalityVoice:
    """Play matched clips instantly and keep runtime synthesis cancellable."""

    audible = True

    def __init__(self, root: Path, fallback, *, player: str | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.fallback = fallback
        self.python = self.root / ".venv/bin/python"
        self.worker = Path(__file__).with_name("personality_voice_worker.py")
        self.player = shutil.which(player or "afplay")
        if (not fallback.audible or not self.python.is_file() or not (self.root / "model/config.json").is_file()
                or not (self.root / "reference.wav").is_file() or not self.player
                or shutil.which("ffmpeg") is None):
            raise ValueError("asurada_personality_voice_dependencies_unavailable")

    def start(self, job) -> _VoiceHandle:
        path = voice_cache_path(self.root, job.speak_text)
        metadata = job.metadata or {}
        if (metadata.get("personality") or {}).get("battle"):
            # Tactical calls have a short deadline. Keep their normal radio backend.
            return _VoiceHandle(self.fallback.start(job), local=False)
        urgent = (job.source_kind == "strategy_broadcast"
                  and strategy_speech_band(job.action_code) == 4)
        voiced = (metadata.get("optional_personality") or metadata.get("pit_follow_up")
                  or (metadata.get("personality") or {}).get("tone"))
        if not urgent and not voiced:
            return _VoiceHandle(self.fallback.start(job), local=False)
        style, shape = voice_delivery(job, urgent=urgent)
        cached = valid_voice_file(path, job.speak_text)
        if cached and not shape:
            handle = self._run([self.player, str(path)])
        elif urgent or has_wing_compensation(job):
            return _VoiceHandle(self.fallback.start(job), local=False)
        else:
            command = [str(self.python), str(self.worker), str(self.root), "--play", self.player]
            if shape:
                command.extend(("--delivery", style))
                if cached:
                    command.extend(("--source-wave", str(path)))
            handle = self._run(command, text=job.speak_text)
        job.metadata.update(render_voice="asurada_zh_reference_v1", render_delivery=style,
                            render_rate=DELIVERIES[style].lead_rate if shape else 1.0)
        if shape:
            job.metadata["render_follow_rate"] = DELIVERIES[style].follow_rate
        return handle

    @staticmethod
    def _run(command: list[str], *, text: str | None = None) -> _VoiceHandle:
        process = subprocess.Popen(command, stdin=subprocess.PIPE if text is not None else subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, start_new_session=True, text=True)
        if text is not None:
            try:
                with process.stdin:
                    process.stdin.write(text)
            except (OSError, ValueError):
                AsuradaPersonalityVoice._stop_process(process)
                process.wait(timeout=1)
                raise
        return _VoiceHandle(process, local=True)

    def is_active(self, handle: _VoiceHandle) -> bool:
        return handle.process.poll() is None if handle.local else self.fallback.is_active(handle.process)

    def completion_error(self, handle: _VoiceHandle) -> str | None:
        if not handle.local:
            return self.fallback.completion_error(handle.process)
        return None if handle.process.poll() == 0 else "asurada_personality_voice_unsuccessful"

    def stop(self, handle: _VoiceHandle) -> None:
        if handle.local:
            self._stop_process(handle.process)
        else:
            self.fallback.stop(handle.process)

    @staticmethod
    def _stop_process(process) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

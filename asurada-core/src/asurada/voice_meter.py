from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_VOICE_METER_PATH = Path(__file__).resolve().parents[2] / "runtime_logs" / "dashboard" / "voice_meter.json"
DEFAULT_VOICE_METER_SOCKET_HOST = "127.0.0.1"
DEFAULT_VOICE_METER_SOCKET_PORT = 8767
VOICE_METER_STALE_MS = 1_500


def resolve_voice_meter_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    override = str(os.getenv("ASURADA_VOICE_METER_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_VOICE_METER_PATH


def resolve_voice_meter_socket_target() -> tuple[str, int] | None:
    host = str(os.getenv("ASURADA_VOICE_METER_SOCKET_HOST") or DEFAULT_VOICE_METER_SOCKET_HOST).strip() or DEFAULT_VOICE_METER_SOCKET_HOST
    raw_port = str(os.getenv("ASURADA_VOICE_METER_SOCKET_PORT") or str(DEFAULT_VOICE_METER_SOCKET_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = DEFAULT_VOICE_METER_SOCKET_PORT
    if port <= 0:
        return None
    return host, port


def load_voice_meter_snapshot(path: Path | None = None, *, stale_after_ms: int = VOICE_METER_STALE_MS) -> dict[str, Any]:
    meter_path = resolve_voice_meter_path(path)
    if not meter_path.exists():
        return _empty_snapshot()
    try:
        payload = json.loads(meter_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_snapshot()
    snapshot = dict(payload or {})
    updated_at_ms = int(snapshot.get("updated_at_ms") or 0)
    now_ms = int(time.time() * 1000)
    if updated_at_ms <= 0 or now_ms - updated_at_ms > max(int(stale_after_ms), 1):
        return {
            **snapshot,
            "playback_active": False,
            "amplitude_level": 0.0,
            "amplitude_peak": 0.0,
            "beat_pulse": 0.0,
        }
    return {
        **_empty_snapshot(),
        **snapshot,
        "playback_active": bool(snapshot.get("playback_active", False)),
        "amplitude_level": _clamp_level(snapshot.get("amplitude_level")),
        "amplitude_peak": _clamp_level(snapshot.get("amplitude_peak")),
        "beat_pulse": _clamp_level(snapshot.get("beat_pulse")),
    }


@dataclass
class VoiceMeterWriter:
    path: Path | None = None
    min_write_interval_ms: int = 16

    def __post_init__(self) -> None:
        self.path = resolve_voice_meter_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._socket_target = resolve_voice_meter_socket_target()
        self._socket: socket.socket | None = None
        if self._socket_target is not None:
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            except OSError:
                self._socket = None
                self._socket_target = None
        self._last_write_at_ms = 0
        self._last_level = 0.0
        self._peak_level = 0.0

    def update(
        self,
        *,
        amplitude_level: float,
        amplitude_rms: int | None = None,
        beat_pulse: float = 0.0,
        playback_active: bool = True,
        audio_format: str | None = None,
        sample_rate_hz: int | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        level = _clamp_level(amplitude_level)
        now_ms = int(time.time() * 1000)
        if playback_active:
            self._peak_level = max(level, self._peak_level * 0.88)
        else:
            self._peak_level = 0.0
        if not force:
            if now_ms - self._last_write_at_ms < max(int(self.min_write_interval_ms), 1):
                if abs(level - self._last_level) < 0.035:
                    return
        snapshot = {
            "playback_active": bool(playback_active),
            "amplitude_level": level,
            "amplitude_peak": _clamp_level(self._peak_level),
            "amplitude_rms": (None if amplitude_rms is None else int(amplitude_rms)),
            "beat_pulse": _clamp_level(beat_pulse),
            "beat_updated_at_ms": now_ms if beat_pulse > 0.0 else 0,
            "audio_format": audio_format,
            "sample_rate_hz": (None if sample_rate_hz is None else int(sample_rate_hz)),
            "updated_at_ms": now_ms,
            "metadata": dict(metadata or {}),
        }
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.path)
        self._send_snapshot(snapshot)
        self._last_write_at_ms = now_ms
        self._last_level = level

    def clear(self, *, metadata: dict[str, Any] | None = None) -> None:
        self.update(amplitude_level=0.0, playback_active=False, metadata=metadata, force=True)

    def _send_snapshot(self, snapshot: dict[str, Any]) -> None:
        if self._socket is None or self._socket_target is None:
            return
        try:
            self._socket.sendto(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"), self._socket_target)
        except OSError:
            return


def _empty_snapshot() -> dict[str, Any]:
    return {
        "playback_active": False,
        "amplitude_level": 0.0,
        "amplitude_peak": 0.0,
        "amplitude_rms": None,
        "beat_pulse": 0.0,
        "beat_updated_at_ms": 0,
        "audio_format": None,
        "sample_rate_hz": None,
        "updated_at_ms": 0,
        "metadata": {},
    }


def _clamp_level(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0

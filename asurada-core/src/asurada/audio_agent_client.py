from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from .llm_explainer import LlmExplainerRequest, LlmExplainerResult
from .voice_sidecar_protocol import (
    AsrTranscribeRequest,
    AsrTranscribeResponse,
    TtsAudioFrame,
    TtsRenderRequest,
    TtsRenderResponse,
    TtsStreamEnd,
    TtsStreamStart,
    VoiceSidecarHealth,
    build_asr_transcribe_request_envelope,
    build_explainer_request_envelope,
    build_tts_render_request_envelope,
    parse_asr_transcribe_response_envelope,
    parse_tts_audio_frame_envelope,
    parse_explainer_result_envelope,
    parse_tts_render_response_envelope,
    parse_tts_stream_end_envelope,
    parse_tts_stream_start_envelope,
)
from .voice_meter import VoiceMeterWriter


class VoiceSidecarClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceSidecarClientConfig:
    base_url: str
    timeout_ms: int = 2_500


@dataclass(frozen=True)
class AudioPlaybackResult:
    status: str
    player_binary: str | None
    audio_format: str
    audio_bytes: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "player_binary": self.player_binary,
            "audio_format": self.audio_format,
            "audio_bytes": self.audio_bytes,
            "metadata": dict(self.metadata),
        }


class _VoiceMeterPlaybackStreamer:
    def __init__(
        self,
        *,
        writer: VoiceMeterWriter,
        audio_format: str,
        sample_rate_hz: int,
        base_metadata: dict[str, Any] | None = None,
        window_ms: int = 20,
        startup_delay_ms: int = 0,
    ) -> None:
        self.writer = writer
        self.audio_format = audio_format
        self.sample_rate_hz = max(int(sample_rate_hz), 1)
        self.base_metadata = dict(base_metadata or {})
        self.window_ms = max(int(window_ms), 10)
        self.startup_delay_ms = max(int(startup_delay_ms), 0)
        self._queue: queue.Queue[tuple[int, int, dict[str, Any]] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="voice-meter-streamer", daemon=True)
        self._started = False
        self._prev_level = 0.0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.writer.update(
            amplitude_level=0.0,
            playback_active=True,
            audio_format=self.audio_format,
            sample_rate_hz=self.sample_rate_hz,
            metadata=self.base_metadata,
            force=True,
        )
        self._thread.start()

    def push_pcm_chunk(self, chunk: bytes, *, metadata: dict[str, Any] | None = None) -> None:
        if not chunk:
            return
        if not self._started:
            self.start()
        merged_metadata = {
            **self.base_metadata,
            **dict(metadata or {}),
        }
        for rms, duration_ms in _iter_pcm_windows(chunk, sample_rate_hz=self.sample_rate_hz, window_ms=self.window_ms):
            self._queue.put((rms, duration_ms, merged_metadata))

    def finish(self, *, metadata: dict[str, Any] | None = None) -> None:
        if not self._started:
            self.writer.clear(metadata=metadata)
            return
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        self.writer.clear(metadata=metadata)

    def _run(self) -> None:
        first_window = True
        while True:
            item = self._queue.get()
            if item is None:
                return
            rms, duration_ms, metadata = item
            if first_window and self.startup_delay_ms > 0:
                time.sleep(self.startup_delay_ms / 1000.0)
                first_window = False
            level = _rms_to_level(rms)
            beat_pulse = _detect_onset(level=level, prev_level=self._prev_level)
            self._prev_level = level
            self.writer.update(
                amplitude_level=level,
                amplitude_rms=rms,
                beat_pulse=beat_pulse,
                playback_active=True,
                audio_format=self.audio_format,
                sample_rate_hz=self.sample_rate_hz,
                metadata=metadata,
                force=True,
            )
            time.sleep(max(duration_ms, 1) / 1000.0)


class VoiceSidecarClient:
    def __init__(self, config: VoiceSidecarClientConfig | None = None) -> None:
        self.config = config or self.from_env().config
        self.voice_meter = VoiceMeterWriter()

    @classmethod
    def from_env(cls) -> "VoiceSidecarClient":
        base_url = str(os.getenv("ASURADA_VOICE_SIDECAR_BASE_URL") or "http://127.0.0.1:8788").strip()
        timeout_ms = int(os.getenv("ASURADA_VOICE_SIDECAR_TIMEOUT_MS") or "2500")
        return cls(VoiceSidecarClientConfig(base_url=base_url.rstrip("/"), timeout_ms=max(timeout_ms, 1)))

    def healthz(self) -> VoiceSidecarHealth:
        payload = self._request_json("GET", "/healthz", None, timeout_ms=self.config.timeout_ms)
        body = dict(payload.get("payload") or {})
        return VoiceSidecarHealth(
            status=str(body.get("status") or ""),
            sidecar_name=str(body.get("sidecar_name") or ""),
            llm_backend_name=str(body.get("llm_backend_name") or ""),
            tts_available=bool(body.get("tts_available")),
            metadata=dict(body.get("metadata") or {}),
        )

    def explain(self, *, request: LlmExplainerRequest, timeout_ms: int | None = None) -> LlmExplainerResult:
        payload = self._request_json(
            "POST",
            "/v1/explainer",
            build_explainer_request_envelope(request).to_dict(),
            timeout_ms=timeout_ms or request.timeout_ms or self.config.timeout_ms,
        )
        return parse_explainer_result_envelope(payload)

    def transcribe_asr(self, *, request: AsrTranscribeRequest, timeout_ms: int | None = None) -> AsrTranscribeResponse:
        payload = self._request_json(
            "POST",
            "/v1/asr/transcribe",
            build_asr_transcribe_request_envelope(request).to_dict(),
            timeout_ms=timeout_ms or self.config.timeout_ms,
        )
        return parse_asr_transcribe_response_envelope(payload)

    def render_tts(self, *, request: TtsRenderRequest, timeout_ms: int | None = None) -> TtsRenderResponse:
        payload = self._request_json(
            "POST",
            "/v1/tts/render",
            build_tts_render_request_envelope(request).to_dict(),
            timeout_ms=timeout_ms or self.config.timeout_ms,
        )
        return parse_tts_render_response_envelope(payload)

    def play_tts(
        self,
        *,
        request: TtsRenderRequest,
        timeout_ms: int | None = None,
    ) -> AudioPlaybackResult:
        return self.play_streamed_tts(request=request, timeout_ms=timeout_ms)

    def play_streamed_tts(
        self,
        *,
        request: TtsRenderRequest,
        timeout_ms: int | None = None,
    ) -> AudioPlaybackResult:
        req = urllib_request.Request(
            url=f"{self.config.base_url}/v1/tts/stream",
            data=json.dumps(build_tts_render_request_envelope(request).to_dict(), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout_s = max(float(timeout_ms or self.config.timeout_ms), 1.0) / 1000.0
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as response:
                start: TtsStreamStart | None = None
                end: TtsStreamEnd | None = None
                chunks: list[bytes] = []
                total_audio_bytes = 0
                stream_proc: subprocess.Popen[bytes] | None = None
                stream_player_binary: str | None = None
                stream_player_args: tuple[str, ...] = ()
                stream_failed = False
                meter_streamer: _VoiceMeterPlaybackStreamer | None = None
                stream_preroll_ms = 0

                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    message_type = str(payload.get("message_type") or "")
                    if message_type == "tts_stream_start":
                        start = parse_tts_stream_start_envelope(payload)
                        if _is_pcm_audio_format(start.audio_format):
                            meter_streamer = _VoiceMeterPlaybackStreamer(
                                writer=self.voice_meter,
                                audio_format=start.audio_format,
                                sample_rate_hz=start.sample_rate_hz,
                                base_metadata=dict(start.metadata),
                                window_ms=20,
                                startup_delay_ms=_resolve_voice_meter_startup_delay_ms(),
                            )
                            meter_streamer.start()
                            stream_preroll_ms = _resolve_stream_preroll_ms()
                        else:
                            self.voice_meter.update(
                                amplitude_level=0.0,
                                playback_active=True,
                                audio_format=start.audio_format,
                                sample_rate_hz=start.sample_rate_hz,
                                metadata=dict(start.metadata),
                                force=True,
                            )
                        stream_player_binary, stream_player_args = _resolve_stream_audio_player(
                            start.audio_format,
                            sample_rate_hz=start.sample_rate_hz,
                        )
                        if stream_player_binary:
                            stream_proc = subprocess.Popen(
                                [stream_player_binary, *stream_player_args],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            preroll = _build_stream_preroll_bytes(
                                audio_format=start.audio_format,
                                sample_rate_hz=start.sample_rate_hz,
                                preroll_ms=stream_preroll_ms,
                            )
                            if preroll and stream_proc.stdin is not None:
                                try:
                                    stream_proc.stdin.write(preroll)
                                    stream_proc.stdin.flush()
                                except BrokenPipeError:
                                    stream_failed = True
                                if meter_streamer is not None:
                                    meter_streamer.push_pcm_chunk(
                                        preroll,
                                        metadata={
                                            **dict(start.metadata),
                                            "stream_player_binary": stream_player_binary,
                                            "stream_preroll_ms": stream_preroll_ms,
                                            "preroll": True,
                                        },
                                    )
                    elif message_type == "tts_audio_frame":
                        frame = parse_tts_audio_frame_envelope(payload)
                        chunk = base64.b64decode(frame.audio_base64)
                        chunks.append(chunk)
                        total_audio_bytes += len(chunk)
                        wrote_to_stream_player = False
                        if stream_proc is not None and stream_proc.stdin is not None and not stream_failed:
                            try:
                                stream_proc.stdin.write(chunk)
                                stream_proc.stdin.flush()
                                wrote_to_stream_player = True
                            except BrokenPipeError:
                                stream_failed = True
                        if meter_streamer is not None:
                            meter_streamer.push_pcm_chunk(
                                chunk,
                                metadata={
                                    **dict(frame.metadata),
                                    "sequence_id": frame.sequence_id,
                                    "stream_player_binary": stream_player_binary,
                                    "stream_player_written": wrote_to_stream_player,
                                },
                            )
                        elif start is not None:
                            rms = _pcm_chunk_rms(chunk) if _is_pcm_audio_format(start.audio_format) else None
                            amplitude_level = _rms_to_level(rms)
                            self.voice_meter.update(
                                amplitude_level=amplitude_level,
                                amplitude_rms=rms,
                                playback_active=True,
                                audio_format=start.audio_format,
                                sample_rate_hz=start.sample_rate_hz,
                                metadata={
                                    **dict(start.metadata),
                                    **dict(frame.metadata),
                                    "sequence_id": frame.sequence_id,
                                    "stream_player_binary": stream_player_binary,
                                    "stream_player_written": wrote_to_stream_player,
                                },
                            )
                    elif message_type == "tts_stream_end":
                        end = parse_tts_stream_end_envelope(payload)

                if start is None or end is None:
                    raise VoiceSidecarClientError("voice_sidecar_stream_incomplete")

                if stream_proc is not None and stream_proc.stdin is not None:
                    try:
                        stream_proc.stdin.close()
                    except BrokenPipeError:
                        stream_failed = True
                    return_code = stream_proc.wait()
                    if return_code != 0:
                        stream_failed = True

                if (
                    not stream_failed
                    and stream_proc is not None
                    and stream_player_binary is not None
                    and end.status == "completed"
                ):
                    clear_metadata = {
                        **dict(start.metadata),
                        **dict(end.metadata),
                        "stream_total_frames": end.total_frames,
                        "stream_total_audio_bytes": end.total_audio_bytes,
                        "playback_mode": "stream",
                        "stream_player_binary": stream_player_binary,
                        "stream_preroll_ms": stream_preroll_ms,
                    }
                    if meter_streamer is not None:
                        meter_streamer.finish(metadata=clear_metadata)
                    else:
                        self.voice_meter.clear(metadata=clear_metadata)
                    return AudioPlaybackResult(
                        status="played",
                        player_binary=stream_player_binary,
                        audio_format=start.audio_format,
                        audio_bytes=total_audio_bytes,
                        metadata={
                            **dict(start.metadata),
                            **dict(end.metadata),
                            "stream_total_frames": end.total_frames,
                            "stream_total_audio_bytes": end.total_audio_bytes,
                            "playback_mode": "stream",
                            "stream_preroll_ms": stream_preroll_ms,
                        },
                    )

                buffered = self._build_stream_response(start=start, end=end, chunks=chunks)
                playback = self.play_rendered_tts(response=buffered)
                if meter_streamer is not None:
                    meter_streamer.finish(
                        metadata={
                            **dict(playback.metadata),
                            "playback_mode": "buffered_fallback",
                        }
                    )
                else:
                    self.voice_meter.clear(
                        metadata={
                            **dict(playback.metadata),
                            "playback_mode": "buffered_fallback",
                        }
                    )
                return AudioPlaybackResult(
                    status=playback.status,
                    player_binary=playback.player_binary,
                    audio_format=playback.audio_format,
                    audio_bytes=playback.audio_bytes,
                    metadata={
                        **dict(playback.metadata),
                        "playback_mode": "buffered_fallback",
                    },
                )
        except urllib_error.HTTPError as exc:
            self.voice_meter.clear(metadata={"reason": "stream_http_error"})
            detail = exc.read().decode("utf-8", errors="replace")
            raise VoiceSidecarClientError(f"voice_sidecar_stream_http_error:{exc.code}:{detail}") from exc
        except urllib_error.URLError as exc:
            self.voice_meter.clear(metadata={"reason": "stream_network_error"})
            raise VoiceSidecarClientError(f"voice_sidecar_stream_network_error:{exc.reason}") from exc
        except Exception:
            self.voice_meter.clear(metadata={"reason": "stream_unknown_error"})
            raise

    def stream_tts(
        self,
        *,
        request: TtsRenderRequest,
        timeout_ms: int | None = None,
    ) -> tuple[TtsStreamStart, list[TtsAudioFrame], TtsStreamEnd]:
        req = urllib_request.Request(
            url=f"{self.config.base_url}/v1/tts/stream",
            data=json.dumps(build_tts_render_request_envelope(request).to_dict(), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout_s = max(float(timeout_ms or self.config.timeout_ms), 1.0) / 1000.0
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as response:
                start: TtsStreamStart | None = None
                frames: list[TtsAudioFrame] = []
                end: TtsStreamEnd | None = None
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    message_type = str(payload.get("message_type") or "")
                    if message_type == "tts_stream_start":
                        start = parse_tts_stream_start_envelope(payload)
                    elif message_type == "tts_audio_frame":
                        frames.append(parse_tts_audio_frame_envelope(payload))
                    elif message_type == "tts_stream_end":
                        end = parse_tts_stream_end_envelope(payload)
                if start is None or end is None:
                    raise VoiceSidecarClientError("voice_sidecar_stream_incomplete")
                return start, frames, end
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VoiceSidecarClientError(f"voice_sidecar_stream_http_error:{exc.code}:{detail}") from exc
        except urllib_error.URLError as exc:
            raise VoiceSidecarClientError(f"voice_sidecar_stream_network_error:{exc.reason}") from exc

    def collect_streamed_tts(
        self,
        *,
        request: TtsRenderRequest,
        timeout_ms: int | None = None,
    ) -> TtsRenderResponse:
        start, frames, end = self.stream_tts(request=request, timeout_ms=timeout_ms)
        return self._build_stream_response(
            start=start,
            end=end,
            chunks=[base64.b64decode(frame.audio_base64) for frame in frames],
        )

    def play_rendered_tts(self, *, response: TtsRenderResponse) -> AudioPlaybackResult:
        if response.status != "completed" or not response.audio_base64:
            self.voice_meter.clear(metadata={"reason": "tts_not_playable"})
            return AudioPlaybackResult(
                status=response.status,
                player_binary=None,
                audio_format=response.audio_format,
                audio_bytes=0,
                metadata={"reason": "tts_not_playable", **dict(response.metadata)},
            )
        audio_bytes = base64.b64decode(response.audio_base64)
        audio_format = response.audio_format
        if _is_pcm_audio_format(audio_format):
            rms = _pcm_chunk_rms(audio_bytes)
            self.voice_meter.update(
                amplitude_level=_rms_to_level(rms),
                amplitude_rms=rms,
                playback_active=True,
                audio_format=audio_format,
                sample_rate_hz=response.sample_rate_hz,
                metadata={"playback_mode": "buffered"},
                force=True,
            )
            audio_bytes = _wrap_pcm_as_wav(audio_bytes, sample_rate_hz=response.sample_rate_hz)
            audio_format = "wav"
        player_binary, player_args = _resolve_audio_player()
        if not player_binary:
            self.voice_meter.clear(metadata={"reason": "audio_player_unavailable"})
            return AudioPlaybackResult(
                status="unsupported",
                player_binary=None,
                audio_format=audio_format,
                audio_bytes=len(audio_bytes),
                metadata={"reason": "audio_player_unavailable", **dict(response.metadata)},
            )
        suffix = _audio_suffix(audio_format)
        with tempfile.TemporaryDirectory(prefix="asurada-agent-play-") as tmpdir:
            audio_path = Path(tmpdir) / f"sidecar_tts{suffix}"
            audio_path.write_bytes(audio_bytes)
            try:
                subprocess.run(
                    [player_binary, *player_args, str(audio_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            finally:
                self.voice_meter.clear(metadata={"player_binary": player_binary, "playback_mode": "buffered"})
        return AudioPlaybackResult(
            status="played",
            player_binary=player_binary,
            audio_format=audio_format,
            audio_bytes=len(audio_bytes),
            metadata=dict(response.metadata),
        )

    def _build_stream_response(
        self,
        *,
        start: TtsStreamStart,
        end: TtsStreamEnd,
        chunks: list[bytes],
    ) -> TtsRenderResponse:
        audio_bytes = b"".join(chunks)
        return TtsRenderResponse(
            status=end.status or start.status,
            audio_base64=(None if not audio_bytes else base64.b64encode(audio_bytes).decode("ascii")),
            audio_format=start.audio_format,
            sample_rate_hz=start.sample_rate_hz,
            metadata={
                **dict(start.metadata),
                **dict(end.metadata),
                "stream_total_frames": end.total_frames,
                "stream_total_audio_bytes": end.total_audio_bytes,
            },
        )

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            url=f"{self.config.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        timeout_s = max(float(timeout_ms), 1.0) / 1000.0
        try:
            with urllib_request.urlopen(req, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VoiceSidecarClientError(f"voice_sidecar_http_error:{exc.code}:{detail}") from exc
        except urllib_error.URLError as exc:
            raise VoiceSidecarClientError(f"voice_sidecar_network_error:{exc.reason}") from exc


def _resolve_audio_player() -> tuple[str | None, tuple[str, ...]]:
    forced_binary = str(os.getenv("ASURADA_AUDIO_AGENT_PLAYER_BINARY") or "").strip()
    forced_args = tuple(shlex.split(str(os.getenv("ASURADA_AUDIO_AGENT_PLAYER_ARGS") or "").strip()))
    if forced_binary:
        resolved = forced_binary if os.path.isabs(forced_binary) else (shutil.which(forced_binary) or forced_binary)
        return resolved, forced_args
    if sys.platform == "darwin":
        afplay = shutil.which("afplay")
        if afplay:
            return afplay, ()
    ffplay = shutil.which("ffplay")
    if ffplay:
        return ffplay, ("-autoexit", "-nodisp", "-loglevel", "quiet")
    return None, ()


def _resolve_stream_audio_player(audio_format: str, *, sample_rate_hz: int) -> tuple[str | None, tuple[str, ...]]:
    forced_binary = str(os.getenv("ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY") or "").strip()
    forced_args = tuple(shlex.split(str(os.getenv("ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS") or "").strip()))
    if forced_binary:
        resolved = forced_binary if os.path.isabs(forced_binary) else (shutil.which(forced_binary) or forced_binary)
        return resolved, forced_args
    ffplay = shutil.which("ffplay")
    lowered = str(audio_format or "").strip().lower()
    if ffplay and lowered in {"wav", "wave"}:
        return ffplay, (
            "-autoexit",
            "-nodisp",
            "-loglevel",
            "quiet",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-sync",
            "audio",
            "-i",
            "pipe:0",
        )
    if ffplay and lowered in {"pcm_s16le", "s16le", "pcm"}:
        return ffplay, (
            "-autoexit",
            "-nodisp",
            "-loglevel",
            "quiet",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-sync",
            "audio",
            "-f",
            "s16le",
            "-ar",
            str(max(int(sample_rate_hz), 1)),
            "-i",
            "pipe:0",
        )
    return None, ()


def _resolve_voice_meter_startup_delay_ms() -> int:
    value = str(os.getenv("ASURADA_VOICE_METER_STARTUP_DELAY_MS") or "").strip()
    if not value:
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


def _resolve_stream_preroll_ms() -> int:
    value = str(os.getenv("ASURADA_AUDIO_AGENT_STREAM_PREROLL_MS") or "").strip()
    if not value:
        return 120
    try:
        return max(int(value), 0)
    except ValueError:
        return 120


def _audio_suffix(audio_format: str) -> str:
    lowered = str(audio_format or "").strip().lower()
    if lowered in {"wav", "wave"}:
        return ".wav"
    if lowered in {"aiff", "aif"}:
        return ".aiff"
    return ".bin"


def _is_pcm_audio_format(audio_format: str) -> bool:
    lowered = str(audio_format or "").strip().lower()
    return lowered in {"pcm_s16le", "s16le", "pcm"}


def _build_stream_preroll_bytes(*, audio_format: str, sample_rate_hz: int, preroll_ms: int) -> bytes:
    if preroll_ms <= 0 or not _is_pcm_audio_format(audio_format):
        return b""
    sample_count = max(int(round(max(sample_rate_hz, 1) * (preroll_ms / 1000.0))), 1)
    return b"\x00\x00" * sample_count


def _wrap_pcm_as_wav(raw_audio: bytes, *, sample_rate_hz: int) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with wave.open(str(temp_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(max(int(sample_rate_hz), 1))
            wav_file.writeframes(raw_audio)
        return temp_path.read_bytes()
    finally:
        temp_path.unlink(missing_ok=True)


def _iter_pcm_windows(raw_audio: bytes, *, sample_rate_hz: int, window_ms: int) -> list[tuple[int, int]]:
    bytes_per_sample = 2
    samples_per_window = max(int(sample_rate_hz * max(window_ms, 1) / 1000), 1)
    window_bytes = samples_per_window * bytes_per_sample
    windows: list[tuple[int, int]] = []
    for offset in range(0, len(raw_audio), window_bytes):
        window = raw_audio[offset:offset + window_bytes]
        if not window:
            continue
        sample_count = len(window) // bytes_per_sample
        if sample_count <= 0:
            continue
        duration_ms = max(int(round(sample_count / max(sample_rate_hz, 1) * 1000)), 1)
        windows.append((_pcm_chunk_rms(window), duration_ms))
    return windows


def _pcm_chunk_rms(raw_audio: bytes) -> int:
    sample_count = len(raw_audio) // 2
    if sample_count <= 0:
        return 0
    total = 0.0
    limit = sample_count * 2
    for index in range(0, limit, 2):
        sample = int.from_bytes(raw_audio[index:index + 2], byteorder="little", signed=True)
        total += float(sample * sample)
    return int(math.sqrt(total / sample_count))


def _rms_to_level(rms: int | None) -> float:
    if rms is None or rms <= 0:
        return 0.0
    normalized = max(0.0, min(float(rms) / 3400.0, 1.0))
    return max(0.0, min(pow(normalized, 0.82), 1.0))


def _detect_onset(*, level: float, prev_level: float) -> float:
    current = max(0.0, min(level, 1.0))
    previous = max(0.0, min(prev_level, 1.0))
    rise = current - previous
    if current < 0.16:
        return 0.0
    if rise < 0.07:
        return 0.0
    strength = min((rise * 3.6) + (current * 0.35), 1.0)
    return max(0.0, strength)

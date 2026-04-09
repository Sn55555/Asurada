from __future__ import annotations

import base64
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import wave
from typing import Any, Iterable, Protocol

from .persona_registry import get_voice_profile
from .tts_backends import PiperBackend
from .voice_sidecar_protocol import TtsRenderRequest, TtsRenderResponse


@dataclass(frozen=True)
class TtsStreamRender:
    status: str
    audio_format: str
    sample_rate_hz: int
    metadata: dict[str, Any]
    chunks: tuple[bytes, ...]
    total_audio_bytes: int
    chunk_iter: Iterable[bytes] | None = None

    def iter_chunks(self) -> Iterable[bytes]:
        return self.chunk_iter if self.chunk_iter is not None else self.chunks


class VoiceSidecarTtsRenderer(Protocol):
    name: str

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        ...

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        ...


class MacOSSaySidecarTtsRenderer:
    name = "macos_say_sidecar_tts_renderer"

    def __init__(
        self,
        *,
        say_binary: str | None = None,
        afconvert_binary: str | None = None,
        voice_name: str | None = None,
        base_wpm: int = 180,
    ) -> None:
        self.say_binary = say_binary or shutil.which("say") or "/usr/bin/say"
        self.afconvert_binary = afconvert_binary or shutil.which("afconvert") or "/usr/bin/afconvert"
        self.voice_name = voice_name or None
        self.base_wpm = base_wpm

    @classmethod
    def from_env(cls) -> "MacOSSaySidecarTtsRenderer":
        return cls(
            say_binary=os.getenv("ASURADA_SAY_BINARY"),
            afconvert_binary=os.getenv("ASURADA_AFCONVERT_BINARY"),
            voice_name=os.getenv("ASURADA_VOICE_SIDECAR_SAY_VOICE"),
            base_wpm=int(os.getenv("ASURADA_VOICE_SIDECAR_SAY_BASE_WPM") or "180"),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return sys.platform == "darwin" and shutil.which("say") is not None and shutil.which("afconvert") is not None

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        audio_bytes, metadata = self._synthesize_wav(request)
        return TtsRenderResponse(
            status="completed",
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata=metadata,
        )

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        wav_bytes, metadata = self._synthesize_wav(request)
        if _is_pcm_stream_format(request.audio_format):
            pcm_bytes = _extract_wav_pcm_bytes(wav_bytes)
            return TtsStreamRender(
                status="completed",
                audio_format="pcm_s16le",
                sample_rate_hz=request.sample_rate_hz,
                metadata=metadata,
                chunks=split_audio_chunks(pcm_bytes, frame_size_bytes=frame_size_bytes),
                total_audio_bytes=len(pcm_bytes),
            )
        return stream_render_from_response(
            TtsRenderResponse(
                status="completed",
                audio_base64=base64.b64encode(wav_bytes).decode("ascii"),
                audio_format="wav",
                sample_rate_hz=request.sample_rate_hz,
                metadata=metadata,
            ),
            frame_size_bytes=frame_size_bytes,
        )

    def _synthesize_wav(self, request: TtsRenderRequest) -> tuple[bytes, dict[str, Any]]:
        voice_profile = get_voice_profile(request.voice_profile_id)
        words_per_minute = max(int(round(self.base_wpm * voice_profile.speaking_rate)), 90)
        voice_name = self.voice_name or voice_profile.macos_say_voice_name
        with tempfile.TemporaryDirectory(prefix="asurada-sidecar-tts-") as tmpdir:
            aiff_path = Path(tmpdir) / "speech.aiff"
            wav_path = Path(tmpdir) / "speech.wav"
            say_cmd = [self.say_binary]
            if voice_name:
                say_cmd.extend(["-v", voice_name])
            say_cmd.extend(["-r", str(words_per_minute), "-o", str(aiff_path), request.text])
            subprocess.run(
                say_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            subprocess.run(
                [
                    self.afconvert_binary,
                    "-f",
                    "WAVE",
                    "-d",
                    f"LEI16@{request.sample_rate_hz}",
                    "-c",
                    "1",
                    str(aiff_path),
                    str(wav_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            audio_bytes = wav_path.read_bytes()
        return audio_bytes, {
            "renderer": self.name,
            "voice_profile_id": voice_profile.voice_profile_id,
            "style_name": voice_profile.style_name,
            "voice_name": voice_name,
            "words_per_minute": words_per_minute,
        }


@dataclass(frozen=True)
class PiperSidecarTtsRenderer:
    name: str = "piper_sidecar_tts_renderer"

    @classmethod
    def from_env(cls) -> "PiperSidecarTtsRenderer":
        if not PiperBackend.env_ready():
            raise ValueError("piper_sidecar_renderer_not_ready")
        return cls()

    @classmethod
    def env_ready(cls) -> bool:
        return PiperBackend.env_ready()

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        audio_bytes, metadata = self._synthesize_wav(request)
        return TtsRenderResponse(
            status="completed",
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata=metadata,
        )

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        wav_bytes, metadata = self._synthesize_wav(request)
        if _is_pcm_stream_format(request.audio_format):
            pcm_bytes = _extract_wav_pcm_bytes(wav_bytes)
            return TtsStreamRender(
                status="completed",
                audio_format="pcm_s16le",
                sample_rate_hz=request.sample_rate_hz,
                metadata=metadata,
                chunks=split_audio_chunks(pcm_bytes, frame_size_bytes=frame_size_bytes),
                total_audio_bytes=len(pcm_bytes),
            )
        return stream_render_from_response(
            TtsRenderResponse(
                status="completed",
                audio_base64=base64.b64encode(wav_bytes).decode("ascii"),
                audio_format="wav",
                sample_rate_hz=request.sample_rate_hz,
                metadata=metadata,
            ),
            frame_size_bytes=frame_size_bytes,
        )

    def _synthesize_wav(self, request: TtsRenderRequest) -> tuple[bytes, dict[str, Any]]:
        cfg = PiperBackend.from_env().config
        with tempfile.TemporaryDirectory(prefix="asurada-sidecar-piper-") as tmpdir:
            wav_path = Path(tmpdir) / "speech.wav"
            synth_cmd = [cfg.piper_binary, "--model", cfg.model_path]
            if cfg.config_path:
                synth_cmd.extend(["--config", cfg.config_path])
            synth_cmd.extend(["--output_file", str(wav_path)])
            subprocess.run(
                synth_cmd,
                input=request.text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            audio_bytes = wav_path.read_bytes()
        return audio_bytes, {
            "renderer": self.name,
            "voice_profile_id": request.voice_profile_id,
        }


@dataclass(frozen=True)
class DoubaoStreamingHttpSidecarTtsRenderer:
    stream_url: str
    app_id: str
    access_key: str
    resource_id: str
    default_speaker: str
    user_id: str = "asurada-sidecar"
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 45.0
    request_format: str = "pcm"
    name: str = "doubao_streaming_http_sidecar_tts_renderer"

    @classmethod
    def from_env(cls) -> "DoubaoStreamingHttpSidecarTtsRenderer":
        app_id = _env_first("ASURADA_DOUBAO_TTS_APP_ID", "ASURADA_VOLC_TTS_APP_ID")
        access_key = _env_first(
            "ASURADA_DOUBAO_TTS_ACCESS_KEY",
            "ASURADA_DOUBAO_TTS_API_KEY",
            "ASURADA_DOUBAO_TTS_TOKEN",
            "ASURADA_VOLC_TTS_ACCESS_KEY",
            "ASURADA_VOLC_TTS_API_KEY",
            "ASURADA_VOLC_TTS_TOKEN",
        )
        if not app_id:
            raise ValueError("ASURADA_DOUBAO_TTS_APP_ID or ASURADA_VOLC_TTS_APP_ID is required")
        if not access_key:
            raise ValueError("ASURADA_DOUBAO_TTS_ACCESS_KEY or ASURADA_VOLC_TTS_ACCESS_KEY is required")
        stream_url = _env_first(
            "ASURADA_DOUBAO_TTS_STREAM_URL",
            "ASURADA_VOLC_TTS_STREAM_URL",
        ) or "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
        resource_id = _env_first(
            "ASURADA_DOUBAO_TTS_RESOURCE_ID",
            "ASURADA_VOLC_TTS_RESOURCE_ID",
        ) or "volc.service_type.10029"
        speaker = _env_first(
            "ASURADA_DOUBAO_TTS_SPEAKER",
            "ASURADA_VOLC_TTS_SPEAKER",
        ) or "zh_male_ahu_conversation_wvae_bigtts"
        user_id = _env_first(
            "ASURADA_DOUBAO_TTS_USER_ID",
            "ASURADA_VOLC_TTS_USER_ID",
        ) or "asurada-sidecar"
        return cls(
            stream_url=stream_url,
            app_id=app_id,
            access_key=access_key,
            resource_id=resource_id,
            default_speaker=speaker,
            user_id=user_id,
            connect_timeout_s=_env_float("ASURADA_DOUBAO_TTS_CONNECT_TIMEOUT_S", default=10.0),
            read_timeout_s=_env_float("ASURADA_DOUBAO_TTS_READ_TIMEOUT_S", default=45.0),
            request_format=_env_first("ASURADA_DOUBAO_TTS_AUDIO_FORMAT", "ASURADA_VOLC_TTS_AUDIO_FORMAT") or "pcm",
        )

    @classmethod
    def env_ready(cls) -> bool:
        return bool(
            importlib.util.find_spec("requests")
            and _env_first("ASURADA_DOUBAO_TTS_APP_ID", "ASURADA_VOLC_TTS_APP_ID")
            and _env_first(
                "ASURADA_DOUBAO_TTS_ACCESS_KEY",
                "ASURADA_DOUBAO_TTS_API_KEY",
                "ASURADA_DOUBAO_TTS_TOKEN",
                "ASURADA_VOLC_TTS_ACCESS_KEY",
                "ASURADA_VOLC_TTS_API_KEY",
                "ASURADA_VOLC_TTS_TOKEN",
            )
        )

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        stream_render = self.stream_render(request, frame_size_bytes=8192)
        pcm_bytes = b"".join(tuple(stream_render.iter_chunks()))
        wav_bytes = _wrap_pcm_as_wav(pcm_bytes, sample_rate_hz=request.sample_rate_hz)
        return TtsRenderResponse(
            status=stream_render.status,
            audio_base64=(None if not wav_bytes else base64.b64encode(wav_bytes).decode("ascii")),
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata=dict(stream_render.metadata),
        )

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        voice_profile = get_voice_profile(request.voice_profile_id)
        speaker = self._resolve_speaker(voice_profile)
        return TtsStreamRender(
            status="completed",
            audio_format="pcm_s16le",
            sample_rate_hz=request.sample_rate_hz,
            metadata={
                "renderer": self.name,
                "provider": "doubao_tts_http_sse",
                "stream_url": self.stream_url,
                "resource_id": self.resource_id,
                "speaker": speaker,
                "request_audio_format": self.request_format,
                "voice_profile_id": request.voice_profile_id,
            },
            chunks=(),
            total_audio_bytes=0,
            chunk_iter=self._iter_pcm_chunks(request=request, frame_size_bytes=frame_size_bytes),
        )

    def _iter_pcm_chunks(self, *, request: TtsRenderRequest, frame_size_bytes: int) -> Iterable[bytes]:
        import requests

        voice_profile = get_voice_profile(request.voice_profile_id)
        speaker = self._resolve_speaker(voice_profile)
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "X-Api-App-ID": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": f"asurada-tts-{uuid.uuid4().hex}",
        }
        payload = {
            "user": {"uid": self.user_id},
            "req_params": {
                "text": request.text,
                "speaker": speaker,
                "voice_type": speaker,
                "audio_params": {
                    "format": self.request_format,
                    "sample_rate": request.sample_rate_hz,
                },
            },
        }
        with requests.post(
            self.stream_url,
            headers=headers,
            json=payload,
            timeout=(self.connect_timeout_s, self.read_timeout_s),
            stream=True,
        ) as response:
            response.raise_for_status()
            for event_payload in _iter_sse_json_events(response.iter_lines(decode_unicode=False)):
                event_code = int(event_payload.get("event") or event_payload.get("_sse_event") or 0)
                provider_code = int(event_payload.get("code") or 0)
                allowed_codes = {0}
                if event_code == 152:
                    allowed_codes.add(20_000_000)
                if provider_code not in allowed_codes:
                    raise RuntimeError(
                        f"doubao_tts_http_error:{event_payload.get('code')}:{event_payload.get('message')}"
                    )
                if event_code in {350, 352}:
                    audio_b64 = str(event_payload.get("data") or "")
                    if not audio_b64:
                        continue
                    decoded = base64.b64decode(audio_b64)
                    yield from split_audio_chunks(decoded, frame_size_bytes=frame_size_bytes)
                    continue
                if event_code in {152, 351}:
                    if event_code == 351:
                        continue
                    break
                if event_code == 153:
                    raise RuntimeError(
                        f"doubao_tts_http_error:{event_payload.get('code')}:{event_payload.get('message')}"
                    )

    def _resolve_speaker(self, voice_profile) -> str:
        env_speaker = _env_first(
            "ASURADA_DOUBAO_TTS_SPEAKER",
            "ASURADA_VOLC_TTS_SPEAKER",
        )
        return env_speaker or voice_profile.doubao_tts_speaker or self.default_speaker


def stream_render_from_response(response: TtsRenderResponse, *, frame_size_bytes: int) -> TtsStreamRender:
    raw_audio = b"" if not response.audio_base64 else base64.b64decode(response.audio_base64)
    chunks = split_audio_chunks(raw_audio, frame_size_bytes=frame_size_bytes)
    return TtsStreamRender(
        status=response.status,
        audio_format=response.audio_format,
        sample_rate_hz=response.sample_rate_hz,
        metadata=dict(response.metadata),
        chunks=chunks,
        total_audio_bytes=len(raw_audio),
    )


def split_audio_chunks(raw_audio: bytes, *, frame_size_bytes: int) -> tuple[bytes, ...]:
    frame_size = max(int(frame_size_bytes), 512)
    return tuple(raw_audio[index : index + frame_size] for index in range(0, len(raw_audio), frame_size))


def _is_pcm_stream_format(audio_format: str) -> bool:
    lowered = str(audio_format or "").strip().lower()
    return lowered in {"pcm_s16le", "s16le", "pcm"}


def _extract_wav_pcm_bytes(wav_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_path = Path(handle.name)
        temp_path.write_bytes(wav_bytes)
    try:
        with wave.open(str(temp_path), "rb") as wav_file:
            return wav_file.readframes(wav_file.getnframes())
    finally:
        temp_path.unlink(missing_ok=True)


def _wrap_pcm_as_wav(raw_audio: bytes, *, sample_rate_hz: int) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with wave.open(str(temp_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate_hz)
            wav_file.writeframes(raw_audio)
        return temp_path.read_bytes()
    finally:
        temp_path.unlink(missing_ok=True)


def _iter_sse_json_events(lines: Iterable[str | bytes]) -> Iterable[dict[str, Any]]:
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> dict[str, Any] | None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None
        raw_data = "\n".join(data_lines).strip()
        current_event = event_name
        event_name = None
        data_lines = []
        if not raw_data or raw_data == "[DONE]":
            return None
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = json.loads("".join(data_lines).strip())
        if current_event:
            payload.setdefault("_sse_event", current_event)
        return payload

    for raw_line in lines:
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw_line).strip()
        if not line:
            payload = flush()
            if payload is not None:
                yield payload
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.partition(":")[2].strip() or None
            continue
        if line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
            continue
        if data_lines:
            data_lines.append(line)
    payload = flush()
    if payload is not None:
        yield payload


def _env_first(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _env_float(name: str, *, default: float) -> float:
    try:
        return max(float(os.getenv(name) or default), 0.1)
    except ValueError:
        return default


def resolve_voice_sidecar_tts_renderer():
    forced = str(os.getenv("ASURADA_VOICE_SIDECAR_TTS_BACKEND") or "").strip().lower()
    if forced == "null":
        return None
    if forced in {"doubao_tts", "doubao_streaming", "volc_tts", "volc_streaming"}:
        return (
            DoubaoStreamingHttpSidecarTtsRenderer.from_env()
            if DoubaoStreamingHttpSidecarTtsRenderer.env_ready()
            else None
        )
    if forced == "say":
        return MacOSSaySidecarTtsRenderer.from_env() if MacOSSaySidecarTtsRenderer.env_ready() else None
    if forced == "piper":
        return PiperSidecarTtsRenderer.from_env() if PiperSidecarTtsRenderer.env_ready() else None
    if MacOSSaySidecarTtsRenderer.env_ready():
        return MacOSSaySidecarTtsRenderer.from_env()
    if PiperSidecarTtsRenderer.env_ready():
        return PiperSidecarTtsRenderer.from_env()
    return None

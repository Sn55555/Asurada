from __future__ import annotations

from .limits import SIDECAR_STREAM_FRAME_MAX

import base64
from dataclasses import dataclass, field
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Protocol

from .audio_agent_client import VoiceSidecarClient
from .macos_audio_capture import MacOSAudioCapture, MacOSAudioCaptureResult
from .macos_audio_stream import MacOSAudioStreamCapture, MacOSAudioStreamEvent
from .voice_sidecar_protocol import (
    AsrRealtimeChunk,
    AsrRealtimeEndRequest,
    AsrRealtimeFinal,
    AsrRealtimePartial,
    AsrRealtimeStartRequest,
    AsrRealtimeStarted,
    AsrTranscribeRequest,
    AsrTranscribeResponse,
    build_asr_realtime_chunk_envelope,
    build_asr_realtime_end_request_envelope,
    build_asr_realtime_start_request_envelope,
    parse_asr_realtime_final_envelope,
    parse_asr_realtime_partial_envelope,
    parse_asr_realtime_started_envelope,
)


_DEFAULT_ASR_PROMPT = (
    "阿斯拉达 阿斯兰达 艾斯拉达 饿死拉倒 "
    "后车差距 前车差距 整体形势 为什么现在不进攻 "
    "DRS ERS 轮胎 进站 车损 安全车 处罚 防守窗口 陪我聊天"
)


@dataclass(frozen=True)
class VoiceSidecarAsrRecognitionResult:
    status: str
    transcript_text: str
    confidence: float | None
    started_at_ms: int
    ended_at_ms: int
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "transcript_text": self.transcript_text,
            "confidence": self.confidence,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "locale": self.locale,
            "metadata": dict(self.metadata),
        }


class VoiceSidecarAsrBackend(Protocol):
    name: str

    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        audio_format: str,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsrTranscribeResponse:
        ...


class VoiceSidecarRealtimeAsrSession(Protocol):
    request_id: str
    locale: str

    def append_audio_chunk(self, chunk: bytes) -> None:
        ...

    def finish(
        self,
        *,
        started_at_ms: int,
        ended_at_ms: int,
        capture_status: str,
        capture_metadata: dict[str, Any] | None = None,
    ) -> VoiceSidecarAsrRecognitionResult:
        ...

    def close(self) -> None:
        ...


class RealtimeCapableVoiceSidecarAsrBackend(VoiceSidecarAsrBackend, Protocol):
    def open_realtime_session(
        self,
        *,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        partial_callback: Callable[[str], None] | None = None,
    ) -> VoiceSidecarRealtimeAsrSession:
        ...


class DoubaoRealtimeAsrStreamSession:
    def __init__(
        self,
        *,
        backend: DoubaoBigmodelStreamingWsSidecarAsrBackend,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        partial_callback: Callable[[str], None] | None = None,
        context=None,
    ) -> None:
        self.context = context
        self._watch_stop = threading.Event()
        self._watcher = None
        self.backend = backend
        self.locale = locale
        self.prompt = prompt
        self.request_metadata = dict(metadata or {})
        self.partial_callback = partial_callback
        self.request_id = f"asurada-realtime-asr-{uuid.uuid4().hex}"
        self._ws: Any | None = None
        self._pending_chunk: bytes | None = None
        self.provider_code = 0
        self.provider_message = ""
        self.provider_request_id = ""
        self.transcript_text = ""
        self.partial_transcript = ""
        self.confidence: float | None = None
        self.utterances: list[Any] = []
        self.last_sequence = 0
        self.message_count = 0
        self.chunk_count = 0
        self.final_received = False

    def open(self) -> None:
        import websocket

        payload = self.backend._build_full_request(
            request_id=self.request_id,
            audio_format="pcm",
            locale=self.locale,
        )
        payload["audio"]["format"] = "pcm"
        if self.context is not None: self.context.remaining()
        ws = websocket.create_connection(
            self.backend.url,
            timeout=min(self.backend.connect_timeout_s, self.context.remaining()) if self.context is not None else self.backend.connect_timeout_s,
            header=self.backend._build_headers(),
            enable_multithread=True,
        )
        self._ws = ws
        try:
            if self.context is not None:
                self.context.remaining()
                self._watcher = threading.Thread(target=self._watch_cancel, name='doubao-asr-cancel', daemon=True)
                self._watcher.start()
            try:
                self.provider_request_id = str(ws.headers.get("X-Tt-Logid") or "")
            except Exception:
                self.provider_request_id = ""
            self._send(_build_ws_full_request(payload))
        except BaseException:
            self.close()
            raise

    def _watch_cancel(self):
        from .task_runtime import TaskCancelled
        while not self._watch_stop.wait(.02):
            try: self.context.remaining()
            except (TaskCancelled, TimeoutError):
                ws = self._ws
                if ws is not None:
                    ws.abort()
                return

    def _send(self, payload):
        if self.context is not None:
            self._ws.settimeout(min(self.backend.recv_timeout_s, self.context.remaining()))
        try:
            self._ws.send_binary(payload)
        except Exception:
            if self.context is not None: self.context.remaining()
            raise
        if self.context is not None: self.context.remaining()

    def append_audio_chunk(self, chunk: bytes) -> None:
        if self.context is not None: self.context.remaining()
        if not chunk:
            return
        if self._ws is None:
            raise RuntimeError("realtime_asr_session_not_open")
        if self._pending_chunk is not None:
            self._send(_build_ws_audio_request(self._pending_chunk, is_last=False))
            self.chunk_count += 1
            self._ws.settimeout(0.05)
            self._consume_available()
        self._pending_chunk = chunk

    def finish(
        self,
        *,
        started_at_ms: int,
        ended_at_ms: int,
        capture_status: str,
        capture_metadata: dict[str, Any] | None = None,
    ) -> VoiceSidecarAsrRecognitionResult:
        if self._ws is None:
            raise RuntimeError("realtime_asr_session_not_open")
        try:
            if self._pending_chunk is not None:
                self._send(_build_ws_audio_request(self._pending_chunk, is_last=True))
                self.chunk_count += 1
                self._pending_chunk = None
            self._ws.settimeout(self.backend.recv_timeout_s)
            self._consume_available(final=True)
        finally:
            self.close()

        if self.context is not None: self.context.remaining()
        final_status = "recognized" if self.transcript_text else "no_speech"
        if capture_status == "timeout_no_speech" and not self.transcript_text:
            final_status = "timeout_no_speech"

        return VoiceSidecarAsrRecognitionResult(
            status=final_status,
            transcript_text=self.transcript_text,
            confidence=self.confidence,
            started_at_ms=started_at_ms,
            ended_at_ms=max(ended_at_ms, started_at_ms),
            locale=self.locale,
            metadata={
                "backend": "doubao_realtime_asr_recognizer",
                "provider": self.backend.name,
                "request_id": self.request_id,
                "provider_code": self.provider_code,
                "provider_message": self.provider_message,
                "provider_request_id": self.provider_request_id,
                "capture_status": capture_status,
                "capture_metadata": dict(capture_metadata or {}),
                "chunk_count": self.chunk_count,
                "utterance_count": len(self.utterances),
                "last_sequence": self.last_sequence,
                "message_count": self.message_count,
                "partial_transcript": self.partial_transcript,
                "prompt_supplied": bool(str(self.prompt or "").strip()),
                "request_metadata": dict(self.request_metadata),
            },
        )

    def close(self) -> None:
        self._watch_stop.set()
        if self._watcher is not None:
            self._watcher.join()
        ws, self._ws = self._ws, None
        if ws is not None:
            if self.context is not None:
                ws.shutdown()
            else:
                ws.close()

    def _consume_available(self, *, final=False) -> None:
        import websocket

        if self._ws is None:
            return
        receive_deadline = time.monotonic() + (self.backend.recv_timeout_s if final else .05)
        while True:
            if self.context is not None:
                self.context.remaining()
                if time.monotonic() >= receive_deadline:
                    break
                self._ws.settimeout(min(.05, self.context.remaining()))
            try:
                message = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                if self.context is not None:
                    self.context.remaining()
                    if final and time.monotonic() < receive_deadline: continue
                break
            except websocket.WebSocketConnectionClosedException:
                if self.context is not None: self.context.remaining()
                break
            except Exception:
                if self.context is not None: self.context.remaining()
                raise
            if self.context is not None: self.context.remaining()
            if not message: break
            if not isinstance(message, (bytes, bytearray)):
                continue
            try:
                parsed = _parse_ws_server_message(bytes(message))
            except RuntimeError as exc:
                if str(exc) == "streaming_asr_ws_message_too_short":
                    continue
                raise
            self.message_count += 1
            if parsed.get("message_type") != 0x9:
                continue
            self.last_sequence = int(parsed.get("sequence") or 0)
            response_payload = dict(parsed.get("payload") or {})
            self.provider_code = int(response_payload.get("code") or self.provider_code or 0)
            self.provider_message = str(response_payload.get("message") or self.provider_message or "")
            result_body = dict(response_payload.get("result") or {})
            text_value = str(
                result_body.get("text")
                or result_body.get("full_text")
                or result_body.get("transcript")
                or ""
            ).strip()
            if text_value:
                self.transcript_text = text_value
                if text_value != self.partial_transcript and self.partial_callback is not None and self.last_sequence >= 0:
                    self.partial_transcript = text_value
                    if self.context is not None: self.context.remaining()
                    self.partial_callback(text_value)
            self.utterances = list(result_body.get("utterances") or self.utterances)
            self.confidence = _extract_asr_confidence(result_body=result_body, utterances=self.utterances)
            if self.last_sequence < 0:
                self.final_received = True
                break


@dataclass(frozen=True)
class DoubaoBigmodelStreamingWsSidecarAsrBackend:
    supports_task_context = True
    url: str
    resource_id: str
    app_key: str | None
    access_key: str | None
    api_key: str | None
    user_id: str
    connect_timeout_s: float = 10.0
    recv_timeout_s: float = 45.0
    audio_chunk_ms: int = 200
    name: str = "doubao_bigmodel_streaming_ws_sidecar_asr_backend"

    @classmethod
    def from_env(cls) -> "DoubaoBigmodelStreamingWsSidecarAsrBackend":
        url = _env_first(
            "ASURADA_DOUBAO_STREAMING_ASR_URL",
            "ASURADA_VOLC_STREAMING_ASR_URL",
        ) or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
        resource_id = _env_first(
            "ASURADA_DOUBAO_STREAMING_ASR_RESOURCE_ID",
            "ASURADA_VOLC_STREAMING_ASR_RESOURCE_ID",
            "ASURADA_DOUBAO_ASR_STREAMING_RESOURCE_ID",
            "ASURADA_VOLC_ASR_STREAMING_RESOURCE_ID",
        ) or "volc.bigasr.sauc.duration"
        api_key = _env_first(
            "ASURADA_DOUBAO_STREAMING_ASR_API_KEY",
            "ASURADA_VOLC_STREAMING_ASR_API_KEY",
            "ASURADA_DOUBAO_ASR_API_KEY",
            "ASURADA_VOLC_ASR_API_KEY",
        )
        app_key = _env_first(
            "ASURADA_DOUBAO_STREAMING_ASR_APP_KEY",
            "ASURADA_DOUBAO_STREAMING_ASR_APP_ID",
            "ASURADA_VOLC_STREAMING_ASR_APP_KEY",
            "ASURADA_VOLC_STREAMING_ASR_APP_ID",
            "ASURADA_DOUBAO_ASR_APP_KEY",
            "ASURADA_DOUBAO_ASR_APP_ID",
            "ASURADA_VOLC_ASR_APP_KEY",
            "ASURADA_VOLC_ASR_APP_ID",
        )
        access_key = _env_first(
            "ASURADA_DOUBAO_STREAMING_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_STREAMING_ASR_ACCESS_TOKEN",
            "ASURADA_DOUBAO_STREAMING_ASR_SECRET_KEY",
            "ASURADA_VOLC_STREAMING_ASR_ACCESS_KEY",
            "ASURADA_VOLC_STREAMING_ASR_ACCESS_TOKEN",
            "ASURADA_VOLC_STREAMING_ASR_SECRET_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_TOKEN",
            "ASURADA_DOUBAO_ASR_SECRET_KEY",
            "ASURADA_VOLC_ASR_ACCESS_KEY",
            "ASURADA_VOLC_ASR_ACCESS_TOKEN",
            "ASURADA_VOLC_ASR_SECRET_KEY",
        )
        if not api_key and not (app_key and access_key):
            raise ValueError(
                "streaming ASR requires API key or APP key + access key"
            )
        return cls(
            url=url,
            resource_id=resource_id,
            app_key=app_key,
            access_key=access_key,
            api_key=api_key,
            user_id=_env_first(
                "ASURADA_DOUBAO_STREAMING_ASR_USER_ID",
                "ASURADA_VOLC_STREAMING_ASR_USER_ID",
                "ASURADA_DOUBAO_ASR_USER_ID",
                "ASURADA_VOLC_ASR_USER_ID",
            ) or "asurada-sidecar",
            connect_timeout_s=_env_float("ASURADA_DOUBAO_STREAMING_ASR_CONNECT_TIMEOUT_S", default=10.0),
            recv_timeout_s=_env_float("ASURADA_DOUBAO_STREAMING_ASR_RECV_TIMEOUT_S", default=45.0),
            audio_chunk_ms=max(
                int(_env_first("ASURADA_DOUBAO_STREAMING_ASR_CHUNK_MS", "ASURADA_VOLC_STREAMING_ASR_CHUNK_MS") or "200"),
                40,
            ),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return bool(
            importlib.util.find_spec("websocket")
            and (
                _env_first(
                    "ASURADA_DOUBAO_STREAMING_ASR_API_KEY",
                    "ASURADA_VOLC_STREAMING_ASR_API_KEY",
                    "ASURADA_DOUBAO_ASR_API_KEY",
                    "ASURADA_VOLC_ASR_API_KEY",
                )
                or (
                    _env_first(
                        "ASURADA_DOUBAO_STREAMING_ASR_APP_KEY",
                        "ASURADA_DOUBAO_STREAMING_ASR_APP_ID",
                        "ASURADA_VOLC_STREAMING_ASR_APP_KEY",
                        "ASURADA_VOLC_STREAMING_ASR_APP_ID",
                        "ASURADA_DOUBAO_ASR_APP_KEY",
                        "ASURADA_DOUBAO_ASR_APP_ID",
                        "ASURADA_VOLC_ASR_APP_KEY",
                        "ASURADA_VOLC_ASR_APP_ID",
                    )
                    and _env_first(
                        "ASURADA_DOUBAO_STREAMING_ASR_ACCESS_KEY",
                        "ASURADA_DOUBAO_STREAMING_ASR_ACCESS_TOKEN",
                        "ASURADA_DOUBAO_STREAMING_ASR_SECRET_KEY",
                        "ASURADA_VOLC_STREAMING_ASR_ACCESS_KEY",
                        "ASURADA_VOLC_STREAMING_ASR_ACCESS_TOKEN",
                        "ASURADA_VOLC_STREAMING_ASR_SECRET_KEY",
                        "ASURADA_DOUBAO_ASR_ACCESS_KEY",
                        "ASURADA_DOUBAO_ASR_ACCESS_TOKEN",
                        "ASURADA_DOUBAO_ASR_SECRET_KEY",
                        "ASURADA_VOLC_ASR_ACCESS_KEY",
                        "ASURADA_VOLC_ASR_ACCESS_TOKEN",
                        "ASURADA_VOLC_ASR_SECRET_KEY",
                    )
                )
            )
        )

    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        audio_format: str,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        context=None,
    ) -> AsrTranscribeResponse:
        import websocket

        if context is not None: context.remaining()
        started_at_ms = int(time.time() * 1000)
        request_id = f"asurada-stream-asr-{uuid.uuid4().hex}"
        payload = self._build_full_request(
            request_id=request_id,
            audio_format=audio_format,
            locale=locale,
        )
        headers = self._build_headers()
        ws = websocket.create_connection(
            self.url,
            timeout=min(self.connect_timeout_s, context.remaining()) if context is not None else self.connect_timeout_s,
            header=headers,
            enable_multithread=True,
        )
        watch_stop = threading.Event()
        watcher = None

        def watch_cancel():
            from .task_runtime import TaskCancelled
            while not watch_stop.wait(.02):
                try:
                    context.remaining()
                except (TaskCancelled, TimeoutError):
                    ws.abort()
                    return

        def send(payload):
            if context is not None:
                ws.settimeout(min(self.recv_timeout_s, context.remaining()))
            ws.send_binary(payload)
            if context is not None: context.remaining()

        def receive(timeout):
            if context is not None:
                timeout = min(timeout, context.remaining())
            ws.settimeout(timeout)
            message = ws.recv()
            if context is not None: context.remaining()
            return message

        provider_request_id = ""
        try:
            provider_request_id = str(ws.headers.get("X-Tt-Logid") or "")
        except Exception:
            provider_request_id = ""

        transcript_text = ""
        confidence: float | None = None
        utterances: list[Any] = []
        provider_code = 0
        provider_message = ""
        last_sequence = 0
        message_count = 0

        def consume_message(message: Any) -> bool:
            nonlocal transcript_text, confidence, utterances, provider_code, provider_message, last_sequence, message_count
            if isinstance(message, str):
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    return False
                message_count += 1
                text_value = str(
                    payload.get("transcript")
                    or payload.get("text")
                    or ""
                ).strip()
                if text_value:
                    transcript_text = text_value
                return bool(payload.get("type") == "conversation.item.input_audio_transcription.completed")

            if not isinstance(message, (bytes, bytearray)):
                return False

            parsed = _parse_ws_server_message(bytes(message))
            message_count += 1
            if parsed.get("message_type") != 0x9:
                return False
            last_sequence = int(parsed.get("sequence") or 0)
            response_payload = dict(parsed.get("payload") or {})
            provider_code = int(response_payload.get("code") or provider_code or 0)
            provider_message = str(response_payload.get("message") or provider_message or "")
            result_body = dict(response_payload.get("result") or {})
            text_value = str(
                result_body.get("text")
                or result_body.get("full_text")
                or result_body.get("transcript")
                or ""
            ).strip()
            if text_value:
                transcript_text = text_value
            utterances = list(result_body.get("utterances") or utterances)
            confidence = _extract_asr_confidence(result_body=result_body, utterances=utterances)
            return last_sequence < 0

        try:
            if context is not None:
                context.remaining()
                watcher = threading.Thread(target=watch_cancel, name='doubao-batch-asr-cancel', daemon=True)
                watcher.start()
            ws.settimeout(self.recv_timeout_s)
            send(_build_ws_full_request(payload))
            chunks = _iter_streaming_audio_chunks(
                audio_bytes,
                audio_format=audio_format,
                chunk_ms=self.audio_chunk_ms,
            )
            final_received = False
            for index, chunk in enumerate(chunks, start=1):
                is_last = index == len(chunks)
                send(_build_ws_audio_request(chunk, is_last=is_last))
                try:
                    receive_budget = min(max(self.audio_chunk_ms / 1000.0, 0.05), 0.2)
                    receive_deadline = time.monotonic() + receive_budget
                    while True:
                        remaining = receive_deadline - time.monotonic()
                        if remaining <= 0: break
                        if consume_message(receive(remaining)):
                            final_received = True
                            break
                except (websocket.WebSocketTimeoutException, websocket.WebSocketConnectionClosedException):
                    if context is not None: context.remaining()
                if final_received:
                    break
                if not is_last and self.audio_chunk_ms > 40:
                    delay = max((self.audio_chunk_ms - 20) / 1000.0, 0.0)
                    if context is None:
                        time.sleep(delay)
                    else:
                        context.cancellation.wait(min(delay, context.remaining()))
                        context.remaining()

            if not final_received:
                receive_deadline = time.monotonic() + self.recv_timeout_s
                while True:
                    remaining = receive_deadline - time.monotonic()
                    if remaining <= 0: break
                    try:
                        if consume_message(receive(remaining)):
                            break
                    except (websocket.WebSocketTimeoutException, websocket.WebSocketConnectionClosedException):
                        if context is not None: context.remaining()
                        break
        except Exception:
            if context is not None: context.remaining()
            raise
        finally:
            watch_stop.set()
            if watcher is not None: watcher.join()
            try:
                if context is not None:
                    ws.shutdown()
                else:
                    ws.close()
            except Exception:
                pass

        if context is not None: context.remaining()
        ended_at_ms = int(time.time() * 1000)
        if provider_code and provider_code not in {1000, 20000000, 20000003}:
            raise RuntimeError(f"doubao_streaming_asr_error:{provider_code}:{provider_message}")

        status = "recognized" if transcript_text else "no_speech"
        if provider_code in {20000003}:
            status = "no_speech"

        return AsrTranscribeResponse(
            status=status,
            transcript_text=transcript_text,
            confidence=confidence,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            locale=locale,
            metadata={
                "backend": self.name,
                "provider": "doubao_bigmodel_streaming_ws",
                "url": self.url,
                "resource_id": self.resource_id,
                "request_id": request_id,
                "provider_code": provider_code,
                "provider_message": provider_message,
                "provider_request_id": provider_request_id,
                "audio_format": audio_format,
                "utterance_count": len(utterances),
                "last_sequence": last_sequence,
                "message_count": message_count,
                "prompt_supplied": bool(str(prompt or "").strip()),
                "boosting_table_id": _env_first(
                    "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_ID",
                    "ASURADA_VOLC_ASR_BOOSTING_TABLE_ID",
                ),
                "boosting_table_name": _env_first(
                    "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_NAME",
                    "ASURADA_VOLC_ASR_BOOSTING_TABLE_NAME",
                ),
                "request_metadata": dict(metadata or {}),
            },
        )

    def open_realtime_session(
        self,
        *,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        partial_callback: Callable[[str], None] | None = None,
        context=None,
    ) -> VoiceSidecarRealtimeAsrSession:
        session = DoubaoRealtimeAsrStreamSession(
            backend=self,
            context=context,
            locale=locale,
            prompt=prompt,
            metadata=metadata,
            partial_callback=partial_callback,
        )
        session.open()
        return session

    def _build_headers(self) -> list[str]:
        headers = [
            f"X-Api-Resource-Id: {self.resource_id}",
        ]
        if self.api_key:
            headers.append(f"X-Api-Key: {self.api_key}")
        else:
            headers.append(f"X-Api-App-Key: {self.app_key}")
            headers.append(f"X-Api-Access-Key: {self.access_key}")
        return headers

    def _build_full_request(self, *, request_id: str, audio_format: str, locale: str) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
            "user": {"uid": self.user_id},
            "audio": {
                "format": _normalize_streaming_audio_format(audio_format),
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "language": locale or "zh-CN",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_ddc": True,
                "enable_punc": True,
                "show_utterances": True,
                "result_type": "single",
                "vad_signal": True,
                "start_silence_time": 2000,
                "vad_silence_time": 800,
                "reqid": request_id,
            },
        }
        boosting_table_id = _env_first(
            "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_ID",
            "ASURADA_VOLC_ASR_BOOSTING_TABLE_ID",
        )
        boosting_table_name = _env_first(
            "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_NAME",
            "ASURADA_VOLC_ASR_BOOSTING_TABLE_NAME",
        )
        if boosting_table_id or boosting_table_name:
            request_payload["request"]["corpus"] = {}
            if boosting_table_id:
                request_payload["request"]["corpus"]["boosting_table_id"] = boosting_table_id
            if boosting_table_name:
                request_payload["request"]["corpus"]["boosting_table_name"] = boosting_table_name
        return request_payload


@dataclass(frozen=True)
class DoubaoFlashHttpSidecarAsrBackend:
    supports_task_context = True
    url: str
    resource_id: str
    app_key: str | None
    access_key: str | None
    api_key: str | None
    boosting_table_id: str | None
    boosting_table_name: str | None
    user_id: str
    request_model_name: str
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 45.0
    name: str = "doubao_flash_http_sidecar_asr_backend"

    @classmethod
    def from_env(cls) -> "DoubaoFlashHttpSidecarAsrBackend":
        url = _env_first(
            "ASURADA_DOUBAO_ASR_URL",
            "ASURADA_VOLC_ASR_URL",
        ) or "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
        resource_id = _env_first(
            "ASURADA_DOUBAO_ASR_RESOURCE_ID",
            "ASURADA_VOLC_ASR_RESOURCE_ID",
        ) or "volc.bigasr.auc_turbo"
        api_key = _env_first(
            "ASURADA_DOUBAO_ASR_API_KEY",
            "ASURADA_VOLC_ASR_API_KEY",
        )
        app_key = _env_first(
            "ASURADA_DOUBAO_ASR_APP_KEY",
            "ASURADA_DOUBAO_ASR_APP_ID",
            "ASURADA_VOLC_ASR_APP_KEY",
            "ASURADA_VOLC_ASR_APP_ID",
            "ASURADA_DOUBAO_TTS_APP_ID",
            "ASURADA_VOLC_TTS_APP_ID",
        )
        access_key = _env_first(
            "ASURADA_DOUBAO_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_TOKEN",
            "ASURADA_DOUBAO_ASR_SECRET_KEY",
            "ASURADA_DOUBAO_ASR_TOKEN",
            "ASURADA_DOUBAO_ASR_API_TOKEN",
            "ASURADA_VOLC_ASR_ACCESS_KEY",
            "ASURADA_VOLC_ASR_ACCESS_TOKEN",
            "ASURADA_VOLC_ASR_SECRET_KEY",
            "ASURADA_VOLC_ASR_TOKEN",
            "ASURADA_DOUBAO_TTS_ACCESS_KEY",
            "ASURADA_DOUBAO_TTS_TOKEN",
            "ASURADA_VOLC_TTS_ACCESS_KEY",
            "ASURADA_VOLC_TTS_TOKEN",
        )
        if not api_key and not (app_key and access_key):
            raise ValueError(
                "ASURADA_DOUBAO_ASR_API_KEY or ASURADA_DOUBAO_ASR_APP_KEY + ASURADA_DOUBAO_ASR_ACCESS_KEY is required"
            )
        return cls(
            url=url,
            resource_id=resource_id,
            app_key=app_key,
            access_key=access_key,
            api_key=api_key,
            boosting_table_id=_env_first(
                "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_ID",
                "ASURADA_VOLC_ASR_BOOSTING_TABLE_ID",
            ),
            boosting_table_name=_env_first(
                "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_NAME",
                "ASURADA_VOLC_ASR_BOOSTING_TABLE_NAME",
            ),
            user_id=_env_first("ASURADA_DOUBAO_ASR_USER_ID", "ASURADA_VOLC_ASR_USER_ID") or "asurada-sidecar",
            request_model_name=_env_first("ASURADA_DOUBAO_ASR_MODEL_NAME", "ASURADA_VOLC_ASR_MODEL_NAME") or "bigmodel",
            connect_timeout_s=_env_float("ASURADA_DOUBAO_ASR_CONNECT_TIMEOUT_S", default=10.0),
            read_timeout_s=_env_float("ASURADA_DOUBAO_ASR_READ_TIMEOUT_S", default=45.0),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return bool(
            importlib.util.find_spec("requests")
            and (
                _env_first("ASURADA_DOUBAO_ASR_API_KEY", "ASURADA_VOLC_ASR_API_KEY")
                or (
                    _env_first(
                        "ASURADA_DOUBAO_ASR_APP_KEY",
                        "ASURADA_DOUBAO_ASR_APP_ID",
                        "ASURADA_VOLC_ASR_APP_KEY",
                        "ASURADA_VOLC_ASR_APP_ID",
                        "ASURADA_DOUBAO_TTS_APP_ID",
                        "ASURADA_VOLC_TTS_APP_ID",
                    )
                    and _env_first(
                        "ASURADA_DOUBAO_ASR_ACCESS_KEY",
                        "ASURADA_DOUBAO_ASR_ACCESS_TOKEN",
                        "ASURADA_DOUBAO_ASR_SECRET_KEY",
                        "ASURADA_DOUBAO_ASR_TOKEN",
                        "ASURADA_DOUBAO_ASR_API_TOKEN",
                        "ASURADA_VOLC_ASR_ACCESS_KEY",
                        "ASURADA_VOLC_ASR_ACCESS_TOKEN",
                        "ASURADA_VOLC_ASR_SECRET_KEY",
                        "ASURADA_VOLC_ASR_TOKEN",
                        "ASURADA_DOUBAO_TTS_ACCESS_KEY",
                        "ASURADA_DOUBAO_TTS_TOKEN",
                        "ASURADA_VOLC_TTS_ACCESS_KEY",
                        "ASURADA_VOLC_TTS_TOKEN",
                    )
                )
            )
        )

    def transcribe_audio(
        self,
        *,
        audio_bytes: bytes,
        audio_format: str,
        locale: str,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        context=None,
    ) -> AsrTranscribeResponse:
        if context is not None: context.remaining()

        started_at_ms = int(time.time() * 1000)
        request_id = f"asurada-asr-{uuid.uuid4().hex}"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        else:
            headers["X-Api-App-Key"] = str(self.app_key or "")
            headers["X-Api-App-ID"] = str(self.app_key or "")
            headers["X-Api-Access-Key"] = str(self.access_key or "")

        body: dict[str, Any] = {
            "user": {"uid": self.user_id},
            "audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
            },
            "request": {
                "model_name": self.request_model_name,
                "show_utterances": True,
                "enable_punc": True,
                "enable_itn": True,
            },
        }
        if locale:
            body["request"]["locale"] = locale
        if self.boosting_table_id:
            body["request"]["boosting_table_id"] = self.boosting_table_id
        elif self.boosting_table_name:
            body["request"]["boosting_table_name"] = self.boosting_table_name

        if context is not None:
            from .cancellable_http import request_json
            payload, response_headers = request_json(self.url,method='POST',body=body,headers=headers,
                context=context,timeout_ms=(self.connect_timeout_s+self.read_timeout_s)*1000,
                connect_timeout_s=self.connect_timeout_s,read_timeout_s=self.read_timeout_s,
                include_response_headers=True,propagate_budget=False)
            context.remaining()
        else:
            import requests
            with requests.post(self.url,headers=headers,json=body,
                               timeout=(self.connect_timeout_s,self.read_timeout_s)) as response:
                response.raise_for_status()
                payload=response.json()
                response_headers={key.lower():value for key,value in response.headers.items()}
        provider_code=int(response_headers.get('x-api-status-code') or 0)
        provider_message=str(response_headers.get('x-api-message') or '')
        provider_request_id=str(response_headers.get('x-tt-logid') or response_headers.get('x-request-id') or '')

        ended_at_ms = int(time.time() * 1000)
        if provider_code not in {20_000_000, 20_000_003}:
            raise RuntimeError(f"doubao_asr_http_error:{provider_code}:{provider_message}")

        result_body = dict(payload.get("result") or {})
        transcript_text = str(
            result_body.get("text")
            or result_body.get("full_text")
            or result_body.get("transcript")
            or ""
        ).strip()
        utterances = list(result_body.get("utterances") or [])
        confidence = _extract_asr_confidence(result_body=result_body, utterances=utterances)
        status = "recognized" if transcript_text else "no_speech"
        if provider_code == 20_000_003:
            status = "no_speech"

        return AsrTranscribeResponse(
            status=status,
            transcript_text=transcript_text,
            confidence=confidence,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            locale=locale,
            metadata={
                "backend": self.name,
                "provider": "doubao_asr_flash_http",
                "url": self.url,
                "resource_id": self.resource_id,
                "request_id": request_id,
                "provider_code": provider_code,
                "provider_message": provider_message,
                "audio_format": audio_format,
                "utterance_count": len(utterances),
                "provider_request_id": provider_request_id,
                "prompt_supplied": bool(str(prompt or "").strip()),
                "boosting_table_id": self.boosting_table_id,
                "boosting_table_name": self.boosting_table_name,
                "request_metadata": dict(metadata or {}),
            },
        )


class VoiceSidecarAsrRecognizer:
    supports_task_context = True
    def __init__(
        self,
        *,
        audio_capture: MacOSAudioCapture | None = None,
        client: VoiceSidecarClient | None = None,
        locale: str = "zh-CN",
        prompt: str = _DEFAULT_ASR_PROMPT,
        keep_audio_files: bool = False,
    ) -> None:
        self.audio_capture = audio_capture or MacOSAudioCapture.from_env()
        self.client = client or VoiceSidecarClient.from_env()
        self.locale = locale
        self.prompt = prompt
        self.keep_audio_files = keep_audio_files

    @classmethod
    def from_env(cls) -> "VoiceSidecarAsrRecognizer":
        return cls(
            locale=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_LOCALE") or "zh-CN"),
            prompt=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_PROMPT") or _DEFAULT_ASR_PROMPT),
            keep_audio_files=_env_bool("ASURADA_VOICE_SIDECAR_ASR_KEEP_AUDIO"),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return MacOSAudioCapture.env_ready()

    def listen_once(self, *, context=None) -> VoiceSidecarAsrRecognitionResult:
        capture = (self.audio_capture.capture_once(context=context) if context is not None else self.audio_capture.capture_once())
        if capture.status not in {"recorded", "recorded_timeout"}:
            return VoiceSidecarAsrRecognitionResult(
                status=capture.status,
                transcript_text="",
                confidence=None,
                started_at_ms=capture.started_at_ms,
                ended_at_ms=capture.ended_at_ms,
                locale=self.locale,
                metadata={"capture": capture.to_dict(), "backend": "voice_sidecar_asr_capture_passthrough"},
            )

        source_path = Path(capture.audio_file_path)
        prepared_path = source_path
        try:
            if context is not None: context.remaining()
            prepared_path = _prepare_audio_for_asr(source_path, context=context) if context is not None else _prepare_audio_for_asr(source_path)
            if context is not None: context.remaining()
            request = AsrTranscribeRequest(
                audio_base64=base64.b64encode(prepared_path.read_bytes()).decode("ascii"),
                audio_format="wav",
                locale=self.locale,
                prompt=self.prompt,
                metadata={"capture": capture.to_dict()},
            )
            response = (self.client.transcribe_asr(request=request, context=context)
                        if context is not None else self.client.transcribe_asr(request=request))
            if context is not None: context.remaining()
            return VoiceSidecarAsrRecognitionResult(
                status=response.status,
                transcript_text=response.transcript_text,
                confidence=response.confidence,
                started_at_ms=capture.started_at_ms,
                ended_at_ms=max(capture.ended_at_ms, response.ended_at_ms),
                locale=response.locale,
                metadata={**dict(response.metadata), "capture": capture.to_dict()},
            )
        finally:
            if not self.keep_audio_files:
                try:
                    source_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if prepared_path != source_path:
                    try:
                        prepared_path.unlink(missing_ok=True)
                    except OSError:
                        pass


class DoubaoRealtimeAsrRecognizer:
    supports_task_context = True
    """True chunked microphone capture + Doubao websocket ASR, final transcript enters the normal router."""

    def __init__(
        self,
        *,
        audio_capture: MacOSAudioStreamCapture | None = None,
        backend: DoubaoBigmodelStreamingWsSidecarAsrBackend | None = None,
        locale: str = "zh-CN",
        prompt: str = _DEFAULT_ASR_PROMPT,
        partial_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.audio_capture = audio_capture or MacOSAudioStreamCapture.from_env()
        self.backend = backend or DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
        self.locale = locale
        self.prompt = prompt
        self.partial_callback = partial_callback

    @classmethod
    def from_env(
        cls,
        *,
        partial_callback: Callable[[str], None] | None = None,
    ) -> "DoubaoRealtimeAsrRecognizer":
        return cls(
            locale=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_LOCALE") or "zh-CN"),
            prompt=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_PROMPT") or _DEFAULT_ASR_PROMPT),
            partial_callback=partial_callback,
        )

    @classmethod
    def env_ready(cls) -> bool:
        return MacOSAudioStreamCapture.env_ready() and DoubaoBigmodelStreamingWsSidecarAsrBackend.env_ready()

    def listen_once(self, *, context=None) -> VoiceSidecarAsrRecognitionResult:
        started_at_ms = int(time.time() * 1000)
        capture_status = "unknown"
        capture_metadata: dict[str, Any] = {}
        ended_at_ms = started_at_ms
        session_options = {'context': context} if context is not None else {}
        session = self.backend.open_realtime_session(
            **session_options,
            locale=self.locale,
            prompt=self.prompt,
            partial_callback=self.partial_callback,
        )
        events = None
        try:
            events = self.audio_capture.iter_events(context=context) if context is not None else self.audio_capture.iter_events()
            for event in events:
                if event.type == "start":
                    started_at_ms = int(event.started_at_ms or started_at_ms)
                    continue
                if event.type == "chunk":
                    chunk_bytes = base64.b64decode(event.audio_base64 or "")
                    if chunk_bytes:
                        session.append_audio_chunk(chunk_bytes)
                    continue
                if event.type == "end":
                    capture_status = str(event.status or "unknown")
                    capture_metadata = dict(event.metadata or {})
                    ended_at_ms = int(event.ended_at_ms or int(time.time() * 1000))
                    break
            return session.finish(
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                capture_status=capture_status,
                capture_metadata=capture_metadata,
            )
        finally:
            try:
                if hasattr(events, "close"): events.close()
            finally:
                session.close()


class VoiceSidecarRealtimeAsrRecognizer:
    supports_task_context = True
    def __init__(
        self,
        *,
        audio_capture: MacOSAudioStreamCapture | None = None,
        host: str = "127.0.0.1",
        port: int = 8789,
        locale: str = "zh-CN",
        prompt: str = _DEFAULT_ASR_PROMPT,
        partial_callback: Callable[[str], None] | None = None,
        connect_timeout_s: float = 5.0,
    ) -> None:
        self.audio_capture = audio_capture or MacOSAudioStreamCapture.from_env()
        self.host = host
        self.port = max(int(port), 1)
        self.locale = locale
        self.prompt = prompt
        self.partial_callback = partial_callback
        self.connect_timeout_s = max(float(connect_timeout_s), 0.5)

    @classmethod
    def from_env(
        cls,
        *,
        partial_callback: Callable[[str], None] | None = None,
    ) -> "VoiceSidecarRealtimeAsrRecognizer":
        base_port = int(os.getenv("ASURADA_VOICE_SIDECAR_PORT") or "8788")
        return cls(
            host=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_STREAM_HOST") or os.getenv("ASURADA_VOICE_SIDECAR_HOST") or "127.0.0.1"),
            port=int(os.getenv("ASURADA_VOICE_SIDECAR_ASR_STREAM_PORT") or str(base_port + 1)),
            locale=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_LOCALE") or "zh-CN"),
            prompt=str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_PROMPT") or _DEFAULT_ASR_PROMPT),
            partial_callback=partial_callback,
            connect_timeout_s=_env_float("ASURADA_VOICE_SIDECAR_ASR_STREAM_CONNECT_TIMEOUT_S", default=5.0),
        )

    @classmethod
    def env_ready(cls) -> bool:
        return MacOSAudioStreamCapture.env_ready()

    def listen_once(self, *, context=None) -> VoiceSidecarAsrRecognitionResult:
        from .task_runtime import TaskContext, TaskCancelled
        task = context or TaskContext.start('sidecar-asr', max(self.audio_capture.config.command_timeout_s, 1.)*1000)
        started_at_ms = int(time.time() * 1000)
        ended_at_ms = started_at_ms
        capture_status = "unknown"
        capture_metadata = {}
        partial_transcript = ""
        final_result = {}
        final_event = threading.Event()
        receiver_errors = []
        with socket.create_connection((self.host, self.port), timeout=min(self.connect_timeout_s, task.remaining())) as sock:
            sock.settimeout(None)
            reader = sock.makefile("rb")
            stop_watch = threading.Event()
            receiver_thread = None
            events = None
            def shutdown():
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            def watch():
                while not stop_watch.wait(.02):
                    try: task.remaining()
                    except (TaskCancelled, TimeoutError):
                        shutdown()
                        return
            watcher = threading.Thread(target=watch, name='asr-socket-cancel', daemon=True)
            watcher.start()
            def send_envelope(payload):
                task.remaining()
                sock.sendall((json.dumps(payload, ensure_ascii=False)+"\n").encode('utf-8'))
                task.remaining()
            def receiver():
                nonlocal partial_transcript, final_result
                try:
                    while True:
                        raw = reader.readline(SIDECAR_STREAM_FRAME_MAX+1)
                        task.remaining()
                        if not raw: return
                        if len(raw)>SIDECAR_STREAM_FRAME_MAX: raise ValueError('asr_frame_too_large')
                        if not raw.strip(): continue
                        payload = json.loads(raw)
                        message_type = str(payload.get('message_type') or '')
                        if message_type == 'asr_realtime_started':
                            parse_asr_realtime_started_envelope(payload)
                        elif message_type == 'asr_realtime_partial':
                            partial = parse_asr_realtime_partial_envelope(payload)
                            partial_transcript = partial.transcript_text
                            task.remaining()
                            if self.partial_callback is not None and partial_transcript:
                                self.partial_callback(partial_transcript)
                        elif message_type == 'asr_realtime_final':
                            final = parse_asr_realtime_final_envelope(payload)
                            final_result = dict(status=final.status, transcript_text=final.transcript_text,
                                confidence=final.confidence, started_at_ms=final.started_at_ms,
                                ended_at_ms=final.ended_at_ms, locale=final.locale, metadata=dict(final.metadata))
                            return
                except Exception as exc:
                    receiver_errors.append(exc)
                finally:
                    final_event.set()
            try:
                send_envelope(build_asr_realtime_start_request_envelope(
                    AsrRealtimeStartRequest(locale=self.locale, audio_format='pcm', prompt=self.prompt)).to_dict())
                receiver_thread = threading.Thread(target=receiver, name='voice-sidecar-realtime-asr', daemon=True)
                receiver_thread.start()
                events = self.audio_capture.iter_events(context=task) if context is not None else self.audio_capture.iter_events()
                chunk_index = 0
                for event in events:
                    task.remaining()
                    if event.type == 'start':
                        started_at_ms = int(event.started_at_ms or started_at_ms)
                    elif event.type == 'chunk':
                        chunk_bytes = base64.b64decode(event.audio_base64 or '')
                        if not chunk_bytes: continue
                        chunk_index += 1
                        send_envelope(build_asr_realtime_chunk_envelope(AsrRealtimeChunk(
                            sequence_id=chunk_index, audio_base64=base64.b64encode(chunk_bytes).decode('ascii'))).to_dict())
                    elif event.type == 'end':
                        capture_status = str(event.status or 'unknown')
                        capture_metadata = dict(event.metadata or {})
                        ended_at_ms = int(event.ended_at_ms or int(time.time()*1000))
                        send_envelope(build_asr_realtime_end_request_envelope(AsrRealtimeEndRequest(
                            started_at_ms=started_at_ms, ended_at_ms=ended_at_ms,
                            status=capture_status, metadata=capture_metadata)).to_dict())
                        break
                while not final_event.wait(timeout=min(.02,task.remaining())):
                    pass
                task.remaining()
                if receiver_errors: raise receiver_errors[0]
            except Exception:
                task.remaining()  # Preserve cancellation/deadline instead of a shutdown socket error.
                raise
            finally:
                stop_watch.set()
                shutdown()  # Unblock readline/send before closing their file handles.
                try:
                    if events is not None and hasattr(events, 'close'): events.close()
                finally:
                    watcher.join(1)
                    if receiver_thread is not None: receiver_thread.join(1)
                    if receiver_thread is not None and receiver_thread.is_alive():
                        # A user callback can be non-cooperative. Keep the live
                        # recognizer worker occupied until it exits, rather than
                        # releasing its slot and leaking another receiver per turn.
                        self.receiver_shutdown_confirmed = False
                        receiver_thread.join()
                    reader.close()
                    self.receiver_shutdown_confirmed = True

        result_metadata = dict(final_result.get("metadata") or {})
        if partial_transcript and not result_metadata.get("partial_transcript"):
            result_metadata["partial_transcript"] = partial_transcript
        result_metadata.setdefault("backend", "voice_sidecar_realtime_asr_recognizer")
        result_metadata.setdefault("capture_status", capture_status)
        result_metadata.setdefault("capture_metadata", capture_metadata)
        if final_result:
            return VoiceSidecarAsrRecognitionResult(
                status=str(final_result.get("status") or "error"),
                transcript_text=str(final_result.get("transcript_text") or ""),
                confidence=final_result.get("confidence"),
                started_at_ms=int(final_result.get("started_at_ms") or started_at_ms),
                ended_at_ms=int(final_result.get("ended_at_ms") or ended_at_ms),
                locale=str(final_result.get("locale") or self.locale),
                metadata=result_metadata,
            )
        return VoiceSidecarAsrRecognitionResult(
            status="error",
            transcript_text="",
            confidence=None,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            locale=self.locale,
            metadata={
                **result_metadata,
                "reason": "voice_sidecar_realtime_asr_no_final",
            },
        )


def resolve_voice_sidecar_asr_backend() -> VoiceSidecarAsrBackend | None:
    forced_backend = str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_BACKEND") or "").strip().lower()
    if forced_backend in {"", "doubao", "doubao_asr", "volc", "volc_asr", "doubao_streaming_asr", "volc_streaming_asr"}:
        if forced_backend in {"doubao_streaming_asr", "volc_streaming_asr"} and DoubaoBigmodelStreamingWsSidecarAsrBackend.env_ready():
            return DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
        if forced_backend in {"", "doubao", "doubao_asr", "volc", "volc_asr"} and DoubaoBigmodelStreamingWsSidecarAsrBackend.env_ready():
            return DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
        if DoubaoFlashHttpSidecarAsrBackend.env_ready():
            return DoubaoFlashHttpSidecarAsrBackend.from_env()
        return None
    if forced_backend in {"none", "disabled"}:
        return None
    if forced_backend in {"doubao_bigmodel_streaming_ws", "doubao_streaming_ws"} and DoubaoBigmodelStreamingWsSidecarAsrBackend.env_ready():
        return DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
    if forced_backend in {"doubao_flash", "doubao_flash_asr"} and DoubaoFlashHttpSidecarAsrBackend.env_ready():
        return DoubaoFlashHttpSidecarAsrBackend.from_env()
    return None


def _normalize_streaming_audio_format(audio_format: str) -> str:
    lowered = str(audio_format or "").strip().lower()
    if lowered in {"wav", "wave"}:
        return "pcm"
    if lowered in {"pcm", "raw", "s16le", "pcm_s16le"}:
        return "pcm"
    if lowered in {"ogg", "opus", "ogg_opus"}:
        return "ogg"
    if lowered in {"mp3"}:
        return "mp3"
    return "wav"


def _iter_streaming_audio_chunks(audio_bytes: bytes, *, audio_format: str, chunk_ms: int) -> list[bytes]:
    if chunk_ms <= 0:
        raise ValueError('audio_chunk_ms_must_be_positive')
    lowered = str(audio_format).strip().lower()
    if lowered in {'wav', 'wave'}:
        import wave
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wav_file:
            # The provider request declares 16 kHz, mono, 16-bit PCM.
            if (wav_file.getframerate(), wav_file.getnchannels(), wav_file.getsampwidth()) != (16000, 1, 2):
                raise ValueError('streaming_asr_requires_16khz_mono_s16_audio')
            pcm = wav_file.readframes(wav_file.getnframes())
        chunk_bytes = max(int(16000 * chunk_ms / 1000), 1) * 2
        return [pcm[index:index + chunk_bytes] for index in range(0, len(pcm), chunk_bytes) if pcm[index:index + chunk_bytes]]
    if lowered in {'pcm', 'raw', 's16le', 'pcm_s16le'}:
        if len(audio_bytes) % 2:
            raise ValueError('incomplete_pcm_sample')
        chunk_bytes = max(int(16000 * chunk_ms / 1000), 1) * 2
        return [audio_bytes[index:index + chunk_bytes] for index in range(0, len(audio_bytes), chunk_bytes)]
    return [audio_bytes]


def _build_ws_full_request(payload: dict[str, Any]) -> bytes:
    body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    header = bytes([0x11, 0x10, 0x11, 0x00])
    return header + len(body).to_bytes(4, byteorder="big", signed=False) + body


def _build_ws_audio_request(audio_chunk: bytes, *, is_last: bool) -> bytes:
    body = gzip.compress(audio_chunk)
    header = bytes([0x11, 0x22 if is_last else 0x20, 0x01, 0x00])
    return header + len(body).to_bytes(4, byteorder="big", signed=False) + body


def _parse_ws_server_message(message: bytes) -> dict[str, Any]:
    if len(message) < 12:
        raise RuntimeError("streaming_asr_ws_message_too_short")
    message_type = (message[1] >> 4) & 0x0F
    if message_type == 0xF:
        error_code = int.from_bytes(message[4:8], byteorder="big", signed=False)
        error_size = int.from_bytes(message[8:12], byteorder="big", signed=False) if len(message) >= 12 else 0
        error_text = message[12:12 + error_size].decode("utf-8", errors="replace") if error_size > 0 else ""
        raise RuntimeError(f"streaming_asr_ws_error:{error_code}:{error_text}")
    sequence = int.from_bytes(message[4:8], byteorder="big", signed=True)
    payload_size = int.from_bytes(message[8:12], byteorder="big", signed=False)
    payload_bytes = message[12:12 + payload_size]
    if payload_bytes[:2] == b"\x1f\x8b":
        payload_bytes = gzip.decompress(payload_bytes)
    payload = json.loads(payload_bytes.decode("utf-8"))
    return {
        "message_type": message_type,
        "sequence": sequence,
        "payload": payload,
    }


def _prepare_audio_for_asr(source_path: Path, *, context=None) -> Path:
    if context is not None: context.remaining()
    if source_path.suffix.lower() == ".wav":
        return source_path
    afconvert_binary = shutil.which("afconvert") or "/usr/bin/afconvert"
    if not shutil.which("afconvert") and not Path(afconvert_binary).exists():
        raise RuntimeError("afconvert_unavailable_for_asr_audio_conversion")
    output_path = Path(tempfile.gettempdir()) / f"{source_path.stem}_{uuid.uuid4().hex}_sidecar_asr.wav"
    command = [afconvert_binary, '-f', 'WAVE', '-d', 'LEI16', '-r', '16000', '-c', '1', str(source_path), str(output_path)]
    try:
        if context is not None:
            from .capture_process import command_json_text
            command_json_text(command, timeout_s=min(20., context.remaining()), context=context)
            context.remaining()
        else:
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, timeout=20, check=False)
            if completed.returncode != 0:
                raise RuntimeError(f"asr_audio_convert_failed:{completed.stderr.strip()}")
        return output_path
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise


def _extract_asr_confidence(*, result_body: dict[str, Any], utterances: list[Any]) -> float | None:
    candidates: list[float] = []
    for value in (
        result_body.get("confidence"),
        result_body.get("avg_confidence"),
        result_body.get("speech_rate"),
    ):
        try:
            if value is not None:
                candidates.append(float(value))
        except (TypeError, ValueError):
            pass
    for utterance in utterances:
        if not isinstance(utterance, dict):
            continue
        for key in ("confidence", "avg_confidence"):
            try:
                value = utterance.get(key)
                if value is not None:
                    candidates.append(float(value))
            except (TypeError, ValueError):
                pass
    return candidates[0] if candidates else None


def _env_first(*names: str) -> str | None:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return None


def _env_float(name: str, *, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "DoubaoRealtimeAsrRecognizer",
    "DoubaoBigmodelStreamingWsSidecarAsrBackend",
    "DoubaoRealtimeAsrStreamSession",
    "DoubaoFlashHttpSidecarAsrBackend",
    "RealtimeCapableVoiceSidecarAsrBackend",
    "VoiceSidecarAsrRecognitionResult",
    "VoiceSidecarAsrRecognizer",
    "VoiceSidecarRealtimeAsrRecognizer",
    "VoiceSidecarRealtimeAsrSession",
    "resolve_voice_sidecar_asr_backend",
]

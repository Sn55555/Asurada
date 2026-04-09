from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import os
import socketserver
import threading
from typing import Any

from .llm_explainer import (
    LlmExplainer,
    LlmExplainerRequest,
    NullLlmExplainerBackend,
    llm_timeout_ms_from_env,
    resolve_embedded_llm_explainer_backend,
)
from .voice_sidecar_protocol import (
    AsrRealtimeFinal,
    AsrRealtimePartial,
    AsrRealtimeStartRequest,
    AsrRealtimeStarted,
    AsrTranscribeResponse,
    TtsAudioFrame,
    TtsRenderResponse,
    TtsStreamEnd,
    TtsStreamStart,
    VoiceSidecarHealth,
    build_asr_realtime_final_envelope,
    build_asr_realtime_partial_envelope,
    build_asr_realtime_started_envelope,
    build_asr_transcribe_response_envelope,
    build_tts_audio_frame_envelope,
    build_explainer_result_envelope,
    build_health_envelope,
    build_tts_render_response_envelope,
    build_tts_stream_end_envelope,
    build_tts_stream_start_envelope,
    parse_asr_realtime_chunk_envelope,
    parse_asr_realtime_end_request_envelope,
    parse_asr_realtime_start_request_envelope,
    parse_asr_transcribe_request_envelope,
    parse_explainer_request_envelope,
    parse_tts_render_request_envelope,
)
from .voice_sidecar_asr import (
    RealtimeCapableVoiceSidecarAsrBackend,
    VoiceSidecarAsrBackend,
    resolve_voice_sidecar_asr_backend,
)
from .voice_sidecar_tts import (
    VoiceSidecarTtsRenderer,
    TtsStreamRender,
    resolve_voice_sidecar_tts_renderer,
    stream_render_from_response,
)


@dataclass(frozen=True)
class VoiceSidecarServerConfig:
    host: str = "127.0.0.1"
    port: int = 8788
    asr_stream_host: str = "127.0.0.1"
    asr_stream_port: int = 8789
    sidecar_name: str = "asurada_voice_sidecar"
    tts_enabled: bool = False


class VoiceSidecarServer:
    def __init__(
        self,
        *,
        config: VoiceSidecarServerConfig | None = None,
        llm_explainer: LlmExplainer | None = None,
        asr_backend: VoiceSidecarAsrBackend | None = None,
        tts_renderer: VoiceSidecarTtsRenderer | None = None,
    ) -> None:
        self.config = config or self.from_env().config
        self.llm_explainer = llm_explainer or LlmExplainer(
            backend=resolve_embedded_llm_explainer_backend(),
            default_timeout_ms=llm_timeout_ms_from_env(),
        )
        self.asr_backend = asr_backend if asr_backend is not None else resolve_voice_sidecar_asr_backend()
        self.tts_renderer = tts_renderer if tts_renderer is not None else resolve_voice_sidecar_tts_renderer()
        handler_cls = self._make_handler_class()
        self._httpd = ThreadingHTTPServer((self.config.host, self.config.port), handler_cls)
        self._asr_stream_server = self._build_asr_stream_server()
        self._asr_stream_thread: threading.Thread | None = None

    @property
    def listening_host(self) -> str:
        return str(self._httpd.server_address[0])

    @property
    def listening_port(self) -> int:
        return int(self._httpd.server_address[1])

    @classmethod
    def from_env(cls) -> "VoiceSidecarServer":
        host = str(os.getenv("ASURADA_VOICE_SIDECAR_HOST") or "127.0.0.1").strip()
        port = int(os.getenv("ASURADA_VOICE_SIDECAR_PORT") or "8788")
        asr_stream_host = str(os.getenv("ASURADA_VOICE_SIDECAR_ASR_STREAM_HOST") or host).strip()
        asr_stream_port = int(os.getenv("ASURADA_VOICE_SIDECAR_ASR_STREAM_PORT") or str(port + 1))
        sidecar_name = str(os.getenv("ASURADA_VOICE_SIDECAR_NAME") or "asurada_voice_sidecar").strip()
        tts_enabled = str(os.getenv("ASURADA_VOICE_SIDECAR_TTS_ENABLED") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            config=VoiceSidecarServerConfig(
                host=host,
                port=port,
                asr_stream_host=asr_stream_host,
                asr_stream_port=asr_stream_port,
                sidecar_name=sidecar_name,
                tts_enabled=tts_enabled,
            )
        )

    def serve_forever(self) -> None:
        if self._asr_stream_server is not None and self._asr_stream_thread is None:
            self._asr_stream_thread = threading.Thread(
                target=self._asr_stream_server.serve_forever,
                name="voice-sidecar-asr-stream",
                daemon=True,
            )
            self._asr_stream_thread.start()
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._asr_stream_server is not None:
            self._asr_stream_server.shutdown()
            self._asr_stream_server.server_close()
        if self._asr_stream_thread is not None:
            self._asr_stream_thread.join(timeout=1.0)

    def _make_handler_class(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/healthz":
                    health = VoiceSidecarHealth(
                        status="ok",
                        sidecar_name=outer.config.sidecar_name,
                        llm_backend_name=outer.llm_explainer.backend.name,
                        tts_available=outer.tts_renderer is not None,
                    )
                    self._send_json(200, build_health_envelope(health).to_dict())
                    return
                self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/v1/explainer":
                    body = self._read_json()
                    request = parse_explainer_request_envelope(body)
                    result = outer.llm_explainer.run(request=request)
                    self._send_json(200, build_explainer_result_envelope(result).to_dict())
                    return
                if self.path == "/v1/asr/transcribe":
                    body = self._read_json()
                    request = parse_asr_transcribe_request_envelope(body)
                    response = outer._transcribe_asr(request)
                    self._send_json(200, build_asr_transcribe_response_envelope(response).to_dict())
                    return
                if self.path == "/v1/tts/render":
                    body = self._read_json()
                    render_request = parse_tts_render_request_envelope(body)
                    response = outer._render_tts(render_request)
                    self._send_json(200, build_tts_render_response_envelope(response).to_dict())
                    return
                if self.path == "/v1/tts/stream":
                    body = self._read_json()
                    render_request = parse_tts_render_request_envelope(body)
                    stream_render = outer._stream_render_tts(render_request)
                    self._send_tts_stream(stream_render)
                    return
                self._send_json(404, {"error": "not_found"})

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length > 0 else b"{}"
                return json.loads(raw.decode("utf-8"))

            def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_tts_stream(self, stream_render: TtsStreamRender) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.end_headers()

                start = build_tts_stream_start_envelope(
                    TtsStreamStart(
                        status=stream_render.status,
                        audio_format=stream_render.audio_format,
                        sample_rate_hz=stream_render.sample_rate_hz,
                        metadata=dict(stream_render.metadata),
                    )
                ).to_dict()
                self.wfile.write((json.dumps(start, ensure_ascii=False) + "\n").encode("utf-8"))

                total_frames = 0
                total_audio_bytes = 0
                final_status = stream_render.status
                end_metadata = dict(stream_render.metadata)
                try:
                    if stream_render.status == "completed":
                        for chunk in stream_render.iter_chunks():
                            total_frames += 1
                            total_audio_bytes += len(chunk)
                            frame = build_tts_audio_frame_envelope(
                                TtsAudioFrame(
                                    sequence_id=total_frames,
                                    audio_base64=base64.b64encode(chunk).decode("ascii"),
                                    audio_bytes=len(chunk),
                                    is_final=False,
                                )
                            ).to_dict()
                            self.wfile.write((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
                            self.wfile.flush()
                except Exception as exc:  # pragma: no cover
                    final_status = "error"
                    end_metadata.update(
                        {
                            "reason": "tts_stream_send_failed",
                            "error_type": type(exc).__name__,
                        }
                    )

                end = build_tts_stream_end_envelope(
                    TtsStreamEnd(
                        status=final_status,
                        total_frames=total_frames,
                        total_audio_bytes=(stream_render.total_audio_bytes or total_audio_bytes),
                        metadata=end_metadata,
                    )
                ).to_dict()
                self.wfile.write((json.dumps(end, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()

        return Handler

    def _build_asr_stream_server(self) -> socketserver.ThreadingTCPServer | None:
        if not hasattr(self.asr_backend, "open_realtime_session"):
            return None
        outer = self

        class RealtimeHandler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                session: Any | None = None
                try:
                    while True:
                        raw = self.rfile.readline()
                        if not raw:
                            break
                        payload = json.loads(raw.decode("utf-8"))
                        message_type = str(payload.get("message_type") or "")
                        if message_type == "asr_realtime_start_request":
                            request = parse_asr_realtime_start_request_envelope(payload)
                            session = outer._open_realtime_asr_session(request, emit_partial=self._emit_partial)
                            self._write_envelope(
                                build_asr_realtime_started_envelope(
                                    AsrRealtimeStarted(
                                        status="started",
                                        request_id=session.request_id,
                                        locale=request.locale,
                                        metadata={
                                            "backend": getattr(outer.asr_backend, "name", "unknown"),
                                            "sidecar_name": outer.config.sidecar_name,
                                        },
                                    )
                                ).to_dict()
                            )
                            continue
                        if session is None:
                            self._write_error("realtime_asr_session_not_started")
                            return
                        if message_type == "asr_realtime_chunk":
                            chunk = parse_asr_realtime_chunk_envelope(payload)
                            session.append_audio_chunk(base64.b64decode(chunk.audio_base64))
                            continue
                        if message_type == "asr_realtime_end_request":
                            request = parse_asr_realtime_end_request_envelope(payload)
                            result = session.finish(
                                started_at_ms=request.started_at_ms,
                                ended_at_ms=request.ended_at_ms,
                                capture_status=request.status,
                                capture_metadata=request.metadata,
                            )
                            self._write_envelope(
                                build_asr_realtime_final_envelope(
                                    AsrRealtimeFinal(
                                        status=result.status,
                                        transcript_text=result.transcript_text,
                                        confidence=result.confidence,
                                        started_at_ms=result.started_at_ms,
                                        ended_at_ms=result.ended_at_ms,
                                        locale=result.locale,
                                        metadata=dict(result.metadata),
                                    )
                                ).to_dict()
                            )
                            return
                except Exception as exc:
                    self._write_error(
                        "realtime_asr_stream_failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                finally:
                    if session is not None:
                        try:
                            session.close()
                        except Exception:
                            pass

            def _emit_partial(self, transcript_text: str) -> None:
                self._write_envelope(
                    build_asr_realtime_partial_envelope(
                        AsrRealtimePartial(
                            transcript_text=transcript_text,
                            locale="zh-CN",
                            metadata={"backend": getattr(outer.asr_backend, "name", "unknown")},
                        )
                    ).to_dict()
                )

            def _write_error(self, reason: str, **extra: Any) -> None:
                self._write_envelope(
                    build_asr_realtime_final_envelope(
                        AsrRealtimeFinal(
                            status="error",
                            transcript_text="",
                            confidence=None,
                            started_at_ms=0,
                            ended_at_ms=0,
                            locale="zh-CN",
                            metadata={"reason": reason, **extra},
                        )
                    ).to_dict()
                )

            def _write_envelope(self, payload: dict[str, Any]) -> None:
                self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()

        class _ThreadingRealtimeServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        return _ThreadingRealtimeServer(
            (self.config.asr_stream_host, self.config.asr_stream_port),
            RealtimeHandler,
        )

    def _open_realtime_asr_session(
        self,
        request: AsrRealtimeStartRequest,
        *,
        emit_partial: Any,
    ) -> Any:
        backend = self.asr_backend
        if not hasattr(backend, "open_realtime_session"):
            raise RuntimeError("realtime_asr_not_supported")
        realtime_backend = backend
        return realtime_backend.open_realtime_session(
            locale=request.locale,
            prompt=request.prompt,
            metadata=request.metadata,
            partial_callback=emit_partial,
        )

    def _render_tts(self, render_request: Any) -> TtsRenderResponse:
        if self.tts_renderer is None:
            return TtsRenderResponse(
                status="unsupported",
                audio_base64=None,
                audio_format="pcm_s16le",
                sample_rate_hz=16_000,
                metadata={"reason": "tts_renderer_unavailable"},
            )
        try:
            return self.tts_renderer.render(render_request)
        except Exception as exc:  # pragma: no cover
            return TtsRenderResponse(
                status="error",
                audio_base64=None,
                audio_format="pcm_s16le",
                sample_rate_hz=render_request.sample_rate_hz,
                metadata={
                    "reason": "tts_render_failed",
                    "error_type": type(exc).__name__,
                },
            )

    def _stream_frame_size_bytes(self) -> int:
        try:
            return max(int(os.getenv("ASURADA_VOICE_SIDECAR_STREAM_FRAME_BYTES", "8192")), 512)
        except ValueError:
            return 8192

    def _stream_render_tts(self, render_request: Any) -> TtsStreamRender:
        if self.tts_renderer is None:
            return TtsStreamRender(
                status="unsupported",
                audio_format="pcm_s16le",
                sample_rate_hz=render_request.sample_rate_hz,
                metadata={"reason": "tts_renderer_unavailable"},
                chunks=(),
                total_audio_bytes=0,
            )
        try:
            if hasattr(self.tts_renderer, "stream_render"):
                return self.tts_renderer.stream_render(
                    render_request,
                    frame_size_bytes=self._stream_frame_size_bytes(),
                )
            response = self._render_tts(render_request)
            return stream_render_from_response(
                response,
                frame_size_bytes=self._stream_frame_size_bytes(),
            )
        except Exception as exc:  # pragma: no cover
            return TtsStreamRender(
                status="error",
                audio_format="pcm_s16le",
                sample_rate_hz=render_request.sample_rate_hz,
                metadata={
                    "reason": "tts_stream_render_failed",
                    "error_type": type(exc).__name__,
                },
                chunks=(),
                total_audio_bytes=0,
            )

    def _transcribe_asr(self, asr_request: Any) -> AsrTranscribeResponse:
        if self.asr_backend is None:
            return AsrTranscribeResponse(
                status="unsupported",
                transcript_text="",
                confidence=None,
                started_at_ms=0,
                ended_at_ms=0,
                locale=asr_request.locale,
                metadata={"reason": "asr_backend_unavailable"},
            )
        try:
            return self.asr_backend.transcribe_audio(
                audio_bytes=base64.b64decode(asr_request.audio_base64),
                audio_format=asr_request.audio_format,
                locale=asr_request.locale,
                prompt=asr_request.prompt,
                metadata=asr_request.metadata,
            )
        except Exception as exc:  # pragma: no cover
            return AsrTranscribeResponse(
                status="error",
                transcript_text="",
                confidence=None,
                started_at_ms=0,
                ended_at_ms=0,
                locale=asr_request.locale,
                metadata={
                    "reason": "asr_transcribe_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )


__all__ = ["VoiceSidecarServer", "VoiceSidecarServerConfig"]

from __future__ import annotations

import io
import json
import os
import sys
import types
import wave
from typing import Any

from asurada.voice_sidecar_asr import DoubaoBigmodelStreamingWsSidecarAsrBackend


def _build_ws_success_frame(sequence: int, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return (
        bytes([0x11, 0x90, 0x10, 0x00])
        + int(sequence).to_bytes(4, byteorder="big", signed=True)
        + len(body).to_bytes(4, byteorder="big", signed=False)
        + body
    )


def _build_test_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


class _FakeTimeout(Exception):
    pass


class _FakeClosed(Exception):
    pass


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers = {"X-Tt-Logid": "fake-streaming-asr-logid"}
        self.sent_frames: list[bytes] = []
        self.closed = False
        self.timeout_value: float | None = None
        self._responses = [
            _build_ws_success_frame(
                1,
                {
                    "audio_info": {"duration": 0},
                    "result": {"text": ""},
                },
            ),
            _build_ws_success_frame(
                -1,
                {
                    "audio_info": {"duration": 620},
                    "result": {
                        "text": "阿斯拉达 后车差距",
                        "utterances": [{"text": "阿斯拉达 后车差距", "confidence": 0.93}],
                    },
                },
            ),
        ]

    def settimeout(self, value: float) -> None:
        self.timeout_value = value

    def send_binary(self, payload: bytes) -> None:
        self.sent_frames.append(payload)

    def recv(self) -> bytes:
        if self._responses:
            return self._responses.pop(0)
        raise _FakeTimeout("no_more_messages")

    def close(self) -> None:
        self.closed = True


def run_phase3_doubao_streaming_asr_backend_regression() -> dict[str, Any]:
    original_env = {
        key: os.environ.get(key)
        for key in (
            "ASURADA_DOUBAO_ASR_APP_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_STREAMING_ASR_RESOURCE_ID",
            "ASURADA_DOUBAO_STREAMING_ASR_CHUNK_MS",
        )
    }
    original_websocket = sys.modules.get("websocket")
    fake_socket = _FakeWebSocket()
    captured_headers: list[str] = []

    fake_websocket_module = types.SimpleNamespace(
        WebSocketTimeoutException=_FakeTimeout,
        WebSocketConnectionClosedException=_FakeClosed,
        create_connection=lambda url, timeout, header, enable_multithread=False: _capture_ws(
            fake_socket, header, captured_headers
        ),
    )

    try:
        os.environ["ASURADA_DOUBAO_ASR_APP_KEY"] = "test-stream-app"
        os.environ["ASURADA_DOUBAO_ASR_ACCESS_KEY"] = "test-stream-token"
        os.environ["ASURADA_DOUBAO_STREAMING_ASR_RESOURCE_ID"] = "volc.bigasr.sauc.duration"
        os.environ["ASURADA_DOUBAO_STREAMING_ASR_CHUNK_MS"] = "120"
        sys.modules["websocket"] = fake_websocket_module

        backend = DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
        result = backend.transcribe_audio(
            audio_bytes=_build_test_wav_bytes(),
            audio_format="wav",
            locale="zh-CN",
            prompt="阿斯拉达 后车差距",
            metadata={"case": "doubao_streaming_asr_regression"},
        )

        checks = {
            "recognized": result.status == "recognized",
            "text": result.transcript_text == "阿斯拉达 后车差距",
            "resource_id": (result.metadata or {}).get("resource_id") == "volc.bigasr.sauc.duration",
            "last_sequence": (result.metadata or {}).get("last_sequence") == -1,
            "request_headers": any(item == "X-Api-App-Key: test-stream-app" for item in captured_headers)
            and any(item == "X-Api-Access-Key: test-stream-token" for item in captured_headers)
            and any(item == "X-Api-Resource-Id: volc.bigasr.sauc.duration" for item in captured_headers),
            "sent_frames": len(fake_socket.sent_frames) >= 2,
            "closed": fake_socket.closed is True,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "result": result.to_dict(),
                "captured_headers": captured_headers,
                "sent_frame_count": len(fake_socket.sent_frames),
            },
        }
    finally:
        if original_websocket is None:
            sys.modules.pop("websocket", None)
        else:
            sys.modules["websocket"] = original_websocket
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _capture_ws(fake_socket: _FakeWebSocket, header: list[str], captured_headers: list[str]) -> _FakeWebSocket:
    captured_headers[:] = list(header)
    return fake_socket


if __name__ == "__main__":
    print(json.dumps(run_phase3_doubao_streaming_asr_backend_regression(), ensure_ascii=False, indent=2))

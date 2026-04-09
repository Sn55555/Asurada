from __future__ import annotations

import base64
import json
import os
import sys
import types
from typing import Any

from asurada.voice_sidecar_asr import (
    DoubaoBigmodelStreamingWsSidecarAsrBackend,
    DoubaoRealtimeAsrRecognizer,
)


def _build_ws_success_frame(sequence: int, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return (
        bytes([0x11, 0x90, 0x10, 0x00])
        + int(sequence).to_bytes(4, byteorder="big", signed=True)
        + len(body).to_bytes(4, byteorder="big", signed=False)
        + body
    )


class _FakeAudioCapture:
    def iter_events(self):
        yield types.SimpleNamespace(type="start", started_at_ms=1000, ended_at_ms=None, status="listening", metadata={}, audio_base64=None)
        yield types.SimpleNamespace(
            type="chunk",
            started_at_ms=None,
            ended_at_ms=None,
            status=None,
            metadata={},
            audio_base64=base64.b64encode(b"\x01\x02" * 1600).decode("ascii"),
        )
        yield types.SimpleNamespace(type="end", started_at_ms=1000, ended_at_ms=1600, status="recorded", metadata={"timeout": "silence_timeout"}, audio_base64=None)


class _FakeTimeout(Exception):
    pass


class _FakeClosed(Exception):
    pass


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers = {"X-Tt-Logid": "fake-realtime-asr-logid"}
        self.sent_frames: list[bytes] = []
        self.closed = False
        self._responses = [
            _build_ws_success_frame(
                1,
                {"audio_info": {"duration": 180}, "result": {"text": "阿斯拉达"}},
            ),
            _build_ws_success_frame(
                -1,
                {
                    "audio_info": {"duration": 620},
                    "result": {
                        "text": "阿斯拉达 后车差距",
                        "utterances": [{"text": "阿斯拉达 后车差距", "confidence": 0.94}],
                    },
                },
            ),
        ]

    def settimeout(self, value: float) -> None:
        return None

    def send_binary(self, payload: bytes) -> None:
        self.sent_frames.append(payload)

    def recv(self) -> bytes:
        if self._responses:
            return self._responses.pop(0)
        raise _FakeTimeout("no_more_messages")

    def close(self) -> None:
        self.closed = True


def run_phase3_doubao_realtime_asr_recognizer_regression() -> dict[str, Any]:
    original_env = {
        key: os.environ.get(key)
        for key in (
            "ASURADA_DOUBAO_ASR_APP_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_STREAMING_ASR_RESOURCE_ID",
        )
    }
    original_websocket = sys.modules.get("websocket")
    fake_socket = _FakeWebSocket()
    partials: list[str] = []

    fake_websocket_module = types.SimpleNamespace(
        WebSocketTimeoutException=_FakeTimeout,
        WebSocketConnectionClosedException=_FakeClosed,
        create_connection=lambda url, timeout, header, enable_multithread=False: fake_socket,
    )

    try:
        os.environ["ASURADA_DOUBAO_ASR_APP_KEY"] = "test-realtime-app"
        os.environ["ASURADA_DOUBAO_ASR_ACCESS_KEY"] = "test-realtime-token"
        os.environ["ASURADA_DOUBAO_STREAMING_ASR_RESOURCE_ID"] = "volc.bigasr.sauc.duration"
        sys.modules["websocket"] = fake_websocket_module

        recognizer = DoubaoRealtimeAsrRecognizer(
            audio_capture=_FakeAudioCapture(),
            backend=DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env(),
            partial_callback=partials.append,
        )
        result = recognizer.listen_once()
        checks = {
            "recognized": result.status == "recognized",
            "text": result.transcript_text == "阿斯拉达 后车差距",
            "partial_callback": partials == ["阿斯拉达"],
            "partial_metadata": (result.metadata or {}).get("partial_transcript") == "阿斯拉达",
            "provider": (result.metadata or {}).get("provider") == "doubao_bigmodel_streaming_ws_sidecar_asr_backend",
            "chunk_count": (result.metadata or {}).get("chunk_count") == 1,
            "closed": fake_socket.closed is True,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "result": result.to_dict(),
                "partials": partials,
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


if __name__ == "__main__":
    print(json.dumps(run_phase3_doubao_realtime_asr_recognizer_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

from asurada.voice_sidecar_asr import VoiceSidecarAsrRecognitionResult, VoiceSidecarRealtimeAsrRecognizer
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig


class _FakeRealtimeSession:
    def __init__(self, *, partial_callback) -> None:  # type: ignore[no-untyped-def]
        self.request_id = "fake-realtime-session"
        self.locale = "zh-CN"
        self.partial_callback = partial_callback
        self.chunks: list[bytes] = []
        self.closed = False

    def append_audio_chunk(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        joined = b"".join(self.chunks)
        if len(joined) >= 4 and self.partial_callback is not None:
            self.partial_callback("阿斯拉达")

    def finish(
        self,
        *,
        started_at_ms: int,
        ended_at_ms: int,
        capture_status: str,
        capture_metadata: dict[str, Any] | None = None,
    ) -> VoiceSidecarAsrRecognitionResult:
        return VoiceSidecarAsrRecognitionResult(
            status="recognized",
            transcript_text="阿斯拉达 后车差距",
            confidence=0.92,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            locale="zh-CN",
            metadata={
                "backend": "fake_sidecar_realtime_backend",
                "capture_status": capture_status,
                "capture_metadata": dict(capture_metadata or {}),
                "partial_transcript": "阿斯拉达",
                "chunk_count": len(self.chunks),
            },
        )

    def close(self) -> None:
        self.closed = True


class _FakeRealtimeBackend:
    name = "fake_realtime_backend"

    def transcribe_audio(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("transcribe_audio should not be used in realtime regression")

    def open_realtime_session(self, *, locale, prompt=None, metadata=None, partial_callback=None):  # type: ignore[no-untyped-def]
        return _FakeRealtimeSession(partial_callback=partial_callback)


class _FakeAudioCapture:
    class config:
        command_timeout_s = 5.0

    def iter_events(self):
        yield type("Evt", (), {"type": "start", "started_at_ms": 1000, "ended_at_ms": None, "status": "listening", "metadata": {}, "audio_base64": None})
        yield type(
            "Evt",
            (),
            {
                "type": "chunk",
                "started_at_ms": None,
                "ended_at_ms": None,
                "status": None,
                "metadata": {},
                "audio_base64": base64.b64encode(b"\x01\x02" * 1600).decode("ascii"),
            },
        )
        yield type(
            "Evt",
            (),
            {
                "type": "end",
                "started_at_ms": None,
                "ended_at_ms": 1600,
                "status": "recorded",
                "metadata": {"timeout": "silence_timeout"},
                "audio_base64": None,
            },
        )


def run_phase3_voice_sidecar_realtime_asr_regression() -> dict[str, Any]:
    server = VoiceSidecarServer(
        config=VoiceSidecarServerConfig(
            host="127.0.0.1",
            port=18798,
            asr_stream_host="127.0.0.1",
            asr_stream_port=18799,
            sidecar_name="test_sidecar",
            tts_enabled=False,
        ),
        asr_backend=_FakeRealtimeBackend(),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.05)
    partials: list[str] = []
    try:
        recognizer = VoiceSidecarRealtimeAsrRecognizer(
            audio_capture=_FakeAudioCapture(),
            host="127.0.0.1",
            port=18799,
            partial_callback=partials.append,
        )
        result = recognizer.listen_once()
    finally:
        server.shutdown()
        server_thread.join(timeout=1.0)

    checks = {
        "recognized": result.status == "recognized",
        "transcript": result.transcript_text == "阿斯拉达 后车差距",
        "partial_callback": partials == ["阿斯拉达"],
        "partial_metadata": (result.metadata or {}).get("partial_transcript") == "阿斯拉达",
        "chunk_count": (result.metadata or {}).get("chunk_count") == 1,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "result": result.to_dict(),
            "partials": partials,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_sidecar_realtime_asr_regression(), ensure_ascii=False, indent=2))

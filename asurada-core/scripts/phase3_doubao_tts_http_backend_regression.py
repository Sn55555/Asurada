from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import threading
import time
import wave
from typing import Any

from asurada.voice_sidecar_protocol import TtsRenderRequest
from asurada.voice_sidecar_tts import DoubaoStreamingHttpSidecarTtsRenderer


class _State:
    headers: dict[str, str] = {}
    body: dict[str, Any] = {}


class _FakeDoubaoTtsHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        _State.headers = {key: value for key, value in self.headers.items()}
        _State.body = json.loads(raw.decode("utf-8"))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()

        frames = [
            b"\x01\x02" * 400,
            b"\x03\x04" * 400,
        ]
        for chunk in frames:
            event = {
                "event": 350,
                "code": 0,
                "message": "ok",
                "data": base64.b64encode(chunk).decode("ascii"),
            }
            self.wfile.write(f"event: message\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        end = {
            "event": 152,
            "code": 0,
            "message": "done",
            "data": {"status": "completed"},
        }
        self.wfile.write(f"event: message\ndata: {json.dumps(end, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def run_phase3_doubao_tts_http_backend_regression() -> dict[str, object]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDoubaoTtsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        renderer = DoubaoStreamingHttpSidecarTtsRenderer(
            stream_url=f"http://127.0.0.1:{server.server_address[1]}/api/v3/tts/unidirectional/sse",
            app_id="test-app-id",
            access_key="test-access-key",
            resource_id="volc.service_type.10029",
            default_speaker="zh_male_ahu_conversation_wvae_bigtts",
        )
        request = TtsRenderRequest(
            text="当前整体先守住后车，再看处罚窗口。",
            persona_id="asurada_default",
            voice_profile_id="asurada_cn_ai_v1",
            audio_format="pcm_s16le",
            sample_rate_hz=16000,
        )
        streamed = renderer.stream_render(request, frame_size_bytes=512)
        chunks = tuple(streamed.iter_chunks())
        rendered = renderer.render(request)
    finally:
        server.shutdown()
        thread.join(timeout=1.0)

    headers_lower = {key.lower(): value for key, value in _State.headers.items()}
    wav_bytes = base64.b64decode(rendered.audio_base64 or "")
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        checks = {
            "stream_completed": streamed.status == "completed",
            "stream_pcm_format": streamed.audio_format == "pcm_s16le",
            "stream_chunk_count": len(chunks) == 4,
            "header_app_id": headers_lower.get("x-api-app-id") == "test-app-id",
            "header_access_key": headers_lower.get("x-api-access-key") == "test-access-key",
            "header_resource_id": headers_lower.get("x-api-resource-id") == "volc.service_type.10029",
            "payload_speaker": (_State.body.get("req_params") or {}).get("speaker") == "zh_male_ahu_conversation_wvae_bigtts",
            "payload_sample_rate": int((((_State.body.get("req_params") or {}).get("audio_params") or {}).get("sample_rate")) or 0)
            == 16000,
            "rendered_wav": rendered.status == "completed" and rendered.audio_format == "wav",
            "rendered_mono": wav_file.getnchannels() == 1,
            "rendered_sample_rate": wav_file.getframerate() == 16000,
            "rendered_non_empty": wav_file.getnframes() > 0,
        }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "metadata": rendered.metadata,
            "request_body": _State.body,
            "chunk_lengths": [len(chunk) for chunk in chunks],
            "wav_bytes": len(wav_bytes),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_doubao_tts_http_backend_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Any

from asurada.voice_sidecar_asr import DoubaoFlashHttpSidecarAsrBackend


class _Handler(BaseHTTPRequestHandler):
    last_request: dict[str, Any] | None = None
    last_headers: dict[str, str] | None = None
    last_path: str | None = None

    def do_POST(self) -> None:  # noqa: N802
        _Handler.last_path = self.path
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        _Handler.last_request = json.loads(body)
        _Handler.last_headers = dict(self.headers)
        response = {
            "result": {
                "text": "阿斯拉达 后车差距",
                "utterances": [
                    {
                        "text": "阿斯拉达 后车差距",
                        "confidence": 0.91,
                    }
                ],
            }
        }
        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Api-Status-Code", "20000000")
        self.send_header("X-Api-Message", "Success")
        self.send_header("X-Tt-Logid", "fake-doubao-asr-logid")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_phase3_doubao_asr_http_backend_regression() -> dict[str, Any]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_env = {
        key: os.environ.get(key)
        for key in (
            "ASURADA_DOUBAO_ASR_URL",
            "ASURADA_DOUBAO_ASR_APP_KEY",
            "ASURADA_DOUBAO_ASR_ACCESS_KEY",
            "ASURADA_DOUBAO_ASR_RESOURCE_ID",
            "ASURADA_DOUBAO_ASR_MODEL_NAME",
            "ASURADA_DOUBAO_ASR_BOOSTING_TABLE_NAME",
        )
    }
    try:
        os.environ["ASURADA_DOUBAO_ASR_URL"] = f"http://127.0.0.1:{server.server_port}/api/v3/auc/bigmodel/recognize/flash"
        os.environ["ASURADA_DOUBAO_ASR_APP_KEY"] = "doubao-asr-test-app"
        os.environ["ASURADA_DOUBAO_ASR_ACCESS_KEY"] = "doubao-asr-test-token"
        os.environ["ASURADA_DOUBAO_ASR_RESOURCE_ID"] = "volc.bigasr.auc_turbo"
        os.environ["ASURADA_DOUBAO_ASR_MODEL_NAME"] = "bigmodel"
        os.environ["ASURADA_DOUBAO_ASR_BOOSTING_TABLE_NAME"] = "asurada-hotwords"

        backend = DoubaoFlashHttpSidecarAsrBackend.from_env()
        result = backend.transcribe_audio(
            audio_bytes=b"fake-audio",
            audio_format="wav",
            locale="zh-CN",
            prompt="阿斯拉达 后车差距",
            metadata={"case": "doubao_asr_http_regression"},
        )
        sent = _Handler.last_request or {}
        sent_headers = _Handler.last_headers or {}
        normalized_headers = {str(key).lower(): value for key, value in sent_headers.items()}
        checks = {
            "recognized": result.status == "recognized",
            "text": result.transcript_text == "阿斯拉达 后车差距",
            "request_path": _Handler.last_path == "/api/v3/auc/bigmodel/recognize/flash",
            "auth_headers": normalized_headers.get("x-api-app-key") == "doubao-asr-test-app"
            and normalized_headers.get("x-api-access-key") == "doubao-asr-test-token",
            "resource_header": normalized_headers.get("x-api-resource-id") == "volc.bigasr.auc_turbo",
            "audio_sent": bool(((sent.get("audio") or {}).get("data"))),
            "model_name": ((sent.get("request") or {}).get("model_name")) == "bigmodel",
            "boosting_table_name": ((sent.get("request") or {}).get("boosting_table_name")) == "asurada-hotwords",
            "request_id_present": bool(normalized_headers.get("x-api-request-id")),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "request_sent": sent,
                "headers_sent": sent_headers,
                "result": result.to_dict(),
            },
        }
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server.shutdown()
        thread.join(timeout=1.0)
        server.server_close()


if __name__ == "__main__":
    print(json.dumps(run_phase3_doubao_asr_http_backend_regression(), ensure_ascii=False, indent=2))

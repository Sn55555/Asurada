from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Any

from asurada.llm_explainer import (
    DoubaoArkChatCompletionsLlmExplainerBackend,
    LlmExplainer,
    LlmExplainerRequest,
    resolve_default_llm_explainer_backend,
)


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
            "id": "chatcmpl_test",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "status": "answerable",
                                "answer_text": "当前整体先守住后车，再看处罚窗口。",
                                "confidence": 0.82,
                                "reason_fields": ["rear_pressure", "penalty_window"],
                                "requires_confirmation": False,
                                "metadata": {"provider": "fake_doubao_chat"},
                            },
                            ensure_ascii=False,
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_phase3_doubao_chat_backend_regression() -> dict[str, Any]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_env = {
        key: os.environ.get(key)
        for key in (
            "ASURADA_LLM_SIDECAR_BACKEND",
            "ASURADA_DOUBAO_API_STYLE",
            "ASURADA_DOUBAO_API_KEY",
            "ARK_API_KEY",
            "ASURADA_DOUBAO_MODEL",
            "ASURADA_DOUBAO_ENDPOINT_ID",
            "ASURADA_DOUBAO_BASE_URL",
        )
    }
    try:
        os.environ["ASURADA_LLM_SIDECAR_BACKEND"] = "doubao"
        os.environ["ASURADA_DOUBAO_API_STYLE"] = "chat_completions"
        os.environ["ASURADA_DOUBAO_API_KEY"] = "doubao-chat-test-key"
        os.environ["ASURADA_DOUBAO_MODEL"] = "ep-test-doubao-chat-001"
        os.environ["ASURADA_DOUBAO_BASE_URL"] = f"http://127.0.0.1:{server.server_port}/api/v3"

        resolved = resolve_default_llm_explainer_backend()
        backend = DoubaoArkChatCompletionsLlmExplainerBackend.from_env()
        explainer = LlmExplainer(backend=backend, default_timeout_ms=800)
        request = LlmExplainerRequest(
            interaction_session_id="runtime:test",
            turn_id="turn:test",
            request_id="req:test",
            query_kind="overall_situation",
            normalized_query_text="整体形势怎么样",
            route_reason="explainer_query",
            timeout_ms=800,
            state_summary={"summary_version": "v1", "state_snapshot": {"track": "Austria"}},
            metadata={"case": "doubao_chat_regression"},
        )
        result = explainer.run(request=request)
        response = dict(result.response or {})
        sent = _Handler.last_request or {}
        sent_headers = _Handler.last_headers or {}
        normalized_headers = {str(key).lower(): value for key, value in sent_headers.items()}
        checks = {
            "resolved_backend_name": getattr(resolved, "name", "") == "doubao_ark_llm_explainer",
            "completed": result.status == "completed",
            "parsed_response": response.get("status") == "answerable"
            and response.get("metadata", {}).get("provider") == "fake_doubao_chat",
            "auth_header": normalized_headers.get("authorization") == "Bearer doubao-chat-test-key",
            "chat_path_used": _Handler.last_path == "/api/v3/chat/completions",
            "model_used": sent.get("model") == "ep-test-doubao-chat-001",
            "persona_instructions": "calm racing copilot" in str((sent.get("messages") or [{}])[0].get("content") or ""),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "request_sent": sent,
                "headers_sent": sent_headers,
                "path": _Handler.last_path,
                "resolved_backend_name": getattr(resolved, "name", ""),
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
    print(json.dumps(run_phase3_doubao_chat_backend_regression(), ensure_ascii=False, indent=2))

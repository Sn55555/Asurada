from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Any

from asurada.llm_explainer import OpenAiResponsesLlmExplainerBackend, LlmExplainer, LlmExplainerRequest


class _Handler(BaseHTTPRequestHandler):
    last_request: dict[str, Any] | None = None
    last_headers: dict[str, str] | None = None

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        _Handler.last_request = json.loads(body)
        _Handler.last_headers = dict(self.headers)
        response = {
            "id": "resp_test",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "status": "answerable",
                                    "answer_text": "当前整体先守住后车，再看处罚窗口。",
                                    "confidence": 0.81,
                                    "reason_fields": ["rear_pressure", "penalty_window"],
                                    "requires_confirmation": False,
                                    "metadata": {"provider": "fake_openai"},
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
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


def run_phase3_openai_llm_backend_regression() -> dict[str, Any]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = OpenAiResponsesLlmExplainerBackend(
            api_key="test-key",
            model="gpt-5.2-mini",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            organization="org_test",
            project="proj_test",
        )
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
            metadata={"case": "regression"},
        )
        result = explainer.run(request=request)
        response = dict(result.response or {})
        sent = _Handler.last_request or {}
        sent_headers = _Handler.last_headers or {}
        normalized_headers = {str(key).lower(): value for key, value in sent_headers.items()}
        checks = {
            "completed": result.status == "completed",
            "parsed_response": response.get("status") == "answerable"
            and response.get("answer_text") == "当前整体先守住后车，再看处罚窗口。",
            "persona_instructions": "calm racing copilot" in str(sent.get("instructions") or ""),
            "auth_header": normalized_headers.get("authorization") == "Bearer test-key",
            "org_header": normalized_headers.get("openai-organization") == "org_test",
            "project_header": normalized_headers.get("openai-project") == "proj_test",
            "path_used": sent.get("model") == "gpt-5.2-mini"
            and sent.get("text", {}).get("format", {}).get("type") == "json_schema",
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
        server.shutdown()
        thread.join(timeout=1.0)
        server.server_close()


if __name__ == "__main__":
    print(json.dumps(run_phase3_openai_llm_backend_regression(), ensure_ascii=False, indent=2))

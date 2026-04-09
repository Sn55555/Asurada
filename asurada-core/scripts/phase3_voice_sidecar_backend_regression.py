from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from asurada.llm_explainer import (
    LlmExplainer,
    LlmExplainerRequest,
    resolve_default_llm_explainer_backend,
)
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig


class SuccessBackend:
    name = "embedded_success_backend"

    def explain(self, request):  # type: ignore[no-untyped-def]
        return {
            "status": "answerable",
            "answer_text": "当前先稳住节奏，后车已接近 DRS 线。",
            "confidence": 0.81,
            "reason_fields": ["rear_pressure"],
            "requires_confirmation": False,
            "metadata": {"provider": "embedded_success_backend"},
        }


def run_phase3_voice_sidecar_backend_regression() -> dict[str, Any]:
    server = VoiceSidecarServer(
        config=VoiceSidecarServerConfig(host="127.0.0.1", port=0, sidecar_name="test_backend_sidecar", tts_enabled=False),
        llm_explainer=LlmExplainer(backend=SuccessBackend(), default_timeout_ms=1000),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)

    previous = {key: os.environ.get(key) for key in (
        "ASURADA_LLM_SIDECAR_BACKEND",
        "ASURADA_VOICE_SIDECAR_BASE_URL",
    )}
    os.environ["ASURADA_LLM_SIDECAR_BACKEND"] = "voice_sidecar"
    os.environ["ASURADA_VOICE_SIDECAR_BASE_URL"] = f"http://127.0.0.1:{server.listening_port}"
    try:
        backend = resolve_default_llm_explainer_backend()
        explainer = LlmExplainer(backend=backend, default_timeout_ms=1200)
        request = LlmExplainerRequest(
            interaction_session_id="runtime:test-sidecar",
            turn_id="turn:test-sidecar",
            request_id="req:test-sidecar",
            query_kind="overall_situation",
            normalized_query_text="整体形势怎么样",
            route_reason="explainer_query",
            timeout_ms=1200,
            state_summary={"summary_version": "v1", "state_snapshot": {"track": "Austria"}},
            metadata={"case": "voice_sidecar_backend_regression"},
        )
        result = explainer.run(request=request)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server.shutdown()
        thread.join(timeout=1.0)

    checks = {
        "resolved_backend_name": backend.name == "voice_sidecar_llm_explainer",
        "completed": result.status == "completed",
        "sidecar_text": (result.response or {}).get("answer_text") == "当前先稳住节奏，后车已接近 DRS 线。",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "backend_name": backend.name,
            "result": result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_sidecar_backend_regression(), ensure_ascii=False, indent=2))

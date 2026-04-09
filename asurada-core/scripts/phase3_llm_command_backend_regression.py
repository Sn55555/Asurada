from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from asurada.llm_explainer import CommandLlmExplainerBackend, LlmExplainer, LlmExplainerRequest


def run_phase3_llm_command_backend_regression() -> dict[str, Any]:
    stub_path = Path("asurada-core/scripts/phase3_llm_sidecar_stub.py").resolve()
    backend = CommandLlmExplainerBackend(command=(sys.executable, str(stub_path)))
    explainer = LlmExplainer(backend=backend, default_timeout_ms=800)
    request = LlmExplainerRequest(
        interaction_session_id="runtime:test",
        turn_id="turn:test",
        request_id="req:test",
        query_kind="overall_situation",
        normalized_query_text="整体形势怎么样",
        route_reason="explainer_query",
        timeout_ms=800,
        state_summary={"summary_version": "v1"},
        metadata={},
    )
    result = explainer.run(request=request)
    response = dict(result.response or {})
    checks = {
        "completed": result.status == "completed",
        "answerable": response.get("status") == "answerable",
        "text_present": bool(str(response.get("answer_text") or "").strip()),
        "backend_name": result.backend_name == "command_llm_explainer",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "request": request.to_dict(),
            "result": result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_llm_command_backend_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

from regression_support import emit_result

import json
import threading
import time
from typing import Any

from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.llm_explainer import LlmExplainer, LlmExplainerRequest
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from asurada.voice_sidecar_protocol import TtsRenderRequest, TtsRenderResponse


class SuccessBackend:
    name = "success_backend"

    def explain(self, request):  # type: ignore[no-untyped-def]
        return {
            "status": "answerable",
            "answer_text": "当前整体先守住后车，再看处罚窗口。",
            "confidence": 0.83,
            "reason_fields": ["state_snapshot.gap_behind_s", "state_snapshot.penalties.num_unserved_drive_through_pens"],
            "requires_confirmation": False,
            "metadata": {"provider": "sidecar_regression"},
        }


class FakeTtsRenderer:
    name = "fake_tts_renderer"

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        return TtsRenderResponse(
            status="completed",
            audio_base64="ZmFrZS13YXY=",
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name, "text": request.text},
        )


def run_phase3_voice_sidecar_server_regression() -> dict[str, Any]:
    port = 18788
    server = VoiceSidecarServer(
        config=VoiceSidecarServerConfig(host="127.0.0.1", port=port, sidecar_name="test_sidecar", tts_enabled=False),
        llm_explainer=LlmExplainer(backend=SuccessBackend(), default_timeout_ms=1000),
        tts_renderer=FakeTtsRenderer(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        client = VoiceSidecarClient(VoiceSidecarClientConfig(base_url=f"http://127.0.0.1:{port}", timeout_ms=1000))
        health = client.healthz()
        request = LlmExplainerRequest(
            interaction_session_id="runtime:test",
            turn_id="turn:test",
            request_id="req:test",
            query_kind="overall_situation",
            normalized_query_text="整体形势怎么样",
            route_reason="explainer_query",
            timeout_ms=1000,
            state_summary={"summary_version": "v1", "state_snapshot": {"track": "Austria", "gap_behind_s": 0.6, "penalties": {"num_unserved_drive_through_pens": 1}}},
            metadata={"case": "voice_sidecar_server_regression"},
        )
        explain_result = client.explain(request=request)
        tts_result = client.render_tts(
            request=TtsRenderRequest(
                text="当前整体先守住后车，再看处罚窗口。",
                persona_id="asurada_default",
                voice_profile_id="asurada_cn_ai_v1",
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=1.0)

    checks = {
        "health_ok": health.status == "ok" and health.sidecar_name == "test_sidecar",
        "health_backend_name": health.llm_backend_name == "success_backend",
        "health_tts_available": health.tts_available is True,
        "explainer_completed": explain_result.status == "completed",
        "explainer_text": (explain_result.response or {}).get("answer_text") == "当前整体先守住后车，再看处罚窗口。",
        "tts_completed": tts_result.status == "completed" and tts_result.audio_base64 == "ZmFrZS13YXY=",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "health": health.to_dict(),
            "explain_result": explain_result.to_dict(),
            "tts_result": tts_result.to_dict(),
        },
    }


if __name__ == "__main__":
    emit_result(run_phase3_voice_sidecar_server_regression())

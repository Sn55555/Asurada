from __future__ import annotations

import json
import threading
import time
from typing import Any

from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.llm_explainer import LlmExplainer
from asurada.voice_sidecar_protocol import TtsRenderRequest, TtsRenderResponse
from asurada.voice_sidecar_tts import TtsStreamRender
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig


class FakeStreamingRenderer:
    name = "fake_streaming_renderer"

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        import base64

        raw_audio = b"RIFF" + (b"\x01\x02" * 6000)
        return TtsRenderResponse(
            status="completed",
            audio_base64=base64.b64encode(raw_audio).decode("ascii"),
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name},
        )

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        def _iter() -> Any:
            for chunk in (b"RIFF" + (b"\x01\x02" * 512), b"\x03\x04" * 1024):
                yield chunk

        return TtsStreamRender(
            status="completed",
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name, "mode": "generator"},
            chunks=(),
            total_audio_bytes=0,
            chunk_iter=_iter(),
        )


def run_phase3_voice_sidecar_stream_regression() -> dict[str, Any]:
    port = 18790
    server = VoiceSidecarServer(
        config=VoiceSidecarServerConfig(host="127.0.0.1", port=port, sidecar_name="stream_sidecar", tts_enabled=False),
        llm_explainer=LlmExplainer(),
        tts_renderer=FakeStreamingRenderer(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        client = VoiceSidecarClient(VoiceSidecarClientConfig(base_url=f"http://127.0.0.1:{port}", timeout_ms=1000))
        start, frames, end = client.stream_tts(
            request=TtsRenderRequest(
                text="当前整体先守住后车，再看处罚窗口。",
                persona_id="asurada_default",
                voice_profile_id="asurada_cn_ai_v1",
            )
        )
        collected = client.collect_streamed_tts(
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
        "start_completed": start.status == "completed",
        "has_frames": len(frames) >= 2,
        "frame_sequence": [frame.sequence_id for frame in frames] == list(range(1, len(frames) + 1)),
        "end_completed": end.status == "completed",
        "collected_completed": collected.status == "completed",
        "collected_stream_meta": int(collected.metadata.get("stream_total_frames") or 0) == len(frames),
        "generator_mode": str(start.metadata.get("mode") or "") == "generator",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "start": start.to_dict(),
            "frame_count": len(frames),
            "end": end.to_dict(),
            "collected": collected.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_sidecar_stream_regression(), ensure_ascii=False, indent=2))

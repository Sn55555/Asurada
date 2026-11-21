from __future__ import annotations

from regression_support import emit_result

import base64
import json
import threading
import time
from typing import Any

from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.voice_sidecar_protocol import AsrTranscribeRequest, AsrTranscribeResponse
from asurada.task_runtime import TaskContext
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig


class FakeAsrBackend:
    name = "fake_asr_backend"

    def transcribe_audio(  # type: ignore[no-untyped-def]
        self,
        *,
        audio_bytes,
        audio_format,
        locale,
        prompt=None,
        metadata=None,
    ) -> AsrTranscribeResponse:
        return AsrTranscribeResponse(
            status="recognized",
            transcript_text="阿斯拉达 后车差距",
            confidence=0.91,
            started_at_ms=1_777_600_000_000,
            ended_at_ms=1_777_600_000_420,
            locale=locale,
            metadata={
                "backend": self.name,
                "audio_bytes": len(audio_bytes),
                "audio_format": audio_format,
                "prompt": prompt,
                "request_metadata": dict(metadata or {}),
            },
        )


def run_phase3_voice_sidecar_asr_regression() -> dict[str, Any]:
    server = VoiceSidecarServer(
        config=VoiceSidecarServerConfig(host="127.0.0.1", port=0, sidecar_name="test_asr_sidecar", tts_enabled=False),
        asr_backend=FakeAsrBackend(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        client = VoiceSidecarClient(
            VoiceSidecarClientConfig(base_url=f"http://127.0.0.1:{server.listening_port}", timeout_ms=1000)
        )
        result = client.transcribe_asr(
            request=AsrTranscribeRequest(
                audio_base64=base64.b64encode(b"fake-wav").decode("ascii"),
                audio_format="wav",
                locale="zh-CN",
                prompt="阿斯拉达 后车差距",
                metadata={"case": "voice_sidecar_asr_regression"},
            )
        )
        contextual_result = client.transcribe_asr(
            request=AsrTranscribeRequest(audio_base64=base64.b64encode(b'fake-wav').decode('ascii'),
                audio_format='wav',locale='zh-CN',metadata={'case':'context-request'}),
            context=TaskContext.start('http-asr-integration',1000),
        )
    finally:
        server.shutdown()
        thread.join(timeout=1.0)

    checks = {
        "recognized": result.status == "recognized",
        "contextual_http_request_parsed": contextual_result.status=='recognized' and contextual_result.transcript_text==result.transcript_text,
        "contextual_metadata_preserved": contextual_result.metadata['request_metadata']['case']=='context-request',
        "text": result.transcript_text == "阿斯拉达 后车差距",
        "backend": (result.metadata or {}).get("backend") == "fake_asr_backend",
        "metadata_passthrough": ((result.metadata or {}).get("request_metadata") or {}).get("case")
        == "voice_sidecar_asr_regression",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "result": result.to_dict(),
        },
    }


if __name__ == "__main__":
    emit_result(run_phase3_voice_sidecar_asr_regression())

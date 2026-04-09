from __future__ import annotations

import base64
import json
import wave
from io import BytesIO

from asurada.voice_sidecar_protocol import TtsRenderRequest
from asurada.voice_sidecar_tts import MacOSSaySidecarTtsRenderer


def run_phase3_voice_sidecar_tts_regression() -> dict[str, object]:
    if not MacOSSaySidecarTtsRenderer.env_ready():
        return {
            "passed": True,
            "checks": {"skipped": True},
            "analysis": {"reason": "macos_say_renderer_unavailable"},
        }

    renderer = MacOSSaySidecarTtsRenderer.from_env()
    request = TtsRenderRequest(
        text="阿斯拉达音频导出测试",
        persona_id="asurada_default",
        voice_profile_id="asurada_cn_ai_v1",
        audio_format="pcm_s16le",
    )
    result = renderer.render(request)
    streamed = renderer.stream_render(request, frame_size_bytes=2048)
    audio_bytes = base64.b64decode(result.audio_base64 or "")
    with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
        checks = {
            "completed": result.status == "completed",
            "wav_format": result.audio_format == "wav",
            "mono": wav_file.getnchannels() == 1,
            "sample_rate": wav_file.getframerate() == 16000,
            "sample_width": wav_file.getsampwidth() == 2,
            "non_empty": wav_file.getnframes() > 0,
            "stream_completed": streamed.status == "completed",
            "stream_chunks": len(streamed.chunks) >= 1,
            "stream_pcm_format": streamed.audio_format == "pcm_s16le",
            "stream_total_bytes": streamed.total_audio_bytes > 0 and streamed.total_audio_bytes < len(audio_bytes),
        }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "metadata": result.metadata,
            "audio_bytes": len(audio_bytes),
            "stream_chunk_count": len(streamed.chunks),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_voice_sidecar_tts_regression(), ensure_ascii=False, indent=2))

from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import wave

from asurada.voice_sidecar_protocol import TtsRenderRequest
from asurada.voice_sidecar_tts import DoubaoStreamingHttpSidecarTtsRenderer


def run_phase3_doubao_tts_smoke(*, text: str, output_path: str | None) -> dict[str, object]:
    renderer = DoubaoStreamingHttpSidecarTtsRenderer.from_env()
    request = TtsRenderRequest(
        text=text,
        persona_id="asurada_default",
        voice_profile_id="asurada_cn_ai_v1",
        audio_format="pcm_s16le",
        sample_rate_hz=16000,
    )

    start_ts = time.perf_counter()
    stream = renderer.stream_render(request, frame_size_bytes=4096)
    first_chunk_ms: float | None = None
    chunks: list[bytes] = []
    total_bytes = 0
    for chunk in stream.iter_chunks():
        if first_chunk_ms is None:
            first_chunk_ms = (time.perf_counter() - start_ts) * 1000.0
        chunks.append(chunk)
        total_bytes += len(chunk)
    stream_done_ms = (time.perf_counter() - start_ts) * 1000.0

    rendered = renderer.render(request)
    wav_bytes = base64.b64decode(rendered.audio_base64 or "")
    with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
        wav_meta = {
            "channels": wav_file.getnchannels(),
            "sample_width_bytes": wav_file.getsampwidth(),
            "sample_rate_hz": wav_file.getframerate(),
            "frames": wav_file.getnframes(),
            "duration_ms": round((wav_file.getnframes() / max(wav_file.getframerate(), 1)) * 1000.0, 2),
        }

    final_output_path = Path(output_path) if output_path else Path(tempfile.gettempdir()) / "asurada_doubao_tts_smoke.wav"
    final_output_path.write_bytes(wav_bytes)

    checks = {
        "stream_completed": stream.status == "completed",
        "first_chunk_seen": first_chunk_ms is not None,
        "stream_has_audio": total_bytes > 0,
        "render_completed": rendered.status == "completed",
        "wav_mono": wav_meta["channels"] == 1,
        "wav_sample_rate": wav_meta["sample_rate_hz"] == 16000,
        "wav_non_empty": wav_meta["frames"] > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "renderer": stream.metadata,
            "first_chunk_ms": None if first_chunk_ms is None else round(first_chunk_ms, 2),
            "stream_done_ms": round(stream_done_ms, 2),
            "stream_chunk_count": len(chunks),
            "stream_total_bytes": total_bytes,
            "wav_bytes": len(wav_bytes),
            "wav_meta": wav_meta,
            "output_path": str(final_output_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test Doubao/Volc streaming TTS sidecar renderer.")
    parser.add_argument("--text", default="当前整体先守住后车，再看处罚窗口。")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    print(
        json.dumps(
            run_phase3_doubao_tts_smoke(
                text=args.text,
                output_path=(args.output or None),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

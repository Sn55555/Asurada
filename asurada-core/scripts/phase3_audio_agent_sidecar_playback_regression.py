from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import wave

from asurada.audio_agent_client import VoiceSidecarClient, VoiceSidecarClientConfig
from asurada.llm_explainer import LlmExplainer
from asurada.voice_sidecar_protocol import TtsRenderRequest, TtsRenderResponse
from asurada.voice_sidecar_server import VoiceSidecarServer, VoiceSidecarServerConfig
from asurada.voice_sidecar_tts import TtsStreamRender


class FakePlaybackRenderer:
    name = "fake_playback_renderer"

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            with wave.open(str(temp_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(request.sample_rate_hz)
                wav_file.writeframes(b"\x00\x00" * 1600)
            audio_bytes = temp_path.read_bytes()
        finally:
            temp_path.unlink(missing_ok=True)
        import base64

        return TtsRenderResponse(
            status="completed",
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            audio_format="wav",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name},
        )


class FakeStreamingPcmRenderer:
    name = "fake_streaming_pcm_renderer"

    def render(self, request: TtsRenderRequest) -> TtsRenderResponse:
        import base64

        raw_audio = b"\x34\x12" * 1600
        return TtsRenderResponse(
            status="completed",
            audio_base64=base64.b64encode(raw_audio).decode("ascii"),
            audio_format="pcm_s16le",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name},
        )

    def stream_render(self, request: TtsRenderRequest, *, frame_size_bytes: int) -> TtsStreamRender:
        chunks = (
            b"\x34\x12" * 320,
            b"\x56\x78" * 320,
        )
        return TtsStreamRender(
            status="completed",
            audio_format="pcm_s16le",
            sample_rate_hz=request.sample_rate_hz,
            metadata={"renderer": self.name},
            chunks=chunks,
            total_audio_bytes=sum(len(chunk) for chunk in chunks),
        )


def run_phase3_audio_agent_sidecar_playback_regression() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="asurada-audio-agent-reg-") as tmpdir:
        player_log = Path(tmpdir) / "player.log"
        player_script = Path(tmpdir) / "fake_stream_player.py"
        player_script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "data = sys.stdin.buffer.read()\n"
            "Path(sys.argv[1]).write_text(f'{len(data)}|{data[:4].decode(\"latin1\")}', encoding='utf-8')\n",
            encoding="utf-8",
        )

        server = VoiceSidecarServer(
            config=VoiceSidecarServerConfig(host="127.0.0.1", port=0, sidecar_name="playback_sidecar", tts_enabled=False),
            llm_explainer=LlmExplainer(),
            tts_renderer=FakePlaybackRenderer(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        previous = {
            "ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY": os.environ.get("ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY"),
            "ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS": os.environ.get("ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS"),
        }
        os.environ["ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY"] = sys.executable
        os.environ["ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS"] = f"{player_script} {player_log}"
        try:
            client = VoiceSidecarClient(
                VoiceSidecarClientConfig(base_url=f"http://127.0.0.1:{server.listening_port}", timeout_ms=1000)
            )
            result = client.play_tts(
                request=TtsRenderRequest(
                    text="当前整体先守住后车，再看处罚窗口。",
                    persona_id="asurada_default",
                    voice_profile_id="asurada_cn_ai_v1",
                )
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            server.shutdown()
            thread.join(timeout=1.0)

        log_text = player_log.read_text(encoding="utf-8")
        checks = {
            "played": result.status == "played",
            "stream_mode": str(result.metadata.get("playback_mode") or "") == "stream",
            "riff_header": log_text.endswith("|RIFF"),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "result": result.to_dict(),
                "player_log": log_text,
            },
        }


def run_phase3_audio_agent_stream_preroll_regression() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="asurada-audio-agent-preroll-reg-") as tmpdir:
        player_log = Path(tmpdir) / "player.log"
        player_script = Path(tmpdir) / "fake_stream_player.py"
        player_script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "data = sys.stdin.buffer.read()\n"
            "Path(sys.argv[1]).write_text(data[:12].hex(), encoding='utf-8')\n",
            encoding="utf-8",
        )

        server = VoiceSidecarServer(
            config=VoiceSidecarServerConfig(host="127.0.0.1", port=0, sidecar_name="preroll_sidecar", tts_enabled=False),
            llm_explainer=LlmExplainer(),
            tts_renderer=FakeStreamingPcmRenderer(),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        previous = {
            "ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY": os.environ.get("ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY"),
            "ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS": os.environ.get("ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS"),
            "ASURADA_AUDIO_AGENT_STREAM_PREROLL_MS": os.environ.get("ASURADA_AUDIO_AGENT_STREAM_PREROLL_MS"),
        }
        os.environ["ASURADA_AUDIO_AGENT_STREAM_PLAYER_BINARY"] = sys.executable
        os.environ["ASURADA_AUDIO_AGENT_STREAM_PLAYER_ARGS"] = f"{player_script} {player_log}"
        os.environ["ASURADA_AUDIO_AGENT_STREAM_PREROLL_MS"] = "120"
        try:
            client = VoiceSidecarClient(
                VoiceSidecarClientConfig(base_url=f"http://127.0.0.1:{server.listening_port}", timeout_ms=1000)
            )
            result = client.play_tts(
                request=TtsRenderRequest(
                    text="当前整体先守住后车，再看处罚窗口。",
                    persona_id="asurada_default",
                    voice_profile_id="asurada_cn_ai_v1",
                    audio_format="pcm_s16le",
                )
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            server.shutdown()
            thread.join(timeout=1.0)

        prefix_hex = player_log.read_text(encoding="utf-8")
        checks = {
            "played": result.status == "played",
            "stream_mode": str(result.metadata.get("playback_mode") or "") == "stream",
            "preroll_reported": int(result.metadata.get("stream_preroll_ms") or 0) == 120,
            "leading_silence": prefix_hex == ("00" * 12),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "analysis": {
                "result": result.to_dict(),
                "prefix_hex": prefix_hex,
            },
        }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "buffered": run_phase3_audio_agent_sidecar_playback_regression(),
                "stream_preroll": run_phase3_audio_agent_stream_preroll_regression(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

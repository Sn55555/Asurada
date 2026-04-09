from __future__ import annotations

import json
from pathlib import Path
import tempfile

from asurada.macos_audio_capture import MacOSAudioCaptureResult
from asurada.open_asr import OpenAsrRecognizer, OpenAsrResult


class _FakeCapture:
    def __init__(self, result: MacOSAudioCaptureResult) -> None:
        self.result = result

    def capture_once(self) -> MacOSAudioCaptureResult:
        return self.result


class _FakeBackend:
    def __init__(self, result: OpenAsrResult) -> None:
        self.result = result

    def transcribe_file(self, *, audio_file_path: str) -> OpenAsrResult:
        return self.result


def run_phase3_open_asr_regression() -> dict[str, object]:
    temp_audio = Path(tempfile.gettempdir()) / "asurada_open_asr_regression.caf"
    temp_audio.write_bytes(b"fake-audio")

    capture_result = MacOSAudioCaptureResult(
        status="recorded",
        audio_file_path=str(temp_audio),
        started_at_ms=1_777_400_000_000,
        ended_at_ms=1_777_400_000_640,
        duration_ms=640,
        metadata={"source": "fake_capture"},
    )
    asr_result = OpenAsrResult(
        status="recognized",
        transcript_text="阿斯拉达 后车差距",
        confidence=0.91,
        started_at_ms=1_777_400_000_100,
        ended_at_ms=1_777_400_000_900,
        locale="zh",
        metadata={"backend": "fake_open_asr"},
    )
    recognizer = OpenAsrRecognizer(
        audio_capture=_FakeCapture(capture_result),
        backend=_FakeBackend(asr_result),
    )
    recognized = recognizer.listen_once()

    no_speech_recognizer = OpenAsrRecognizer(
        audio_capture=_FakeCapture(
            MacOSAudioCaptureResult(
                status="timeout_no_speech",
                audio_file_path="",
                started_at_ms=1_777_400_001_000,
                ended_at_ms=1_777_400_007_000,
                duration_ms=6000,
                metadata={"source": "fake_capture"},
            )
        ),
        backend=_FakeBackend(asr_result),
    )
    no_speech = no_speech_recognizer.listen_once()

    checks = {
        "recognized_status": recognized.status == "recognized",
        "recognized_text": recognized.transcript_text == "阿斯拉达 后车差距",
        "capture_attached": ((recognized.metadata or {}).get("capture") or {}).get("status") == "recorded",
        "temp_audio_cleaned": not temp_audio.exists(),
        "no_speech_passthrough": no_speech.status == "timeout_no_speech" and no_speech.transcript_text == "",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "recognized": recognized.to_dict(),
            "no_speech": no_speech.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_open_asr_regression(), ensure_ascii=False, indent=2))

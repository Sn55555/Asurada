from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from asurada.macos_speech import MacOSSpeechRecognizer, MacOSSpeechRecognizerConfig


def run_phase3_macos_speech_regression() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="asurada-macos-speech-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        fake_swift = tmp_path / "swift"
        fake_script = tmp_path / "macos_speech_capture.swift"
        fake_swift.write_text(
            """#!/bin/sh
printf '%s\n' '{"status":"recognized","transcript_text":"后车差距","confidence":0.98,"started_at_ms":1000,"ended_at_ms":1400,"locale":"zh-CN","metadata":{"backend":"fake_swift"}}'
""",
            encoding="utf-8",
        )
        fake_swift.chmod(0o755)
        fake_script.write_text("// fake script path for regression\n", encoding="utf-8")

        recognizer = MacOSSpeechRecognizer(
            MacOSSpeechRecognizerConfig(
                swift_binary=str(fake_swift),
                script_path=str(fake_script),
                locale="zh-CN",
                listen_timeout_s=4.0,
                silence_timeout_s=1.0,
                command_timeout_s=4.0,
            )
        )
        result = recognizer.listen_once()

    checks = {
        "recognized_status": result.status == "recognized",
        "transcript_loaded": result.transcript_text == "后车差距",
        "confidence_loaded": result.confidence == 0.98,
        "locale_loaded": result.locale == "zh-CN",
        "metadata_loaded": result.metadata.get("backend") == "fake_swift",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "result": result.to_dict(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_macos_speech_regression(), ensure_ascii=False, indent=2))

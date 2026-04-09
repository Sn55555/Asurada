from __future__ import annotations

import json
import os
import types
from pathlib import Path


def run_phase3_realtime_asr_default_regression() -> dict[str, object]:
    source = Path("/Users/sn5/Asurada/asurada-core/scripts/phase3_macos_voice_loop.py").read_text(encoding="utf-8")
    checks = {
        "default_symbol_present": "_DEFAULT_RECOGNIZER_BACKEND" in source,
        "sidecar_realtime_preferred": '"voice_sidecar_realtime_asr"' in source,
        "doubao_realtime_present": '"doubao_realtime_asr"' in source,
        "voice_sidecar_fallback": '"voice_sidecar_asr"' in source,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_realtime_asr_default_regression(), ensure_ascii=False, indent=2))

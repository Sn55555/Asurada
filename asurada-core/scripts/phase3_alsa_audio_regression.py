from __future__ import annotations

import json
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from asurada.audio_io import (
    AlsaAplayOutputBackend,
    AlsaAudioInputConfig,
    AlsaAudioOutputConfig,
    AlsaArecordInputBackend,
    AudioFormat,
    AudioIO,
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_alsa_pair() -> tuple[AlsaArecordInputBackend, AlsaAplayOutputBackend, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="asurada-alsa-regression-"))
    capture_source = temp_dir / "capture.raw"
    capture_source.write_bytes((b"\x01\x02" * 320) + (b"\x03\x04" * 320))
    playback_sink = temp_dir / "playback.raw"

    arecord_script = temp_dir / "fake_arecord.py"
    _write_executable(
        arecord_script,
        f"""#!/usr/bin/env python3
import pathlib
import sys

source = pathlib.Path({capture_source.as_posix()!r})
sys.stdout.buffer.write(source.read_bytes())
sys.stdout.flush()
""",
    )

    aplay_script = temp_dir / "fake_aplay.py"
    _write_executable(
        aplay_script,
        f"""#!/usr/bin/env python3
import pathlib
import sys

sink = pathlib.Path({playback_sink.as_posix()!r})
payload = sys.stdin.buffer.read()
sink.write_bytes(payload)
""",
    )

    fmt = AudioFormat(sample_rate_hz=16000, channels=1, sample_width_bytes=2)
    input_backend = AlsaArecordInputBackend(
        AlsaAudioInputConfig(
            audio_format=fmt,
            period_ms=20,
            arecord_binary=str(arecord_script),
        )
    )
    output_backend = AlsaAplayOutputBackend(
        AlsaAudioOutputConfig(
            audio_format=fmt,
            aplay_binary=str(aplay_script),
        )
    )
    return input_backend, output_backend, playback_sink


def run_phase3_alsa_audio_regression() -> dict[str, Any]:
    input_backend, output_backend, playback_sink = _make_fake_alsa_pair()
    audio_io = AudioIO(input_backend=input_backend, output_backend=output_backend)
    audio_io.start()
    first_chunk = audio_io.read_input_chunk()
    second_chunk = audio_io.read_input_chunk()
    if first_chunk is not None:
        audio_io.play_output_chunk(first_chunk)
    if second_chunk is not None:
        audio_io.play_output_chunk(second_chunk)
    audio_io.stop()

    # Give the fake playback writer one short moment to flush on process exit.
    deadline = time.time() + 1.0
    while time.time() < deadline and not playback_sink.exists():
        time.sleep(0.05)

    played_bytes = playback_sink.read_bytes() if playback_sink.exists() else b""
    first_chunk_bytes = first_chunk.pcm_s16le if first_chunk is not None else b""
    second_chunk_bytes = second_chunk.pcm_s16le if second_chunk is not None else b""

    checks = {
        "audio_io_starts": True,
        "read_first_chunk": first_chunk is not None and len(first_chunk_bytes) > 0,
        "read_second_chunk": second_chunk is not None and len(second_chunk_bytes) > 0,
        "playback_receives_bytes": len(played_bytes) == len(first_chunk_bytes) + len(second_chunk_bytes),
        "audio_io_stops": not input_backend.is_active() and not output_backend.is_active(),
    }

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "analysis": {
            "first_chunk_bytes": len(first_chunk_bytes),
            "second_chunk_bytes": len(second_chunk_bytes),
            "played_bytes": len(played_bytes),
            "audio_io": audio_io.describe(),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_phase3_alsa_audio_regression(), ensure_ascii=False, indent=2))

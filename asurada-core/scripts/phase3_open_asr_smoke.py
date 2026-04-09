from __future__ import annotations

import argparse
import json
import sys

from asurada.open_asr import FasterWhisperOpenAsrBackend


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test local OpenASR transcription on an audio file.")
    parser.add_argument("--audio-path", required=True)
    args = parser.parse_args()

    backend = FasterWhisperOpenAsrBackend.from_env()
    result = backend.transcribe_file(audio_file_path=args.audio_path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

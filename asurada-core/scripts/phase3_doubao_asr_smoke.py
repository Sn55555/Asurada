from __future__ import annotations

import argparse
import json
from pathlib import Path

from asurada.voice_sidecar_asr import (
    DoubaoBigmodelStreamingWsSidecarAsrBackend,
    DoubaoFlashHttpSidecarAsrBackend,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test Doubao flash ASR on a local audio file.")
    parser.add_argument("--audio-path", required=True)
    parser.add_argument("--audio-format", default="wav")
    parser.add_argument("--locale", default="zh-CN")
    parser.add_argument("--prompt", default="阿斯拉达 后车差距 整体形势 为什么现在不进攻 陪我聊天")
    parser.add_argument("--backend", choices=("flash", "streaming"), default="flash")
    args = parser.parse_args()

    if args.backend == "streaming":
        backend = DoubaoBigmodelStreamingWsSidecarAsrBackend.from_env()
    else:
        backend = DoubaoFlashHttpSidecarAsrBackend.from_env()
    audio_bytes = Path(args.audio_path).read_bytes()
    result = backend.transcribe_audio(
        audio_bytes=audio_bytes,
        audio_format=args.audio_format,
        locale=args.locale,
        prompt=args.prompt,
        metadata={"audio_path": args.audio_path},
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

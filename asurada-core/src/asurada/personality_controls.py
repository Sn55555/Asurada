"""Inspect or change personality controls through the local speech service."""
from __future__ import annotations

import argparse
import json
import os

from .speech_client import SharedSpeechClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=os.getenv("ASURADA_SPEECH_SOCKET"))
    parser.add_argument("--quiet", choices=("on", "off"))
    parser.add_argument("--humor", choices=("off", "low", "normal"))
    args = parser.parse_args()
    if not args.socket:
        parser.error("set ASURADA_SPEECH_SOCKET or pass --socket")
    changes = {}
    if args.quiet is not None:
        changes["quiet"] = args.quiet == "on"
    if args.humor is not None:
        changes["humor"] = args.humor
    try:
        result = SharedSpeechClient(args.socket).personality_preferences(**changes)
    except (OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

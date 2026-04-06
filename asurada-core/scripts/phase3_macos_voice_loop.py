from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from asurada.audio_io import AudioFormat
from asurada.decode import decode_snapshot
from asurada.macos_speech import MacOSSpeechRecognizer
from asurada.models import SessionState, StrategyMessage
from asurada.output import ConsoleVoiceOutput
from asurada.voice_input import VoiceInputCoordinator
from asurada.voice_turn import VoiceTurn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a macOS duplex voice-loop smoke test against one snapshot.")
    parser.add_argument(
        "--session-log",
        default="asurada-core/runtime_logs/session_log.jsonl",
        help="Session log jsonl used as the snapshot source.",
    )
    parser.add_argument(
        "--row",
        default="latest",
        help="Row selector: latest or zero-based row index.",
    )
    parser.add_argument(
        "--locale",
        default="zh-CN",
        help="Speech recognition locale identifier.",
    )
    parser.add_argument(
        "--no-auto-refresh",
        action="store_true",
        help="Do not reload the latest snapshot before each listen cycle.",
    )
    parser.add_argument(
        "--wait-for-live-seconds",
        type=float,
        default=30.0,
        help="How long to wait for the first live snapshot when the session log is still empty.",
    )
    args = parser.parse_args()

    if not MacOSSpeechRecognizer.env_ready():
        print("macOS speech recognizer is not ready. Check swift availability and script path.", file=sys.stderr)
        return 2

    state, primary_message = wait_for_state_and_message(
        Path(args.session_log),
        args.row,
        wait_seconds=args.wait_for_live_seconds,
    )
    recognizer = MacOSSpeechRecognizer.from_env()
    coordinator = VoiceInputCoordinator()
    voice_output = ConsoleVoiceOutput()

    print("macOS duplex voice loop")
    print(f"track={state.track} lap={state.lap_number}/{state.total_laps} position=P{state.player.position}")
    print(f"weather={state.weather} safety_car={state.safety_car} source_ts={state.source_timestamp_ms}")
    if primary_message is not None:
        print(f"primary_message={primary_message.code} {primary_message.title}")
    print("commands: press Enter to listen, r to reload snapshot, q to quit")

    while True:
        command = input("> ").strip().lower()
        if command in {"q", "quit", "exit"}:
            return 0
        if command in {"r", "reload"}:
            state, primary_message = wait_for_state_and_message(
                Path(args.session_log),
                args.row,
                wait_seconds=args.wait_for_live_seconds,
            )
            print(f"reloaded track={state.track} lap={state.lap_number}/{state.total_laps} P{state.player.position}")
            continue

        if not args.no_auto_refresh:
            state, primary_message = wait_for_state_and_message(
                Path(args.session_log),
                args.row,
                wait_seconds=args.wait_for_live_seconds,
            )

        print("listening...")
        result = recognizer.listen_once()
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.status not in {"recognized", "recognized_partial"} or not result.transcript_text.strip():
            continue

        turn = VoiceTurn(
            turn_id=f"voice-turn:macos:{int(time.time() * 1000)}",
            started_at_ms=result.started_at_ms,
            ended_at_ms=result.ended_at_ms,
            audio_format=AudioFormat(),
            pcm_s16le=b"",
            chunk_count=0,
            source="macos_speech",
            completion_reason=result.status,
            metadata={
                "transcript_text": result.transcript_text,
                "macos_speech": result.to_dict(),
            },
        )
        processing = coordinator.process_completed_turn(
            state=state,
            turn=turn,
            voice_output=voice_output,
            primary_message=primary_message,
            render=True,
        )
        print(json.dumps(processing.to_dict(), ensure_ascii=False, indent=2))


def load_state_and_message(path: Path, row_selector: str) -> tuple[SessionState, StrategyMessage | None]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise RuntimeError(f"empty session log: {path}")
    if row_selector == "latest":
        row = rows[-1]
    else:
        row = rows[int(row_selector)]

    payload = {
        "session_uid": row["session_uid"],
        "track": row["track"],
        "lap_number": row["lap_number"],
        "total_laps": row["total_laps"],
        "weather": row.get("weather") or "Unknown",
        "safety_car": row.get("safety_car") or "NONE",
        "source_timestamp_ms": row.get("source_timestamp_ms") or 0,
        "player": row["player"],
        "rivals": row.get("rivals") or [],
        "raw": row.get("raw") or {},
    }
    state = decode_snapshot(payload)
    primary_message = None
    if row.get("messages"):
        top = row["messages"][0]
        primary_message = StrategyMessage(
            code=str(top["code"]),
            priority=int(top["priority"]),
            title=str(top["title"]),
            detail=str(top["detail"]),
        )
    return state, primary_message


def wait_for_state_and_message(path: Path, row_selector: str, *, wait_seconds: float) -> tuple[SessionState, StrategyMessage | None]:
    deadline = time.time() + max(wait_seconds, 0.0)
    while True:
        try:
            return load_state_and_message(path, row_selector)
        except RuntimeError as exc:
            if "empty session log" not in str(exc):
                raise
            if time.time() >= deadline:
                raise
            time.sleep(0.25)


if __name__ == "__main__":
    raise SystemExit(main())

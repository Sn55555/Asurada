"""Extract and replay bounded clips from the driver's historical snapshots."""
from argparse import ArgumentParser
from collections import Counter, deque
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import resource
import sys
import time
from unittest.mock import patch

from asurada.app import AsuradaApp
from asurada.config import AppConfig
from asurada.output import ConsoleVoiceOutput
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.wheel_telemetry import TYRE_WEAR_ALERT, tyre_alert
from regression_support import ImmediateSpeechBackend


SCENES = {
    "suzuka": ("9840823942616679864", {"finish", "FRONT_LOAD", "DYNAMICS_UNSTABLE"}),
    "jeddah": ("1476455955304844120", {"DEFEND_WINDOW", "FRONT_LOAD", TYRE_WEAR_ALERT}),
    "miami": ("14194040201519987940", {"right_wing"}),
}


def observed_tags(row):
    raw = row.get("raw") or {}
    debug = row.get("debug") or {}
    arbitration = ((debug.get("arbiter_v2") or {}).get("input") or {})
    values = {rule.get("code") for rule in arbitration.get("rule_candidates", [])}
    for action in row.get("messages") or ():
        values.add(action.get("code"))
    tyre = tyre_alert(raw.get("tyres_damage_pct"), raw.get("tyres_wear_pct"))
    if tyre:
        values.add(tyre[0])
    if (row.get("personality") or {}).get("opportunity") == "finish" or raw.get("result_status") == 3:
        values.add("finish")
    if (raw.get("wing_damage_pct") or {}).get("front_right", 0) >= 30:
        values.add("right_wing")
    return values


def select_clips(archive, uid, expected):
    selected, anchors = {}, {}
    history = deque(maxlen=10)
    remaining = 0
    missing = expected.copy()
    for source in sorted(archive.glob("session_log.*.jsonl")):
        with source.open() as stream:
            first = next(stream, "")
            if not first or str(json.loads(first).get("session_uid")) != uid:
                continue
            for number, raw in enumerate(stream, 2):
                row = json.loads(raw)
                if str(row.get("session_uid")) != uid:
                    continue
                key = (source.name, number)
                history.append((key, raw))
                matches = observed_tags(row) & missing
                if matches:
                    selected.update(history)
                    remaining = 30
                    for tag in sorted(matches):
                        anchors[tag] = {"archive": source.name, "line": number,
                                        "session_time_s": (row.get("raw") or {}).get("session_time_s")}
                    missing.difference_update(matches)
                if remaining:
                    selected[key] = raw
                    remaining -= 1
                if not missing and not remaining:
                    return selected, anchors
    return selected, anchors


def replay(path):
    with TemporaryDirectory(prefix="asurada-race-baseline-", dir="/tmp") as temp, patch.dict(
        os.environ, {"ASURADA_RUNTIME_DIR": str(Path(temp) / "logs"), "ASURADA_PERSONALITY_ENABLED": "1",
                     "ASURADA_PERSONALITY_LLM_MODE": "disabled", "ASURADA_ATTACK_MODE_STATE_PATH": str(Path(temp) / "attack.json"),
                     "ASURADA_TRAINING_MEMORY_DB": str(Path(temp) / "training.sqlite3")},
    ):
        output = ConsoleVoiceOutput(backend=ImmediateSpeechBackend())
        service = SpeechService(Path(temp) / "voice.sock", output=output).start()
        try:
            client = SharedSpeechClient(service.path, timeout_s=5)
            app = AsuradaApp(AppConfig(), voice_output=client)
            events = []
            with redirect_stdout(io.StringIO()):
                app.run_replay(path)
                output.tick()
            cursor = None
            while True:
                page = client.read_events(cursor=cursor, limit=128, timeout_s=1)
                events.extend(entry["event"] for entry in page["events"])
                cursor = page["cursor"]
                if not page["has_more"]:
                    break
            return events
        finally:
            service.close()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("/tmp/asurada-personality-live-zhlj_11k/logs"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, (uid, expected) in SCENES.items():
        path = args.output / f"{name}.jsonl"
        clips, anchors = select_clips(args.archive, uid, expected)
        path.write_text("".join(clips[key] for key in sorted(clips)), encoding="utf-8")
        events = replay(path) if clips else []
        timeline = args.output / f"{name}-speech.json"
        timeline.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        results[name] = {
            "session_uid": uid, "anchors": anchors, "missing": sorted(expected - anchors.keys()),
            "frames": len(clips), "sha256": sha256(path.read_bytes()).hexdigest(),
            "input": path.name, "events": timeline.name,
            "historical_primary": dict(Counter(
                (json.loads(raw).get("messages") or [{}])[0].get("code", "NONE") for raw in clips.values()
            )),
            "starts": dict(Counter(event["action_code"] for event in events if event["event_type"] == "start")),
        }
    combined = args.output / "consecutive-scenes.jsonl"
    with combined.open("wb") as stream:
        for name in SCENES:
            stream.write((args.output / f"{name}.jsonl").read_bytes())
    start = time.monotonic()
    consecutive = replay(combined) if combined.stat().st_size else []
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (args.output / "consecutive-events.json").write_text(
        json.dumps(consecutive, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {
        "source": str(args.archive), "scope": "historical normalized snapshots and simulated playback", "scenes": results,
        "consecutive_replay": {
            "source": combined.name, "events": "consecutive-events.json",
            "frames": sum(scene["frames"] for scene in results.values()),
            "session_ids": [scene["session_uid"] for scene in results.values() if scene["frames"]],
            "seconds": round(time.monotonic() - start, 3),
            "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        },
    }
    (args.output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

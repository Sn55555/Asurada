#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asurada.capture_ingest import CaptureJsonlSource  # noqa: E402
from asurada.decode import decode_snapshot  # noqa: E402
from asurada.packet_snapshot import CaptureSnapshotAssembler  # noqa: E402
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError  # noqa: E402
from asurada.track_model import load_track_profile  # noqa: E402


REAL_CAPTURE_SAMPLES = (
    (
        "Shanghai",
        ROOT.parent / "tools" / "captures" / "f1_25_udp_capture_20260321_024707.jsonl",
    ),
    (
        "Suzuka",
        ROOT
        / "data"
        / "capture_samples"
        / "f1_25_udp_capture_20260329_190623"
        / "suzuka_sprint_race_like_uid15.jsonl",
    ),
    ("Austria", ROOT / "runtime_logs" / "live_udp_capture_20260407_025455.jsonl"),
)
TARGET_SNAPSHOTS = 40


def validate_capture(expected_track: str, path: Path) -> dict[str, Any]:
    decoder = F125PacketDecoder()
    assembler = CaptureSnapshotAssembler()
    decoded_packets = 0
    decode_errors = 0
    snapshots = 0
    classified_snapshots = 0
    seen_segments: set[str] = set()
    actual_tracks: set[str] = set()

    if not path.exists():
        return {
            "track": expected_track,
            "source": str(path),
            "passed": True,
            "skipped": True,
            "reason": "external_capture_missing",
        }

    for packet in CaptureJsonlSource(path):
        try:
            envelope = decoder.decode_raw(packet)
        except PacketDecodeError:
            decode_errors += 1
            continue
        decoded_packets += 1
        snapshot = assembler.push(envelope)
        if snapshot is None:
            continue
        state = decode_snapshot(snapshot)
        actual_tracks.add(state.track)
        if state.track != expected_track:
            continue
        snapshots += 1
        profile = load_track_profile(state.track)
        lap_distance_m = state.player.lap_distance_m
        if profile is not None and lap_distance_m is not None and lap_distance_m >= 0.0:
            zone = profile.classify(float(lap_distance_m))
            if zone.zone_type != "unavailable":
                classified_snapshots += 1
                seen_segments.add(zone.zone_name)
        if snapshots >= TARGET_SNAPSHOTS and classified_snapshots >= 10:
            break

    passed = (
        expected_track in actual_tracks
        and snapshots >= TARGET_SNAPSHOTS
        and classified_snapshots >= 10
        and bool(seen_segments)
        and decode_errors == 0
    )
    return {
        "track": expected_track,
        "source": str(path),
        "evidence": "real_f1_25_raw_udp_capture",
        "decoded_packets": decoded_packets,
        "decode_errors": decode_errors,
        "snapshots": snapshots,
        "classified_snapshots": classified_snapshots,
        "seen_segments": sorted(seen_segments),
        "actual_tracks": sorted(actual_tracks),
        "passed": passed,
    }


def main() -> int:
    tracks = [validate_capture(track, path) for track, path in REAL_CAPTURE_SAMPLES]
    available_tracks = [item for item in tracks if not item.get("skipped")]
    report = {
        "passed": all(bool(item["passed"]) for item in available_tracks),
        "evidence_scope": "external_raw_captures_when_available",
        "summary": {
            "real_udp_tracks": len(tracks),
            "available_tracks": len(available_tracks),
            "passed_tracks": sum(bool(item["passed"]) for item in available_tracks),
            "skipped_tracks": sum(bool(item.get("skipped")) for item in tracks),
        },
        "tracks": tracks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

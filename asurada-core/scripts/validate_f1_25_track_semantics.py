#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from f1_25_track_catalog import F1_25_TRACK_CATALOG


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asurada.track_model import load_track_profile  # noqa: E402
from asurada.packet_snapshot import TRACK_NAMES  # noqa: E402


VALID_ZONE_TYPES = {
    "deployment_straight",
    "braking_entry",
    "apex_rotation",
    "exit_traction",
    "high_load_management",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"not an object: {path}")
    return payload


def validate_profile(path: Path, *, expected_track: str, expected_track_id: int) -> dict[str, int]:
    payload = load_json(path)
    assert payload["track"] == expected_track, (path, payload.get("track"), expected_track)
    if "track_id" in payload:
        assert int(payload["track_id"]) == expected_track_id
    lap_length = float(payload["lap_length_m"])
    assert 3000.0 <= lap_length <= 8000.0, (path, lap_length)
    segments = payload["semantic_segments"]
    assert segments, path
    assert math.isclose(float(segments[0]["start_m"]), 0.0, abs_tol=1e-3), path
    assert math.isclose(float(segments[-1]["end_m"]), lap_length, abs_tol=1e-3), path
    previous_end = 0.0
    for segment in segments:
        start = float(segment["start_m"])
        end = float(segment["end_m"])
        assert math.isclose(start, previous_end, abs_tol=1e-3), (path, previous_end, start)
        assert end > start, (path, segment)
        assert segment["zone_type"] in VALID_ZONE_TYPES, (path, segment)
        assert str(segment.get("usage", "")).strip(), (path, segment)
        previous_end = end
    for zone in payload.get("braking_zones", []):
        assert 0.0 <= float(zone["start_m"]) < float(zone["end_m"]) <= lap_length
    for apex in payload.get("corner_apexes", []):
        assert 0.0 <= float(apex["distance_m"]) <= lap_length
        if apex.get("recommended_gear") is not None:
            assert 1 <= int(apex["recommended_gear"]) <= 8

    profile = load_track_profile(expected_track)
    assert profile is not None, expected_track
    assert profile.track == expected_track
    for segment in segments:
        midpoint = (float(segment["start_m"]) + float(segment["end_m"])) / 2.0
        classified = profile.classify(midpoint)
        assert classified.zone_name == segment["name"], (expected_track, midpoint, classified, segment)
    assert profile.classify(-1.0).zone_type == "unavailable"
    for index, segment in enumerate(segments):
        classified = profile.classify(float(segment["start_m"]))
        assert classified.zone_name == segment["name"], (expected_track, segment, classified)
        following = profile.next_segment(float(segment["start_m"]))
        expected_following = segments[(index + 1) % len(segments)]
        assert following.zone_name == expected_following["name"], (
            expected_track,
            segment,
            following,
            expected_following,
        )
    return {
        "segments": len(segments),
        "brakes": len(payload.get("braking_zones", [])),
        "apexes": len(payload.get("corner_apexes", [])),
    }


def validate_download_manifest(path: Path) -> tuple[int, int, int]:
    manifest = load_json(path)
    assert int(manifest["track_count"]) == len(F1_25_TRACK_CATALOG)
    expected_slugs = {entry.profile_slug for entry in F1_25_TRACK_CATALOG}
    actual_slugs = {item["profile_slug"] for item in manifest["tracks"]}
    assert actual_slugs == expected_slugs
    lap_count = 0
    verified_lap_count = 0
    for track in manifest["tracks"]:
        assert len(track["laps"]) >= 3, track["track_name"]
        for lap in track["laps"]:
            file_path = path.parent / lap["file"]
            expected_sha256 = str(lap["sha256"])
            assert len(expected_sha256) == 64
            int(expected_sha256, 16)
            assert int(lap["byte_length"]) > 0
            lap_count += 1
            if not file_path.exists():
                continue
            raw = file_path.read_bytes()
            assert len(raw) == int(lap["byte_length"]), file_path
            assert hashlib.sha256(raw).hexdigest() == expected_sha256, file_path
            payload = json.loads(raw)
            assert len(payload["original"]["speed"]) >= 100, file_path
            verified_lap_count += 1
    return len(manifest["tracks"]), lap_count, verified_lap_count


def main() -> int:
    expected_track_names = {entry.track_id: entry.track_name for entry in F1_25_TRACK_CATALOG}
    assert TRACK_NAMES == expected_track_names, (TRACK_NAMES, expected_track_names)
    track_dir = ROOT / "data" / "tracks"
    telemetry_manifest = ROOT / "data" / "community_telemetry" / "f1laps_f12025" / "manifest.json"
    track_count, lap_count, verified_lap_count = validate_download_manifest(telemetry_manifest)
    segment_count = brake_count = apex_count = 0
    for entry in F1_25_TRACK_CATALOG:
        result = validate_profile(
            track_dir / f"{entry.profile_slug}_segments.json",
            expected_track=entry.track_name,
            expected_track_id=entry.track_id,
        )
        segment_count += result["segments"]
        brake_count += result["brakes"]
        apex_count += result["apexes"]
    print(
        json.dumps(
            {
                "ok": True,
                "track_layouts": track_count,
                "community_laps": lap_count,
                "community_laps_verified": verified_lap_count,
                "source_validation_mode": (
                    "raw_files_verified" if verified_lap_count == lap_count else "manifest_hashes_only"
                ),
                "semantic_segments": segment_count,
                "braking_zones": brake_count,
                "corner_apexes": apex_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

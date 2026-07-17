#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from build_f1_25_track_semantics import CURATED_PROFILE_SLUGS
from f1_25_track_catalog import F1_25_TRACK_CATALOG


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asurada.track_model import load_track_profile  # noqa: E402


MIN_BRAKE_ZONE_HIT_RATE = 0.70
MIN_APEX_STEER_HIT_RATE = 0.80
MIN_GEAR_AGREEMENT_RATE = 0.80
HIGH_RISK_SLUGS = {
    "monaco",
    "jeddah",
    "miami",
    "silverstone_reverse",
    "austria_reverse",
    "zandvoort_reverse",
}
TELEMETRY_ROOT = ROOT / "data" / "community_telemetry" / "f1laps_f12025"
QUALITY_BASELINE = ROOT / "data" / "tracks" / "f1_25_track_semantics_quality_baseline.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated F1 25 track semantics quality.")
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="Write the raw-telemetry result as a compact checked-in baseline.",
    )
    return parser.parse_args()


def _manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_telemetry_available(manifest: dict[str, Any]) -> bool:
    return all(
        (TELEMETRY_ROOT / lap["file"]).exists()
        for track in manifest.get("tracks", [])
        for lap in track.get("laps", [])
    )


def _load_checked_in_baseline(manifest_path: Path) -> dict[str, Any]:
    report = json.loads(QUALITY_BASELINE.read_text(encoding="utf-8"))
    assert report["source_manifest_sha256"] == _manifest_sha256(manifest_path)
    assert report["summary"]["community_generated_tracks"] == 24
    report["evidence_mode"] = "checked_in_raw_telemetry_baseline"
    return report


def _channel_points(
    payload: dict[str, Any], channel: str, *, source_length_m: float, target_length_m: float
) -> list[tuple[float, float]]:
    return [
        (float(item["x"]) * target_length_m / source_length_m, float(item["y"]))
        for item in payload["original"][channel]
    ]


def _rate(values: list[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> int:
    args = parse_args()
    manifest_path = TELEMETRY_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not _raw_telemetry_available(manifest):
        report = _load_checked_in_baseline(manifest_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    records = {item["profile_slug"]: item for item in manifest["tracks"]}
    tracks: list[dict[str, Any]] = []

    for entry in F1_25_TRACK_CATALOG:
        if entry.profile_slug in CURATED_PROFILE_SLUGS:
            continue
        profile = load_track_profile(entry.track_name)
        if profile is None:
            tracks.append({"track": entry.track_name, "passed": False, "reason": "profile_missing"})
            continue
        brake_hits: list[bool] = []
        apex_hits: list[bool] = []
        gear_hits: list[bool] = []
        record = records[entry.profile_slug]
        for lap in record["laps"]:
            payload = json.loads((TELEMETRY_ROOT / lap["file"]).read_text(encoding="utf-8"))
            source_length_m = max(float(item["x"]) for item in payload["original"]["speed"])
            brake_points = _channel_points(
                payload,
                "brake",
                source_length_m=source_length_m,
                target_length_m=profile.lap_length_m,
            )
            steer_points = _channel_points(
                payload,
                "steer",
                source_length_m=source_length_m,
                target_length_m=profile.lap_length_m,
            )
            gear_points = _channel_points(
                payload,
                "gear",
                source_length_m=source_length_m,
                target_length_m=profile.lap_length_m,
            )
            for zone in profile.braking_zones:
                values = [
                    value
                    for distance, value in brake_points
                    if zone.start_m - 25.0 <= distance <= zone.end_m + 25.0
                ]
                brake_hits.append(max(values, default=0.0) >= 0.25)
            for apex in profile.corner_apexes:
                steer_values = [
                    abs(value)
                    for distance, value in steer_points
                    if apex.distance_m - apex.window_m <= distance <= apex.distance_m + apex.window_m
                ]
                apex_hits.append(max(steer_values, default=0.0) >= 0.055)
                gear_values = [
                    value
                    for distance, value in gear_points
                    if apex.distance_m - 20.0 <= distance <= apex.distance_m + 20.0
                ]
                if apex.recommended_gear is not None and gear_values:
                    observed_gear = int(round(statistics.median(gear_values)))
                    gear_hits.append(abs(observed_gear - apex.recommended_gear) <= 1)

        brake_rate = _rate(brake_hits)
        apex_rate = _rate(apex_hits)
        gear_rate = _rate(gear_hits)
        passed = (
            brake_rate >= MIN_BRAKE_ZONE_HIT_RATE
            and apex_rate >= MIN_APEX_STEER_HIT_RATE
            and gear_rate >= MIN_GEAR_AGREEMENT_RATE
        )
        tracks.append(
            {
                "track_id": entry.track_id,
                "track": entry.track_name,
                "profile_slug": entry.profile_slug,
                "high_risk": entry.profile_slug in HIGH_RISK_SLUGS,
                "community_laps": len(record["laps"]),
                "brake_zone_hit_rate": round(brake_rate, 4),
                "apex_steer_hit_rate": round(apex_rate, 4),
                "gear_agreement_rate": round(gear_rate, 4),
                "passed": passed,
            }
        )

    high_risk = [item for item in tracks if item.get("high_risk")]
    report = {
        "passed": all(bool(item["passed"]) for item in tracks),
        "evidence_mode": "raw_telemetry_recomputed",
        "source_manifest_sha256": _manifest_sha256(manifest_path),
        "thresholds": {
            "brake_zone_hit_rate": MIN_BRAKE_ZONE_HIT_RATE,
            "apex_steer_hit_rate": MIN_APEX_STEER_HIT_RATE,
            "gear_agreement_rate": MIN_GEAR_AGREEMENT_RATE,
        },
        "summary": {
            "community_generated_tracks": len(tracks),
            "passed_tracks": sum(bool(item["passed"]) for item in tracks),
            "high_risk_tracks": len(high_risk),
            "passed_high_risk_tracks": sum(bool(item["passed"]) for item in high_risk),
        },
        "tracks": tracks,
    }
    if args.write_baseline:
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

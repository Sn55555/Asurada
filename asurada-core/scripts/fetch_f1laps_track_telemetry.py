#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1_25_track_catalog import F1_25_TRACK_CATALOG, TrackCatalogEntry


BASE_URL = "https://www.f1laps.com"
GAME_SLUG = "f12025"
USER_AGENT = "Asurada telemetry research/1.0 (public F1Laps leaderboard data)"
LAP_LINK_PATTERN = re.compile(
    r'/laptimes/leaderboard/f12025/(?P<track>[a-z0-9_]+)/(?P<lap>[0-9a-f-]{36})/'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download public F1Laps F1 25 leaderboard telemetry for every game layout."
    )
    parser.add_argument("--top", type=int, default=3, help="Number of leaderboard laps per track (default: 3).")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between HTTP requests in seconds.")
    parser.add_argument("--refresh", action="store_true", help="Re-download files already present locally.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "community_telemetry" / "f1laps_f12025",
    )
    return parser.parse_args()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def leaderboard_lap_ids(entry: TrackCatalogEntry, html: str, limit: int) -> list[str]:
    lap_ids: list[str] = []
    for match in LAP_LINK_PATTERN.finditer(html):
        if match.group("track") != entry.leaderboard_slug:
            continue
        lap_id = match.group("lap")
        if lap_id not in lap_ids:
            lap_ids.append(lap_id)
        if len(lap_ids) >= limit:
            break
    if len(lap_ids) < limit:
        raise RuntimeError(
            f"{entry.leaderboard_slug}: expected {limit} public telemetry laps, found {len(lap_ids)}"
        )
    return lap_ids


def validate_telemetry(
    payload: dict[str, Any], *, track_slug: str, lap_id: str, expected_lap_length_m: float
) -> None:
    original = payload.get("original")
    if not isinstance(original, dict):
        raise ValueError(f"{track_slug}/{lap_id}: missing original telemetry object")
    required = ("speed", "brake", "throttle", "steer", "gear", "drs")
    for channel in required:
        values = original.get(channel)
        if not isinstance(values, list) or len(values) < 100:
            raise ValueError(f"{track_slug}/{lap_id}: invalid {channel} channel")
        if not all(isinstance(item, dict) and "x" in item and "y" in item for item in values[:20]):
            raise ValueError(f"{track_slug}/{lap_id}: malformed {channel} samples")
    distance_max_m = max(float(item["x"]) for item in original["speed"])
    if not expected_lap_length_m * 0.90 <= distance_max_m <= expected_lap_length_m * 1.12:
        raise ValueError(
            f"{track_slug}/{lap_id}: incomplete or implausible lap distance {distance_max_m:.1f} m "
            f"for expected {expected_lap_length_m:.1f} m"
        )


def load_existing(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: object) -> bytes:
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return encoded


def main() -> int:
    args = parse_args()
    if args.top < 1 or args.top > 10:
        raise SystemExit("--top must be between 1 and 10")

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    track_records: list[dict[str, Any]] = []

    for track_index, entry in enumerate(F1_25_TRACK_CATALOG, start=1):
        leaderboard_url = f"{BASE_URL}/f1-25/leaderboard/{entry.leaderboard_slug}/"
        html = fetch_bytes(leaderboard_url).decode("utf-8", errors="replace")
        lap_ids = leaderboard_lap_ids(entry, html, 10)
        lap_records: list[dict[str, Any]] = []

        for leaderboard_rank, lap_id in enumerate(lap_ids, start=1):
            if len(lap_records) >= args.top:
                break
            telemetry_url = f"{BASE_URL}/laptimes/{GAME_SLUG}/{lap_id}/telemetry_charts/"
            relative_path = Path(entry.profile_slug) / f"rank_{leaderboard_rank:02d}_{lap_id}.json"
            output_path = output_dir / relative_path
            payload = None if args.refresh else load_existing(output_path)
            try:
                if payload is None:
                    raw = fetch_bytes(telemetry_url)
                    payload = json.loads(raw.decode("utf-8"))
                    validate_telemetry(
                        payload,
                        track_slug=entry.leaderboard_slug,
                        lap_id=lap_id,
                        expected_lap_length_m=entry.lap_length_m,
                    )
                    encoded = write_json(output_path, payload)
                    time.sleep(max(args.delay, 0.0))
                else:
                    validate_telemetry(
                        payload,
                        track_slug=entry.leaderboard_slug,
                        lap_id=lap_id,
                        expected_lap_length_m=entry.lap_length_m,
                    )
                    encoded = output_path.read_bytes()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"  skip rank {leaderboard_rank}: {lap_id} ({exc})")
                continue

            original = payload["original"]
            lap_records.append(
                {
                    "rank": leaderboard_rank,
                    "lap_id": lap_id,
                    "telemetry_url": telemetry_url,
                    "file": relative_path.as_posix(),
                    "byte_length": len(encoded),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "sample_count": len(original["speed"]),
                    "distance_min_m": min(float(item["x"]) for item in original["speed"]),
                    "distance_max_m": max(float(item["x"]) for item in original["speed"]),
                    "lap_stats": original.get("lap_stats", {}),
                }
            )

        if len(lap_records) < args.top:
            raise RuntimeError(
                f"{entry.leaderboard_slug}: only {len(lap_records)} valid telemetry laps found in top 10"
            )

        track_records.append(
            {
                "leaderboard_slug": entry.leaderboard_slug,
                "track_id": entry.track_id,
                "track_name": entry.track_name,
                "profile_slug": entry.profile_slug,
                "lap_length_m": entry.lap_length_m,
                "leaderboard_url": leaderboard_url,
                "laps": lap_records,
            }
        )
        print(f"[{track_index:02d}/{len(F1_25_TRACK_CATALOG)}] {entry.track_name}: {len(lap_records)} laps")
        time.sleep(max(args.delay, 0.0))

    manifest = {
        "schema_version": "asurada.f1laps-telemetry-manifest.v1",
        "game": "EA SPORTS F1 25",
        "game_slug": GAME_SLUG,
        "provider": "F1Laps",
        "provider_url": BASE_URL,
        "source_scope": "Public F1 25 community leaderboard telemetry pages",
        "retrieved_at": retrieved_at,
        "top_laps_per_track": args.top,
        "track_count": len(track_records),
        "lap_count": sum(len(item["laps"]) for item in track_records),
        "tracks": track_records,
    }
    write_json(output_dir / "manifest.json", manifest)
    print(f"Manifest: {output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1_25_track_catalog import F1_25_TRACK_CATALOG


CHANNELS = ("speed", "brake", "throttle", "steer", "gear", "drs")
CURATED_PROFILE_SLUGS = frozenset({"austria", "shanghai", "suzuka"})
GRID_STEP_M = 5.0


@dataclass(frozen=True)
class SignalGroup:
    start_index: int
    end_index: int
    peak: float
    sign: int = 0


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build complete F1 25 track semantics from downloaded F1Laps community telemetry."
    )
    parser.add_argument(
        "--telemetry-dir",
        type=Path,
        default=root / "data" / "community_telemetry" / "f1laps_f12025",
    )
    parser.add_argument("--output-dir", type=Path, default=root / "data" / "tracks")
    parser.add_argument(
        "--include-curated",
        action="store_true",
        help="Regenerate Austria, Shanghai and Suzuka instead of preserving their existing hand-curated profiles.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def channel_points(payload: dict[str, Any], channel: str) -> list[tuple[float, float]]:
    values = payload["original"][channel]
    points = sorted((float(item["x"]), float(item["y"])) for item in values)
    deduplicated: list[tuple[float, float]] = []
    for distance, value in points:
        if deduplicated and math.isclose(distance, deduplicated[-1][0], abs_tol=1e-6):
            deduplicated[-1] = (distance, value)
        else:
            deduplicated.append((distance, value))
    return deduplicated


def interpolate(points: list[tuple[float, float]], distance: float) -> float:
    xs = [item[0] for item in points]
    index = bisect.bisect_left(xs, distance)
    if index <= 0:
        return points[0][1]
    if index >= len(points):
        return points[-1][1]
    x0, y0 = points[index - 1]
    x1, y1 = points[index]
    if math.isclose(x0, x1):
        return y1
    ratio = (distance - x0) / (x1 - x0)
    return y0 + (y1 - y0) * ratio


def smooth(values: list[float], radius: int = 2) -> list[float]:
    result: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        result.append(statistics.fmean(values[start:end]))
    return result


def aggregate_laps(
    lap_payloads: list[dict[str, Any]], *, lap_length_m: float
) -> tuple[list[float], dict[str, list[float]], float]:
    grid = [float(value) for value in range(0, int(lap_length_m), int(GRID_STEP_M))]
    if not grid or not math.isclose(grid[-1], lap_length_m, abs_tol=1e-6):
        grid.append(float(lap_length_m))
    aggregate: dict[str, list[float]] = {}
    for channel in CHANNELS:
        per_lap = []
        for payload in lap_payloads:
            points = channel_points(payload, channel)
            source_lap_length_m = max(float(item["x"]) for item in payload["original"]["speed"])
            per_lap.append((points, source_lap_length_m))
        values = [
            statistics.median(
                interpolate(points, distance * source_lap_length_m / lap_length_m)
                for points, source_lap_length_m in per_lap
            )
            for distance in grid
        ]
        aggregate[channel] = smooth(values, radius=2 if channel in {"speed", "steer"} else 1)
    return grid, aggregate, lap_length_m


def close_group(
    groups: list[SignalGroup],
    start: int | None,
    end: int | None,
    peak: float,
    sign: int,
    grid: list[float],
    *,
    min_span_m: float,
    min_peak: float,
) -> None:
    if start is None or end is None:
        return
    span = grid[end] - grid[start] + GRID_STEP_M
    if peak >= min_peak and (span >= min_span_m or peak >= min_peak * 1.8):
        groups.append(SignalGroup(start, end, peak, sign))


def steering_groups(grid: list[float], steer: list[float]) -> list[SignalGroup]:
    groups: list[SignalGroup] = []
    start: int | None = None
    last_active: int | None = None
    current_sign = 0
    peak = 0.0
    max_gap_points = int(25.0 / GRID_STEP_M)
    for index, value in enumerate(steer):
        magnitude = abs(value)
        sign = 1 if value > 0 else -1
        if magnitude >= 0.055:
            if start is None:
                start = last_active = index
                current_sign = sign
                peak = magnitude
            elif sign != current_sign:
                close_group(groups, start, last_active, peak, current_sign, grid, min_span_m=15.0, min_peak=0.09)
                start = last_active = index
                current_sign = sign
                peak = magnitude
            else:
                last_active = index
                peak = max(peak, magnitude)
        elif start is not None and last_active is not None and index - last_active > max_gap_points:
            close_group(groups, start, last_active, peak, current_sign, grid, min_span_m=15.0, min_peak=0.09)
            start = last_active = None
            current_sign = 0
            peak = 0.0
    close_group(groups, start, last_active, peak, current_sign, grid, min_span_m=15.0, min_peak=0.09)

    merged: list[SignalGroup] = []
    for group in groups:
        if merged and merged[-1].sign == group.sign and grid[group.start_index] - grid[merged[-1].end_index] <= 35.0:
            previous = merged[-1]
            merged[-1] = SignalGroup(previous.start_index, group.end_index, max(previous.peak, group.peak), group.sign)
        else:
            merged.append(group)
    return merged


def threshold_groups(
    grid: list[float], values: list[float], *, threshold: float, min_span_m: float, min_peak: float
) -> list[SignalGroup]:
    groups: list[SignalGroup] = []
    start: int | None = None
    last_active: int | None = None
    peak = 0.0
    max_gap_points = int(20.0 / GRID_STEP_M)
    for index, value in enumerate(values):
        if value >= threshold:
            if start is None:
                start = index
            last_active = index
            peak = max(peak, value)
        elif start is not None and last_active is not None and index - last_active > max_gap_points:
            close_group(groups, start, last_active, peak, 0, grid, min_span_m=min_span_m, min_peak=min_peak)
            start = last_active = None
            peak = 0.0
    close_group(groups, start, last_active, peak, 0, grid, min_span_m=min_span_m, min_peak=min_peak)
    return groups


def range_values(values: list[float], start: int, end: int) -> list[float]:
    return values[max(start, 0) : min(end + 1, len(values))]


def nearest_corner_index(group: SignalGroup, corners: list[SignalGroup]) -> int:
    midpoint = (group.start_index + group.end_index) / 2.0
    return min(
        range(len(corners)),
        key=lambda index: abs(((corners[index].start_index + corners[index].end_index) / 2.0) - midpoint),
    )


def build_labels(
    grid: list[float], signals: dict[str, list[float]], corners: list[SignalGroup], brakes: list[SignalGroup]
) -> list[str]:
    labels = ["deployment_straight"] * len(grid)
    for group in corners:
        avg_speed = statistics.fmean(range_values(signals["speed"], group.start_index, group.end_index))
        avg_throttle = statistics.fmean(range_values(signals["throttle"], group.start_index, group.end_index))
        zone = "high_load_management" if avg_speed >= 190.0 and avg_throttle >= 0.62 else "apex_rotation"
        for index in range(group.start_index, group.end_index + 1):
            labels[index] = zone
        exit_end = min(len(labels) - 1, group.end_index + int(90.0 / GRID_STEP_M))
        for index in range(group.end_index + 1, exit_end + 1):
            if labels[index] == "deployment_straight":
                labels[index] = "exit_traction"
            if signals["throttle"][index] >= 0.96 and abs(signals["steer"][index]) < 0.045:
                break
    for group in brakes:
        for index in range(max(0, group.start_index - 1), min(len(labels) - 1, group.end_index + 1) + 1):
            labels[index] = "braking_entry"
    return labels


def grid_round(value: float) -> float:
    return round(float(value), 3)


def label_runs(labels: list[str], grid: list[float], lap_length_m: float) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    run_start = 0
    for index in range(1, len(labels)):
        if labels[index] == labels[run_start]:
            continue
        runs.append(
            {
                "zone_type": labels[run_start],
                "start_m": grid_round(grid[run_start]),
                "end_m": grid_round(grid[index]),
            }
        )
        run_start = index
    runs.append(
        {
            "zone_type": labels[run_start],
            "start_m": grid_round(grid[run_start]),
            "end_m": grid_round(lap_length_m),
        }
    )
    return [item for item in runs if item["end_m"] > item["start_m"]]


def merge_short_runs(runs: list[dict[str, Any]], *, min_length_m: float = 15.0) -> list[dict[str, Any]]:
    merged = [dict(item) for item in runs]
    changed = True
    while changed and len(merged) > 1:
        changed = False
        for index, run in enumerate(merged):
            if float(run["end_m"]) - float(run["start_m"]) >= min_length_m:
                continue
            if 0 < index < len(merged) - 1 and merged[index - 1]["zone_type"] == merged[index + 1]["zone_type"]:
                merged[index - 1]["end_m"] = merged[index + 1]["end_m"]
                del merged[index : index + 2]
            elif index == 0:
                merged[1]["start_m"] = run["start_m"]
                del merged[0]
            else:
                merged[index - 1]["end_m"] = run["end_m"]
                del merged[index]
            changed = True
            break

    coalesced: list[dict[str, Any]] = []
    for run in merged:
        if coalesced and coalesced[-1]["zone_type"] == run["zone_type"]:
            coalesced[-1]["end_m"] = run["end_m"]
        else:
            coalesced.append(dict(run))
    return coalesced


def segment_slice(grid: list[float], start_m: float, end_m: float) -> tuple[int, int]:
    start = max(0, bisect.bisect_left(grid, start_m))
    end = min(len(grid) - 1, bisect.bisect_right(grid, end_m) - 1)
    return start, max(start, end)


def overlapping_corner_number(start: int, end: int, corners: list[SignalGroup]) -> int | None:
    overlaps = [
        (index + 1, min(end, group.end_index) - max(start, group.start_index))
        for index, group in enumerate(corners)
        if min(end, group.end_index) >= max(start, group.start_index)
    ]
    if overlaps:
        return max(overlaps, key=lambda item: item[1])[0]
    if not corners:
        return None
    midpoint = (start + end) / 2.0
    return min(
        range(len(corners)),
        key=lambda index: abs(((corners[index].start_index + corners[index].end_index) / 2.0) - midpoint),
    ) + 1


def decorate_segments(
    runs: list[dict[str, Any]], grid: list[float], signals: dict[str, list[float]], corners: list[SignalGroup]
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    straight_number = 0
    for run_index, run in enumerate(runs):
        start, end = segment_slice(grid, run["start_m"], run["end_m"])
        corner_number = overlapping_corner_number(start, end, corners)
        zone = run["zone_type"]
        speed_values = range_values(signals["speed"], start, end)
        brake_values = range_values(signals["brake"], start, end)
        throttle_values = range_values(signals["throttle"], start, end)
        drs_values = range_values(signals["drs"], start, end)
        length = run["end_m"] - run["start_m"]
        if zone == "braking_entry":
            name = f"Corner {corner_number:02d} Braking" if corner_number else "Braking Zone"
            usage = "maximum_brake_pressure" if max(brake_values) >= 0.82 and max(speed_values) - min(speed_values) >= 70 else "late_brake_control"
        elif zone == "apex_rotation":
            name = f"Corner {corner_number:02d} Rotation" if corner_number else "Corner Rotation"
            usage = "slow_corner_rotation" if min(speed_values) < 115 else "yaw_balance"
        elif zone == "high_load_management":
            name = f"Corner {corner_number:02d} High Load" if corner_number else "High Load Complex"
            usage = "front_tyre_protection" if statistics.fmean(speed_values) >= 225 else "lateral_load_management"
        elif zone == "exit_traction":
            name = f"Corner {corner_number:02d} Exit" if corner_number else "Corner Exit"
            usage = "traction_rebuild" if min(throttle_values) < 0.65 else "traction_release"
        else:
            straight_number += 1
            if run_index == 0 or run_index == len(runs) - 1:
                name = "Main Straight"
                usage = "lap_restart_accel"
            else:
                name = f"Straight {straight_number:02d}"
                drs_fraction = sum(value >= 0.5 for value in drs_values) / max(len(drs_values), 1)
                if drs_fraction >= 0.25 and length >= 180:
                    usage = "primary_overtake_deploy"
                elif length >= 500:
                    usage = "primary_ers_deploy"
                elif length >= 180:
                    usage = "ers_prepare"
                else:
                    usage = "brake_setup"
        decorated.append({"name": name, **run, "usage": usage})
    return decorated


def build_profile(track_record: dict[str, Any], telemetry_dir: Path) -> dict[str, Any]:
    lap_records = track_record["laps"]
    lap_payloads = [load_json(telemetry_dir / item["file"]) for item in lap_records]
    lap_length_m = float(track_record["lap_length_m"])
    grid, signals, lap_length_m = aggregate_laps(lap_payloads, lap_length_m=lap_length_m)
    corners = steering_groups(grid, signals["steer"])
    brakes = threshold_groups(grid, signals["brake"], threshold=0.055, min_span_m=10.0, min_peak=0.30)
    if len(corners) < 5:
        raise RuntimeError(f"{track_record['track_name']}: only {len(corners)} corner signals detected")
    if len(brakes) < 3:
        raise RuntimeError(f"{track_record['track_name']}: only {len(brakes)} braking signals detected")
    runs = label_runs(build_labels(grid, signals, corners, brakes), grid, lap_length_m)
    segments = decorate_segments(merge_short_runs(runs), grid, signals, corners)
    braking_zones = []
    for group in brakes:
        corner_number = nearest_corner_index(group, corners) + 1
        braking_zones.append(
            {
                "name": f"Corner {corner_number:02d} Braking",
                "start_m": grid_round(grid[group.start_index]),
                "end_m": grid_round(min(lap_length_m, grid[group.end_index] + GRID_STEP_M)),
            }
        )
    corner_apexes = []
    for index, group in enumerate(corners, start=1):
        local_speeds = range_values(signals["speed"], group.start_index, group.end_index)
        apex_index = group.start_index + min(range(len(local_speeds)), key=local_speeds.__getitem__)
        span = grid[group.end_index] - grid[group.start_index] + GRID_STEP_M
        gear_start = max(group.start_index, apex_index - int(15.0 / GRID_STEP_M))
        gear_end = min(group.end_index, apex_index + int(10.0 / GRID_STEP_M))
        recommended_gear = max(
            1,
            min(8, int(round(statistics.median(range_values(signals["gear"], gear_start, gear_end))))),
        )
        corner_apexes.append(
            {
                "name": f"Corner {index:02d} Apex",
                "distance_m": grid_round(grid[apex_index]),
                "window_m": grid_round(max(15.0, min(75.0, span / 2.0))),
                "recommended_gear": recommended_gear,
            }
        )
    return {
        "track": track_record["track_name"],
        "track_id": track_record["track_id"],
        "lap_length_m": grid_round(lap_length_m),
        "source": {
            "provider": "F1Laps",
            "community": "F1Laps F1 25 public leaderboard",
            "leaderboard_url": track_record["leaderboard_url"],
            "retrieved_at": track_record.get("retrieved_at"),
            "lap_count": len(lap_records),
            "lap_ids": [item["lap_id"] for item in lap_records],
            "telemetry_channels": list(CHANNELS),
            "method": "lap-length calibrated 5 m resampling, per-channel multi-lap median, telemetry-derived braking/corner/exit segmentation",
            "distance_calibration": "Each community racing-line distance is linearly normalized to the F1 25 circuit lap distance.",
        },
        "quality": {
            "grid_step_m": GRID_STEP_M,
            "corner_signal_count": len(corners),
            "braking_zone_count": len(brakes),
            "semantic_segment_count": len(segments),
        },
        "braking_zones": braking_zones,
        "corner_apexes": corner_apexes,
        "semantic_segments": segments,
    }


def main() -> int:
    args = parse_args()
    telemetry_dir = args.telemetry_dir.resolve()
    output_dir = args.output_dir.resolve()
    manifest = load_json(telemetry_dir / "manifest.json")
    track_records = {item["profile_slug"]: dict(item, retrieved_at=manifest.get("retrieved_at")) for item in manifest["tracks"]}
    coverage = []
    for entry in F1_25_TRACK_CATALOG:
        output_path = output_dir / f"{entry.profile_slug}_segments.json"
        if entry.profile_slug in CURATED_PROFILE_SLUGS and not args.include_curated:
            if not output_path.exists():
                raise FileNotFoundError(f"curated track profile missing: {output_path}")
            profile = load_json(output_path)
            generation = "curated_existing"
        else:
            profile = build_profile(track_records[entry.profile_slug], telemetry_dir)
            write_json(output_path, profile)
            generation = "community_telemetry_generated"
        coverage.append(
            {
                "track_id": entry.track_id,
                "track": entry.track_name,
                "profile_slug": entry.profile_slug,
                "profile_file": output_path.name,
                "generation": generation,
                "lap_length_m": profile["lap_length_m"],
                "braking_zone_count": len(profile.get("braking_zones", [])),
                "corner_apex_count": len(profile.get("corner_apexes", [])),
                "semantic_segment_count": len(profile.get("semantic_segments", [])),
            }
        )
        print(f"{entry.track_id:02d} {entry.track_name}: {generation}")
    coverage_manifest = {
        "schema_version": "asurada.f1-25-track-semantics.v1",
        "game": "EA SPORTS F1 25",
        "track_layout_count": len(coverage),
        "curated_profile_count": sum(item["generation"] == "curated_existing" for item in coverage),
        "community_generated_profile_count": sum(item["generation"] == "community_telemetry_generated" for item in coverage),
        "telemetry_manifest": "data/community_telemetry/f1laps_f12025/manifest.json",
        "tracks": coverage,
    }
    write_json(output_dir / "f1_25_track_semantics_manifest.json", coverage_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

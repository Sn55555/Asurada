#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from f1_25_track_catalog import F1_25_TRACK_CATALOG


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asurada.brake_point_assist import BrakePointAssistController  # noqa: E402
from asurada.corner_gear_assist import CornerGearAssistController  # noqa: E402
from asurada.model_runtime import build_runtime_feature_row  # noqa: E402
from asurada.models import DriverState, SessionState, TyreState  # noqa: E402
from asurada.packet_snapshot import TRACK_NAMES  # noqa: E402
from asurada.strategy import StrategyEngine  # noqa: E402
from asurada.track_model import load_track_profile  # noqa: E402


def main() -> int:
    brake_controller = BrakePointAssistController.__new__(BrakePointAssistController)
    gear_controller = CornerGearAssistController.__new__(CornerGearAssistController)
    expected_names = {entry.track_id: entry.track_name for entry in F1_25_TRACK_CATALOG}
    checks: dict[str, bool] = {
        "catalog_has_27_layouts": len(F1_25_TRACK_CATALOG) == 27,
        "packet_track_ids_match_catalog": TRACK_NAMES == expected_names,
    }
    tracks: list[dict[str, object]] = []

    for entry in F1_25_TRACK_CATALOG:
        profile = load_track_profile(entry.track_name)
        loaded = profile is not None
        midpoint_classification = False
        boundary_classification = False
        next_segment_classification = False
        negative_distance_guard = False
        runtime_preview = False
        brake_target_count = 0
        gear_target_count = 0
        if profile is not None:
            midpoint_classification = all(
                profile.classify((segment.start_m + segment.end_m) / 2.0).zone_name == segment.name
                for segment in profile.semantic_segments
            )
            boundary_classification = all(
                profile.classify(segment.start_m).zone_name == segment.name
                for segment in profile.semantic_segments
            )
            next_segment_classification = all(
                profile.next_segment(segment.start_m).zone_name
                == profile.semantic_segments[(index + 1) % len(profile.semantic_segments)].name
                for index, segment in enumerate(profile.semantic_segments)
            )
            negative_distance_guard = profile.classify(-1.0).zone_type == "unavailable"
            brake_target_count = len(brake_controller._build_targets(profile))
            gear_target_count = len(gear_controller._build_targets(profile))
            current_segment = profile.semantic_segments[0]
            lap_distance_m = (current_segment.start_m + current_segment.end_m) / 2.0
            state = SessionState(
                session_uid=f"track-regression:{entry.profile_slug}",
                track=entry.track_name,
                lap_number=1,
                total_laps=5,
                weather="Clear",
                safety_car="NONE",
                player=DriverState(
                    car_index=0,
                    name="Player",
                    position=1,
                    lap=1,
                    gap_ahead_s=None,
                    gap_behind_s=None,
                    fuel_laps_remaining=6.0,
                    ers_pct=50.0,
                    drs_available=False,
                    tyre=TyreState(compound="C3", wear_pct=5.0, age_laps=1),
                    speed_kph=200.0,
                    status_tags=[],
                ),
                rivals=[],
                source_timestamp_ms=1,
                raw={
                    "lap_distance_m": lap_distance_m,
                    "throttle": 0.5,
                    "brake": 0.0,
                    "steer": 0.0,
                },
            )
            context = StrategyEngine.__new__(StrategyEngine)._build_context(state, [state])
            runtime_row = build_runtime_feature_row(state=state, context=context)
            expected_next = profile.next_segment(lap_distance_m)
            runtime_preview = (
                context.next_track_segment == expected_next.zone_name
                and context.next_track_usage == expected_next.usage
                and runtime_row["next_track_segment"] == expected_next.zone_name
                and runtime_row["next_track_usage"] == expected_next.usage
            )
        track_ok = all(
            (
                loaded,
                midpoint_classification,
                boundary_classification,
                next_segment_classification,
                negative_distance_guard,
                runtime_preview,
                brake_target_count > 0,
                gear_target_count > 0,
            )
        )
        checks[f"track:{entry.profile_slug}"] = track_ok
        tracks.append(
            {
                "track_id": entry.track_id,
                "track": entry.track_name,
                "loaded": loaded,
                "semantic_segments": len(profile.semantic_segments) if profile else 0,
                "brake_targets": brake_target_count,
                "gear_targets": gear_target_count,
                "runtime_preview": runtime_preview,
                "passed": track_ok,
            }
        )

    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "summary": {
            "track_layouts": len(tracks),
            "passed_tracks": sum(bool(item["passed"]) for item in tracks),
            "brake_supported_tracks": sum(int(item["brake_targets"]) > 0 for item in tracks),
            "gear_supported_tracks": sum(int(item["gear_targets"]) > 0 for item in tracks),
        },
        "tracks": tracks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

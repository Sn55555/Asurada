from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import SessionState
from .track_model import load_track_profile


@dataclass
class SegmentAnalysis:
    """Aggregated per-segment counters for lap review."""

    name: str
    zone_type: str
    sample_count: int = 0
    unstable_events: int = 0
    overload_events: int = 0
    heavy_braking_events: int = 0
    max_speed_kph: float = 0.0
    min_speed_kph: float = 0.0


@dataclass
class DynamicsPhaseSummary:
    """Aggregated driver-dynamics summary for entry, apex, and exit phases."""

    phase: str
    sample_count: int = 0
    unstable_events: int = 0
    overload_events: int = 0
    heavy_braking_events: int = 0
    avg_speed_kph: float = 0.0


@dataclass
class LapAnalysisSummary:
    """Compact single-lap summary used by console output and JSON report."""

    max_speed_kph: float
    min_speed_kph: float
    heavy_braking_events: int
    unstable_events: int
    overload_events: int
    sector_transitions: int
    top_risk_segments: list[SegmentAnalysis] = field(default_factory=list)
    deployment_segments: list[SegmentAnalysis] = field(default_factory=list)
    dynamics_phases: list[DynamicsPhaseSummary] = field(default_factory=list)
    driver_style_summary: list[str] = field(default_factory=list)

    def to_report_dict(self, track: str, sample_count: int) -> dict:
        return {
            "track": track,
            "sample_count": sample_count,
            "summary": {
                "max_speed_kph": self.max_speed_kph,
                "min_speed_kph": self.min_speed_kph,
                "heavy_braking_events": self.heavy_braking_events,
                "unstable_events": self.unstable_events,
                "overload_events": self.overload_events,
                "sector_transitions": self.sector_transitions,
            },
            "top_risk_segments": [asdict(item) for item in self.top_risk_segments],
            "deployment_segments": [asdict(item) for item in self.deployment_segments],
            "dynamics_phases": [asdict(item) for item in self.dynamics_phases],
            "driver_style_summary": list(self.driver_style_summary),
        }


def summarize_lap(states: list[SessionState]) -> LapAnalysisSummary:
    # 备注:
    # 单圈总结优先回答三个问题:
    # 1. 速度范围如何
    # 2. 动态/重刹问题集中在哪
    # 3. 哪些区段最像部署主段
    if not states:
        return LapAnalysisSummary(0.0, 0.0, 0, 0, 0, 0, [], [])

    speeds = [state.player.speed_kph for state in states]
    heavy_braking = 0
    unstable = 0
    overload = 0
    sector_transitions = 0
    prev_sector = None
    segment_buckets: dict[tuple[str, str], SegmentAnalysis] = {}
    phase_buckets: dict[str, DynamicsPhaseSummary] = {
        "entry": DynamicsPhaseSummary(phase="entry"),
        "apex": DynamicsPhaseSummary(phase="apex"),
        "exit": DynamicsPhaseSummary(phase="exit"),
    }
    profile = load_track_profile(states[0].track)

    for state in states:
        tags = set(state.player.status_tags)
        heavy_braking += int("heavy_braking" in tags)
        unstable += int("unstable" in tags)
        overload += int("front_tyre_overload" in tags)
        sector = state.raw.get("sector")
        if prev_sector is not None and sector != prev_sector:
            sector_transitions += 1
        prev_sector = sector

        if profile is not None:
            classified = profile.classify(float(state.raw.get("lap_distance_m", 0.0)))
            key = (classified.zone_name, classified.zone_type)
            bucket = segment_buckets.setdefault(
                key,
                SegmentAnalysis(
                    name=classified.zone_name,
                    zone_type=classified.zone_type,
                    min_speed_kph=state.player.speed_kph,
                ),
            )
            bucket.sample_count += 1
            bucket.unstable_events += int("unstable" in tags)
            bucket.overload_events += int("front_tyre_overload" in tags)
            bucket.heavy_braking_events += int("heavy_braking" in tags)
            bucket.max_speed_kph = max(bucket.max_speed_kph, state.player.speed_kph)
            bucket.min_speed_kph = min(bucket.min_speed_kph, state.player.speed_kph)

            phase = _phase_name(classified.zone_type)
            phase_bucket = phase_buckets[phase]
            phase_bucket.sample_count += 1
            phase_bucket.unstable_events += int("unstable" in tags)
            phase_bucket.overload_events += int("front_tyre_overload" in tags)
            phase_bucket.heavy_braking_events += int("heavy_braking" in tags)
            phase_bucket.avg_speed_kph += state.player.speed_kph

    ranked_risk = sorted(
        segment_buckets.values(),
        key=lambda item: (
            item.unstable_events * 4
            + item.overload_events * 3
            + item.heavy_braking_events * 2
            + item.sample_count * 0.05
        ),
        reverse=True,
    )
    deployment_segments = sorted(
        [item for item in segment_buckets.values() if item.zone_type == "deployment_straight"],
        key=lambda item: item.max_speed_kph,
        reverse=True,
    )
    dynamics_phases = []
    for phase in ("entry", "apex", "exit"):
        bucket = phase_buckets[phase]
        if bucket.sample_count:
            bucket.avg_speed_kph = bucket.avg_speed_kph / bucket.sample_count
        dynamics_phases.append(bucket)

    style_tags = []
    if heavy_braking >= 40:
        style_tags.append("heavy_brake_bias")
    if unstable >= 8:
        style_tags.append("rotation_instability")
    if overload >= 8:
        style_tags.append("front_axle_stress")
    if max(speeds) >= 320:
        style_tags.append("straightline_commit")
    if not style_tags:
        style_tags.append("balanced_lap")

    return LapAnalysisSummary(
        max_speed_kph=max(speeds),
        min_speed_kph=min(speeds),
        heavy_braking_events=heavy_braking,
        unstable_events=unstable,
        overload_events=overload,
        sector_transitions=sector_transitions,
        top_risk_segments=ranked_risk[:4],
        deployment_segments=deployment_segments[:3],
        dynamics_phases=dynamics_phases,
        driver_style_summary=style_tags,
    )


def _phase_name(zone_type: str) -> str:
    """Map semantic zone types into lap-review dynamics phases."""

    if zone_type == "braking_entry":
        return "entry"
    if zone_type == "apex_rotation" or zone_type == "high_load_management":
        return "apex"
    return "exit"

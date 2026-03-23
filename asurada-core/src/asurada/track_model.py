from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class TrackZone:
    """Track classification result for a single lap-distance sample."""

    zone_type: str
    zone_name: str
    usage: str = ""


@dataclass
class SemanticSegment:
    """Named semantic segment loaded from track JSON."""

    name: str
    zone_type: str
    start_m: float
    end_m: float
    usage: str = ""


@dataclass
class CornerApex:
    name: str
    distance_m: float
    window_m: float


@dataclass
class BrakingZone:
    name: str
    start_m: float
    end_m: float


@dataclass
class TrackProfile:
    """Per-track semantic map used by strategy and analysis."""

    track: str
    lap_length_m: float
    semantic_segments: list[SemanticSegment]
    braking_zones: list[BrakingZone]
    corner_apexes: list[CornerApex]

    def classify(self, lap_distance_m: float) -> TrackZone:
        # 备注:
        # 分类优先级是 semantic segment -> braking zone -> corner apex -> fallback straight。
        # 这样细语义段会压过旧的粗粒度 braking/corner 回退逻辑。
        wrapped = lap_distance_m % self.lap_length_m if self.lap_length_m else lap_distance_m

        for segment in self.semantic_segments:
            if segment.start_m <= wrapped <= segment.end_m:
                return TrackZone(zone_type=segment.zone_type, zone_name=segment.name, usage=segment.usage)

        for zone in self.braking_zones:
            if zone.start_m <= wrapped <= zone.end_m:
                return TrackZone(zone_type="braking", zone_name=zone.name)

        for apex in self.corner_apexes:
            if abs(wrapped - apex.distance_m) <= apex.window_m:
                return TrackZone(zone_type="corner", zone_name=apex.name)

        return TrackZone(zone_type="straight", zone_name="Straight")

    def segment_order(self, segment_name: str) -> int | None:
        for index, segment in enumerate(self.semantic_segments):
            if segment.name == segment_name:
                return index
        return None


@lru_cache(maxsize=8)
def load_track_profile(track_name: str) -> TrackProfile | None:
    # 备注:
    # 赛道模型按文件名加载并做 LRU 缓存，避免回放过程中重复读 JSON。
    normalized = track_name.strip().lower()
    root = Path(__file__).resolve().parents[2]
    candidate = root / "data" / "tracks" / f"{normalized}_segments.json"
    if not candidate.exists():
        return None

    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return TrackProfile(
        track=payload["track"],
        lap_length_m=float(payload["lap_length_m"]),
        semantic_segments=[
            SemanticSegment(
                name=item["name"],
                zone_type=item["zone_type"],
                start_m=float(item["start_m"]),
                end_m=float(item["end_m"]),
                usage=item.get("usage", ""),
            )
            for item in payload.get("semantic_segments", [])
        ],
        braking_zones=[
            BrakingZone(
                name=item["name"],
                start_m=float(item["start_m"]),
                end_m=float(item["end_m"]),
            )
            for item in payload.get("braking_zones", [])
        ],
        corner_apexes=[
            CornerApex(
                name=item["name"],
                distance_m=float(item["distance_m"]),
                window_m=float(item["window_m"]),
            )
            for item in payload.get("corner_apexes", [])
        ],
    )

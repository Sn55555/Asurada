from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path


class LapCsvSource:
    """Reads recorder CSV rows and emits normalized snapshot payloads."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __iter__(self) -> Iterator[dict]:
        # 备注:
        # CSV 输入本质是“单车单圈时序样本”，这里一次性读入后再逐行归一化，
        # 便于先拿到 total_distance 和 total_laps 这类整圈上下文。
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        total_distance = max(float(row["lap_distance_m"]) for row in rows) if rows else 0.0
        total_laps = int(rows[-1]["lap_number"]) if rows else 1

        for row in rows:
            yield self._normalize_row(row, total_distance=total_distance, total_laps=total_laps)

    def _normalize_row(self, row: dict[str, str], total_distance: float, total_laps: int) -> dict:
        # 备注:
        # 这层只负责把 recorder 字段映射到项目统一 snapshot 结构。
        # 对手态势、比赛事件等比赛级语义不在 CSV 单圈路径里构造。
        speed = float(row["speed_kmh"])
        throttle = float(row["throttle"])
        brake = float(row["brake"])
        steer = float(row["steer"])
        g_lat = float(row["g_force_lateral"])
        g_lon = float(row["g_force_longitudinal"])
        tags = build_dynamic_tags(speed, throttle, brake, steer, g_lat, g_lon)
        ers_pct = min(max(float(row["ers_store_energy"]) / 4_000_000.0 * 100.0, 0.0), 100.0)
        lap_distance = float(row["lap_distance_m"])

        return {
            "session_uid": f"csv-{self.path.stem}",
            "track": row["track_name"],
            "lap_number": int(row["lap_number"]),
            "total_laps": total_laps,
            "weather": "Unknown",
            "safety_car": "NONE",
            "source_timestamp_ms": int(float(row["session_time_s"]) * 1000),
            "player": {
                "car_index": 0,
                "name": "CSV Driver",
                "position": 1,
                "lap": int(row["lap_number"]),
                "gap_ahead_s": None,
                "gap_behind_s": None,
                "fuel_laps_remaining": float(row["fuel_remaining_laps"]),
                "ers_pct": ers_pct,
                "drs_available": row["drs"] == "1",
                "speed_kph": speed,
                "tyre": {
                    "compound": "Unknown",
                    "wear_pct": estimate_tyre_wear(lap_distance, total_distance),
                    "age_laps": int(float(row["tyres_age_laps"])),
                },
                "status_tags": tags,
            },
            "rivals": [],
            "raw": {
                "session_time_s": float(row["session_time_s"]),
                "frame_identifier": int(row["frame_identifier"]),
                "overall_frame_identifier": int(row["overall_frame_identifier"]),
                "lap_time_s": float(row["lap_time_s"]),
                "lap_distance_m": lap_distance,
                "sector": int(row["sector"]),
                "throttle": throttle,
                "brake": brake,
                "steer": steer,
                "gear": int(row["gear"]),
                "rpm": int(row["rpm"]),
                "fuel_in_tank": float(row["fuel_in_tank"]),
                "ers_store_energy": float(row["ers_store_energy"]),
                "ers_deploy_mode": int(row["ers_deploy_mode"]),
                "g_force_lateral": g_lat,
                "g_force_longitudinal": g_lon,
                "g_force_vertical": float(row["g_force_vertical"]),
                "yaw": float(row["yaw"]),
                "pitch": float(row["pitch"]),
                "roll": float(row["roll"]),
                "world_position_x": float(row["world_position_x"]),
                "world_position_y": float(row["world_position_y"]),
                "world_position_z": float(row["world_position_z"]),
                "current_lap_invalid": row["current_lap_invalid"] == "1",
            },
        }


def estimate_tyre_wear(lap_distance: float, total_distance: float) -> float:
    """Estimate coarse tyre wear for CSV-only single-lap analysis."""

    if total_distance <= 0:
        return 12.0
    return min(75.0, 8.0 + 52.0 * (lap_distance / total_distance))


def build_dynamic_tags(
    speed_kmh: float,
    throttle: float,
    brake: float,
    steer: float,
    g_force_lateral: float,
    g_force_longitudinal: float,
) -> list[str]:
    """Build lightweight dynamic tags from recorder telemetry features."""

    # 备注:
    # 这里是 CSV 原型链路的轻量动态标签器。
    # 真实 PDU 路径下会叠加 wheel slip、damage 等更完整的信息。
    tags: list[str] = []

    if abs(g_force_lateral) > 4.5 and abs(steer) > 0.35:
        tags.append("unstable")
    elif abs(g_force_lateral) > 3.6 and abs(steer) > 0.28:
        if steer > 0:
            tags.append("right_hand_limit")
        else:
            tags.append("left_hand_limit")

    if brake > 0.72 and g_force_longitudinal < -3.5:
        tags.append("heavy_braking")

    if throttle > 0.82 and abs(steer) > 0.22 and speed_kmh > 150:
        tags.append("aggressive_exit")

    if abs(g_force_lateral) > 3.8 and brake > 0.15:
        tags.append("front_tyre_overload")

    if not tags:
        tags.append("stable")
    return tags

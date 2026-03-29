from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .track_model import load_track_profile


class DebugDashboardBuilder:
    """Builds a static HTML dashboard from the replay log.

    备注:
    这里故意保持“零前端依赖”，便于在 Pi 或最小环境里直接生成、
    打开和共享调试页面。
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_from_session_log(self, session_log_path: Path) -> Path:
        # 备注:
        # dashboard 只消费 replay logger 产出的 JSONL，不直接依赖运行时对象。
        # 这样回放结束后仍可离线重建页面。
        rows = []
        if session_log_path.exists():
            with session_log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            # 备注:
                            # 回放被中断时 JSONL 末尾可能留下半行。
                            # dashboard 重建跳过坏行，避免整个调试页失效。
                            continue
        capture_summary_path = self.output_dir.parent / "capture_summary.json"
        capture_summary = {}
        if capture_summary_path.exists():
            capture_summary = json.loads(capture_summary_path.read_text(encoding="utf-8"))

        latest = rows[-1] if rows else {}
        last_rows = rows
        timing_summary = self._build_timing_summary(rows)
        track_name = latest.get("track") if latest else None
        track_profile = load_track_profile(str(track_name)) if track_name else None
        frames = []
        laps = []
        seen_laps = set()

        for row_index, row in enumerate(last_rows):
            player = row.get("player", {})
            raw = row.get("raw", {})
            debug = row.get("debug", {})
            context = debug.get("context", {})
            rivals = row.get("rivals", [])
            messages = row.get("messages", [])
            lap_number = int(row.get("lap_number", 0))
            frame_identifier = int(raw.get("frame_identifier", 0))
            player_position = int(player.get("position", 0))
            front_rival = next((item for item in rivals if int(item.get("position", 0)) == player_position - 1), None)
            rear_rival = next((item for item in rivals if int(item.get("position", 0)) == player_position + 1), None)

            if lap_number not in seen_laps:
                laps.append(lap_number)
                seen_laps.add(lap_number)

            frames.append(
                {
                    "frame": frame_identifier,
                    "lap": lap_number,
                    "session_time_s": float(raw.get("session_time_s", 0.0)),
                    "total_laps": int((raw.get("session_packet", {}) or {}).get("total_laps", 0) or 0),
                    "track": row.get("track"),
                    "speed": float(player.get("speed_kph", 0.0)),
                    "top_priority": messages[0]["priority"] if messages else 0,
                    "top_message": messages[0]["title"] if messages else "",
                    "top_detail": messages[0]["detail"] if messages else "",
                    "messages": messages,
                    "position": player_position,
                    "track_segment": context.get("track_segment"),
                    "track_usage": context.get("track_usage"),
                    "player_world_x": raw.get("world_position_x"),
                    "player_world_z": raw.get("world_position_z"),
                    "front_world_x": raw.get("front_rival_world_position_x"),
                    "front_world_z": raw.get("front_rival_world_position_z"),
                    "front_world_name": raw.get("front_rival_name"),
                    "rear_world_x": raw.get("rear_rival_world_position_x"),
                    "rear_world_z": raw.get("rear_rival_world_position_z"),
                    "rear_world_name": raw.get("rear_rival_name"),
                    "front_rival": self._build_rival_summary(
                        front_rival,
                        relation="front",
                        display_gap_ahead_s=raw.get("front_rival_car_gap_ahead_s"),
                        display_gap_behind_s=raw.get("front_rival_car_gap_behind_s"),
                    ),
                    "rear_rival": self._build_rival_summary(
                        rear_rival,
                        relation="rear",
                        display_gap_ahead_s=raw.get("rear_rival_car_gap_ahead_s"),
                        display_gap_behind_s=raw.get("rear_rival_car_gap_behind_s"),
                    ),
                    "stage_two_model_debug": self._extract_stage_two_model_debug(row),
                }
            )

        payload = {
            "latest": {
                "track": latest.get("track"),
            },
            "timing_summary": timing_summary,
            "frames": frames,
            "laps": sorted(laps),
        }

        html = self._render_html(payload)
        output_path = self.output_dir / "debug_dashboard.html"
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _build_timing_summary(self, rows: list[dict]) -> dict:
        if not rows:
            return {
                "capture_wall_seconds": 0.0,
                "capture_wall_label": "0m 0s",
                "session_span_seconds": 0.0,
                "session_span_label": "0m 0s",
            }

        timestamps = [int(row.get("raw", {}).get("source_timestamp_ms", 0)) for row in rows if row.get("raw", {}).get("source_timestamp_ms") is not None]
        session_times = [float(row.get("raw", {}).get("session_time_s", 0.0)) for row in rows if row.get("raw", {}).get("session_time_s") is not None]
        capture_wall_seconds = max((max(timestamps) - min(timestamps)) / 1000.0, 0.0) if timestamps else 0.0
        session_span_seconds = max(max(session_times) - min(session_times), 0.0) if session_times else 0.0
        return {
            "capture_wall_seconds": round(capture_wall_seconds, 3),
            "capture_wall_label": self._format_duration(capture_wall_seconds),
            "session_span_seconds": round(session_span_seconds, 3),
            "session_span_label": self._format_duration(session_span_seconds),
        }

    def _format_duration(self, seconds: float) -> str:
        total_seconds = int(round(seconds))
        minutes, remaining_seconds = divmod(total_seconds, 60)
        hours, remaining_minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {remaining_minutes}m {remaining_seconds}s"
        return f"{minutes}m {remaining_seconds}s"

    def _build_rival_summary(
        self,
        rival: dict | None,
        *,
        relation: str,
        display_gap_ahead_s: float | None = None,
        display_gap_behind_s: float | None = None,
    ) -> dict:
        if not isinstance(rival, dict):
            return {
                "name": "-",
                "position": None,
                "display_gap_ahead_s": None,
                "display_gap_behind_s": None,
                "speed_kph": None,
                "ers_pct": None,
                "drs_available": None,
                "relation": relation,
            }

        if display_gap_ahead_s is None:
            display_gap_ahead_s = rival.get("gap_ahead_s")
        if display_gap_behind_s is None:
            display_gap_behind_s = rival.get("gap_behind_s")

        return {
            "name": rival.get("name") or "-",
            "position": int(rival.get("position", 0)) if rival.get("position") is not None else None,
            "display_gap_ahead_s": display_gap_ahead_s,
            "display_gap_behind_s": display_gap_behind_s,
            "speed_kph": rival.get("speed_kph"),
            "ers_pct": rival.get("ers_pct"),
            "drs_available": rival.get("drs_available"),
            "relation": relation,
        }

    def _extract_parsed_packet_fields(self, row: dict) -> dict:
        raw = row.get("raw", {})
        player = row.get("player", {})
        session_packet = raw.get("session_packet", {}) or {}
        lap_positions = raw.get("lap_positions", {}) or {}
        lobby_info = raw.get("lobby_info", {}) or {}
        lobby_player = lobby_info.get("player", {}) or {}
        return {
            "frame_identifier": raw.get("frame_identifier"),
            "session_time_s": raw.get("session_time_s"),
            "timing_mode": raw.get("timing_mode"),
            "timing_support_level": raw.get("timing_support_level"),
            "lap_number": row.get("lap_number"),
            "lap_distance_m": raw.get("lap_distance_m"),
            "current_lap_time_ms": raw.get("current_lap_time_ms"),
            "last_lap_time_ms": raw.get("last_lap_time_ms"),
            "sector1_time_ms": raw.get("sector1_time_ms"),
            "sector2_time_ms": raw.get("sector2_time_ms"),
            "delta_to_car_in_front_minutes": raw.get("delta_to_car_in_front_minutes"),
            "delta_to_car_in_front_ms": raw.get("delta_to_car_in_front_ms"),
            "delta_to_race_leader_minutes": raw.get("delta_to_race_leader_minutes"),
            "delta_to_race_leader_ms": raw.get("delta_to_race_leader_ms"),
            "official_delta_to_car_in_front_s": raw.get("official_delta_to_car_in_front_s"),
            "official_delta_to_race_leader_s": raw.get("official_delta_to_race_leader_s"),
            "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
            "official_gap_behind_s": raw.get("official_gap_behind_s"),
            "official_gap_source_ahead": raw.get("official_gap_source_ahead"),
            "official_gap_source_behind": raw.get("official_gap_source_behind"),
            "official_gap_confidence_ahead": raw.get("official_gap_confidence_ahead"),
            "official_gap_confidence_behind": raw.get("official_gap_confidence_behind"),
            "estimated_gap_ahead_s": raw.get("estimated_gap_ahead_s"),
            "estimated_gap_behind_s": raw.get("estimated_gap_behind_s"),
            "estimated_gap_source_ahead": raw.get("estimated_gap_source_ahead"),
            "estimated_gap_source_behind": raw.get("estimated_gap_source_behind"),
            "estimated_gap_confidence_ahead": raw.get("estimated_gap_confidence_ahead"),
            "estimated_gap_confidence_behind": raw.get("estimated_gap_confidence_behind"),
            "rival_gap_sources": raw.get("rival_gap_sources"),
            "pit_status": raw.get("pit_status"),
            "speed_kph": player.get("speed_kph"),
            "throttle": raw.get("throttle"),
            "brake": raw.get("brake"),
            "steer": raw.get("steer"),
            "gear": raw.get("gear"),
            "rpm": raw.get("rpm"),
            "fuel_in_tank": raw.get("fuel_in_tank"),
            "fuel_capacity": raw.get("fuel_capacity"),
            "ers_store_energy": raw.get("ers_store_energy"),
            "ers_deploy_mode": raw.get("ers_deploy_mode"),
            "tyres_wear_pct": raw.get("tyres_wear_pct"),
            "tyres_damage_pct": raw.get("tyres_damage_pct"),
            "tyre_blisters_pct": raw.get("tyre_blisters_pct"),
            "brakes_damage_pct": raw.get("brakes_damage_pct"),
            "wheel_slip_ratio": raw.get("wheel_slip_ratio"),
            "wheel_slip_angle": raw.get("wheel_slip_angle"),
            "wheel_lat_force": raw.get("wheel_lat_force"),
            "wheel_long_force": raw.get("wheel_long_force"),
            "local_velocity": raw.get("local_velocity"),
            "angular_velocity": raw.get("angular_velocity"),
            "world_forward_dir": raw.get("world_forward_dir"),
            "world_right_dir": raw.get("world_right_dir"),
            "event_code": raw.get("event_code"),
            "event_detail": raw.get("event_detail"),
            "track_temperature_c": session_packet.get("track_temperature_c"),
            "air_temperature_c": session_packet.get("air_temperature_c"),
            "weather": row.get("weather"),
            "weather_forecast_samples_head": (session_packet.get("weather_forecast_samples") or [])[:3],
            "forecast_accuracy": session_packet.get("forecast_accuracy"),
            "ai_difficulty": session_packet.get("ai_difficulty"),
            "season_link_identifier": session_packet.get("season_link_identifier"),
            "weekend_link_identifier": session_packet.get("weekend_link_identifier"),
            "session_link_identifier": session_packet.get("session_link_identifier"),
            "pit_stop_window_ideal_lap": session_packet.get("pit_stop_window_ideal_lap"),
            "pit_stop_window_latest_lap": session_packet.get("pit_stop_window_latest_lap"),
            "pit_stop_rejoin_position": session_packet.get("pit_stop_rejoin_position"),
            "game_mode": session_packet.get("game_mode"),
            "rule_set": session_packet.get("rule_set"),
            "time_of_day_minutes": session_packet.get("time_of_day_minutes"),
            "session_length": session_packet.get("session_length"),
            "weekend_structure": session_packet.get("weekend_structure"),
            "sector2_lap_distance_start_m": session_packet.get("sector2_lap_distance_start_m"),
            "sector3_lap_distance_start_m": session_packet.get("sector3_lap_distance_start_m"),
            "lap_positions_num_laps": lap_positions.get("num_laps"),
            "lap_positions_lap_start": lap_positions.get("lap_start"),
            "player_lap_positions_head": (lap_positions.get("player_lap_positions") or [])[:6],
            "lobby_num_players": lobby_info.get("num_players"),
            "lobby_player_name": lobby_player.get("name"),
            "lobby_player_ready_status": lobby_player.get("ready_status"),
        }

    def _extract_field_sources(self) -> dict:
        return {
            "Session": [
                "track_temperature_c",
                "air_temperature_c",
                "weather",
                "weather_forecast_samples_head",
                "forecast_accuracy",
                "ai_difficulty",
                "season_link_identifier",
                "weekend_link_identifier",
                "session_link_identifier",
                "pit_stop_window_ideal_lap",
                "pit_stop_window_latest_lap",
                "pit_stop_rejoin_position",
                "game_mode",
                "rule_set",
                "time_of_day_minutes",
                "session_length",
                "weekend_structure",
                "sector2_lap_distance_start_m",
                "sector3_lap_distance_start_m",
                "lap_positions_num_laps",
                "lap_positions_lap_start",
                "player_lap_positions_head",
                "lobby_num_players",
                "lobby_player_name",
                "lobby_player_ready_status",
            ],
            "LapData": [
                "lap_number",
                "timing_mode",
                "timing_support_level",
                "lap_distance_m",
                "current_lap_time_ms",
                "last_lap_time_ms",
                "sector1_time_ms",
                "sector2_time_ms",
                "delta_to_car_in_front_minutes",
                "delta_to_car_in_front_ms",
                "delta_to_race_leader_minutes",
                "delta_to_race_leader_ms",
                "official_delta_to_car_in_front_s",
                "official_delta_to_race_leader_s",
                "official_gap_ahead_s",
                "official_gap_behind_s",
                "official_gap_source_ahead",
                "official_gap_source_behind",
                "official_gap_confidence_ahead",
                "official_gap_confidence_behind",
                "estimated_gap_ahead_s",
                "estimated_gap_behind_s",
                "estimated_gap_source_ahead",
                "estimated_gap_source_behind",
                "estimated_gap_confidence_ahead",
                "estimated_gap_confidence_behind",
                "rival_gap_sources",
                "pit_status",
            ],
            "CarTelemetry": [
                "speed_kph",
                "throttle",
                "brake",
                "steer",
                "gear",
                "rpm",
            ],
            "CarStatus": [
                "fuel_in_tank",
                "fuel_capacity",
                "ers_store_energy",
                "ers_deploy_mode",
            ],
            "CarDamage": [
                "tyres_wear_pct",
                "tyres_damage_pct",
                "tyre_blisters_pct",
                "brakes_damage_pct",
            ],
            "Motion": [
                "world_forward_dir",
                "world_right_dir",
            ],
            "MotionEx": [
                "wheel_slip_ratio",
                "wheel_slip_angle",
                "wheel_lat_force",
                "wheel_long_force",
                "local_velocity",
                "angular_velocity",
            ],
            "Event": [
                "event_code",
                "event_detail",
            ],
        }

    def _extract_field_trace(self) -> dict:
        return {
            "lap_number": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "lap_number"},
            "timing_mode": {"packet": "LapData", "decoder_method": "_timing_mode_name", "snapshot_key": "raw.timing_mode"},
            "timing_support_level": {"packet": "LapData", "decoder_method": "_timing_support_level", "snapshot_key": "raw.timing_support_level"},
            "lap_distance_m": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.lap_distance_m"},
            "current_lap_time_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.current_lap_time_ms"},
            "last_lap_time_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.last_lap_time_ms"},
            "sector1_time_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.sector1_time_ms"},
            "sector2_time_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.sector2_time_ms"},
            "delta_to_car_in_front_minutes": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.delta_to_car_in_front_minutes"},
            "delta_to_car_in_front_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.delta_to_car_in_front_ms"},
            "delta_to_race_leader_minutes": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.delta_to_race_leader_minutes"},
            "delta_to_race_leader_ms": {"packet": "LapData", "decoder_method": "_decode_lap_data", "snapshot_key": "raw.delta_to_race_leader_ms"},
            "official_delta_to_car_in_front_s": {"packet": "LapData", "decoder_method": "_lap_delta_seconds", "snapshot_key": "raw.official_delta_to_car_in_front_s"},
            "official_delta_to_race_leader_s": {"packet": "LapData", "decoder_method": "_lap_delta_seconds", "snapshot_key": "raw.official_delta_to_race_leader_s"},
            "official_gap_ahead_s": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.official_gap_ahead_s"},
            "official_gap_behind_s": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.official_gap_behind_s"},
            "official_gap_source_ahead": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.official_gap_source_ahead"},
            "official_gap_source_behind": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.official_gap_source_behind"},
            "official_gap_confidence_ahead": {"packet": "LapData", "decoder_method": "_official_gap_confidence_from_source", "snapshot_key": "raw.official_gap_confidence_ahead"},
            "official_gap_confidence_behind": {"packet": "LapData", "decoder_method": "_official_gap_confidence_from_source", "snapshot_key": "raw.official_gap_confidence_behind"},
            "estimated_gap_ahead_s": {"packet": "LapData", "decoder_method": "_estimate_gap_seconds", "snapshot_key": "raw.estimated_gap_ahead_s"},
            "estimated_gap_behind_s": {"packet": "LapData", "decoder_method": "_estimate_gap_seconds", "snapshot_key": "raw.estimated_gap_behind_s"},
            "estimated_gap_source_ahead": {"packet": "LapData", "decoder_method": "_estimate_gap_seconds", "snapshot_key": "raw.estimated_gap_source_ahead"},
            "estimated_gap_source_behind": {"packet": "LapData", "decoder_method": "_estimate_gap_seconds", "snapshot_key": "raw.estimated_gap_source_behind"},
            "estimated_gap_confidence_ahead": {"packet": "LapData", "decoder_method": "_estimated_gap_confidence_from_source", "snapshot_key": "raw.estimated_gap_confidence_ahead"},
            "estimated_gap_confidence_behind": {"packet": "LapData", "decoder_method": "_estimated_gap_confidence_from_source", "snapshot_key": "raw.estimated_gap_confidence_behind"},
            "rival_gap_sources": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.rival_gap_sources"},
            "pit_status": {"packet": "LapData", "decoder_method": "_normalize_snapshot", "snapshot_key": "raw.pit_status"},
            "speed_kph": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "player.speed_kph"},
            "throttle": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "raw.throttle"},
            "brake": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "raw.brake"},
            "steer": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "raw.steer"},
            "gear": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "raw.gear"},
            "rpm": {"packet": "CarTelemetry", "decoder_method": "_decode_car_telemetry", "snapshot_key": "raw.rpm"},
            "fuel_in_tank": {"packet": "CarStatus", "decoder_method": "_decode_car_status", "snapshot_key": "raw.fuel_in_tank"},
            "fuel_capacity": {"packet": "CarStatus", "decoder_method": "_decode_car_status", "snapshot_key": "raw.fuel_capacity"},
            "ers_store_energy": {"packet": "CarStatus", "decoder_method": "_decode_car_status", "snapshot_key": "raw.ers_store_energy"},
            "ers_deploy_mode": {"packet": "CarStatus", "decoder_method": "_decode_car_status", "snapshot_key": "raw.ers_deploy_mode"},
            "tyres_wear_pct": {"packet": "CarDamage", "decoder_method": "_decode_car_damage", "snapshot_key": "raw.tyres_wear_pct"},
            "tyres_damage_pct": {"packet": "CarDamage", "decoder_method": "_decode_car_damage", "snapshot_key": "raw.tyres_damage_pct"},
            "tyre_blisters_pct": {"packet": "CarDamage", "decoder_method": "_decode_car_damage", "snapshot_key": "raw.tyre_blisters_pct"},
            "brakes_damage_pct": {"packet": "CarDamage", "decoder_method": "_decode_car_damage", "snapshot_key": "raw.brakes_damage_pct"},
            "world_forward_dir": {"packet": "Motion", "decoder_method": "_decode_motion", "snapshot_key": "raw.world_forward_dir"},
            "world_right_dir": {"packet": "Motion", "decoder_method": "_decode_motion", "snapshot_key": "raw.world_right_dir"},
            "wheel_slip_ratio": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.wheel_slip_ratio"},
            "wheel_slip_angle": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.wheel_slip_angle"},
            "wheel_lat_force": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.wheel_lat_force"},
            "wheel_long_force": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.wheel_long_force"},
            "local_velocity": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.local_velocity"},
            "angular_velocity": {"packet": "MotionEx", "decoder_method": "_decode_motion_ex", "snapshot_key": "raw.angular_velocity"},
            "track_temperature_c": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.track_temperature_c"},
            "air_temperature_c": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.air_temperature_c"},
            "weather": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "weather"},
            "weather_forecast_samples_head": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.weather_forecast_samples"},
            "forecast_accuracy": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.forecast_accuracy"},
            "ai_difficulty": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.ai_difficulty"},
            "season_link_identifier": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.season_link_identifier"},
            "weekend_link_identifier": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.weekend_link_identifier"},
            "session_link_identifier": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.session_link_identifier"},
            "pit_stop_window_ideal_lap": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.pit_stop_window_ideal_lap"},
            "pit_stop_window_latest_lap": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.pit_stop_window_latest_lap"},
            "pit_stop_rejoin_position": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.pit_stop_rejoin_position"},
            "game_mode": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.game_mode"},
            "rule_set": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.rule_set"},
            "time_of_day_minutes": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.time_of_day_minutes"},
            "session_length": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.session_length"},
            "weekend_structure": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.weekend_structure"},
            "sector2_lap_distance_start_m": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.sector2_lap_distance_start_m"},
            "sector3_lap_distance_start_m": {"packet": "Session", "decoder_method": "_decode_session", "snapshot_key": "raw.session_packet.sector3_lap_distance_start_m"},
            "lap_positions_num_laps": {"packet": "LapPositions", "decoder_method": "_decode_lap_positions", "snapshot_key": "raw.lap_positions.num_laps"},
            "lap_positions_lap_start": {"packet": "LapPositions", "decoder_method": "_decode_lap_positions", "snapshot_key": "raw.lap_positions.lap_start"},
            "player_lap_positions_head": {"packet": "LapPositions", "decoder_method": "_decode_lap_positions", "snapshot_key": "raw.lap_positions.player_lap_positions"},
            "lobby_num_players": {"packet": "LobbyInfo", "decoder_method": "_decode_lobby_info", "snapshot_key": "raw.lobby_info.num_players"},
            "lobby_player_name": {"packet": "LobbyInfo", "decoder_method": "_decode_lobby_info", "snapshot_key": "raw.lobby_info.player.name"},
            "lobby_player_ready_status": {"packet": "LobbyInfo", "decoder_method": "_decode_lobby_info", "snapshot_key": "raw.lobby_info.player.ready_status"},
            "event_code": {"packet": "Event", "decoder_method": "_decode_event", "snapshot_key": "raw.event_code"},
            "event_detail": {"packet": "Event", "decoder_method": "_decode_event_detail", "snapshot_key": "raw.event_detail"},
        }

    def _extract_trigger_highlights(self, row: dict) -> dict:
        player = row.get("player", {})
        debug = row.get("debug", {})
        assessment = debug.get("assessment", {})
        context = debug.get("context", {})
        risk_profile = debug.get("risk_profile", {})
        messages = row.get("messages", [])
        semantic = []
        strategy = []

        if assessment.get("fuel_state") == "critical":
            semantic.append({"field": "fuel_laps_remaining", "value": player.get("fuel_laps_remaining"), "reason": "fuel_state -> critical"})
            strategy.append({"field": "fuel_risk", "value": risk_profile.get("fuel_risk"), "reason": "LOW_FUEL candidate/message"})
        if assessment.get("tyre_state") in {"manage", "box_now"}:
            semantic.append({"field": "tyre.wear_pct", "value": player.get("tyre", {}).get("wear_pct"), "reason": f"tyre_state -> {assessment.get('tyre_state')}"})
            strategy.append({"field": "tyre_risk", "value": risk_profile.get("tyre_risk"), "reason": "TYRE_MANAGE or BOX_WINDOW"})
        if assessment.get("ers_state") == "low":
            semantic.append({"field": "ers_pct", "value": player.get("ers_pct"), "reason": "ers_state -> low"})
            strategy.append({"field": "ers_risk", "value": risk_profile.get("ers_risk"), "reason": "ERS_LOW"})
        if assessment.get("attack_state") == "available":
            semantic.append({"field": "official_gap_ahead_s", "value": player.get("gap_ahead_s"), "reason": "attack_state -> available"})
            semantic.append({"field": "drs_available", "value": player.get("drs_available"), "reason": "DRS open"})
            strategy.append({"field": "attack_opportunity", "value": risk_profile.get("attack_opportunity"), "reason": "ATTACK_WINDOW"})
        if assessment.get("defend_state") == "urgent":
            semantic.append({"field": "official_gap_behind_s", "value": player.get("gap_behind_s"), "reason": "defend_state -> urgent"})
            strategy.append({"field": "defend_risk", "value": risk_profile.get("defend_risk"), "reason": "DEFEND_WINDOW"})
        if assessment.get("dynamics_state") != "stable":
            semantic.append({"field": "status_tags", "value": player.get("status_tags"), "reason": f"dynamics_state -> {assessment.get('dynamics_state')}"})
            semantic.append({"field": "track_usage", "value": context.get("track_usage"), "reason": "dynamic context weighting"})
            strategy.append({"field": "dynamics_risk", "value": risk_profile.get("dynamics_risk"), "reason": "DYNAMICS_UNSTABLE or FRONT_LOAD"})
        if context.get("track_usage"):
            strategy.append({"field": "usage_bias", "value": debug.get("usage_bias", {}), "reason": f"track_usage -> {context.get('track_usage')}"})
        if messages:
            strategy.append({"field": "messages", "value": [item.get("code") for item in messages], "reason": "final arbitrated output"})
        return {"semantic_triggers": semantic, "strategy_triggers": strategy}

    def _extract_frame_diff(self, row: dict, previous_row: dict) -> dict:
        if not previous_row:
            return {"parsed_packet_fields": {}, "semantic_layer": {}, "strategy_output": {}}
        current_parsed = self._extract_parsed_packet_fields(row)
        previous_parsed = self._extract_parsed_packet_fields(previous_row)
        current_semantic = self._extract_semantic_layer(row)
        previous_semantic = self._extract_semantic_layer(previous_row)
        current_strategy = self._extract_strategy_output(row)
        previous_strategy = self._extract_strategy_output(previous_row)
        return {
            "parsed_packet_fields": self._diff_dict(current_parsed, previous_parsed),
            "semantic_layer": self._diff_dict(current_semantic, previous_semantic),
            "strategy_output": self._diff_dict(current_strategy, previous_strategy),
        }

    def _diff_dict(self, current: dict, previous: dict) -> dict:
        diff = {}
        for key in sorted(set(current) | set(previous)):
            if current.get(key) != previous.get(key):
                diff[key] = {"previous": previous.get(key), "current": current.get(key)}
        return diff

    def _extract_semantic_layer(self, row: dict) -> dict:
        debug = row.get("debug", {})
        context = debug.get("context", {})
        assessment = debug.get("assessment", {})
        player = row.get("player", {})
        rivals = row.get("rivals", [])
        return {
            "track": row.get("track"),
            "track_zone": context.get("track_zone"),
            "track_segment": context.get("track_segment"),
            "track_usage": context.get("track_usage"),
            "driving_mode": context.get("driving_mode"),
            "recent_unstable_ratio": context.get("recent_unstable_ratio"),
            "recent_front_overload_ratio": context.get("recent_front_overload_ratio"),
            "tyre_age_factor": context.get("tyre_age_factor"),
            "brake_phase_factor": context.get("brake_phase_factor"),
            "throttle_phase_factor": context.get("throttle_phase_factor"),
            "steering_phase_factor": context.get("steering_phase_factor"),
            "status_tags": player.get("status_tags", []),
            "player_position": player.get("position"),
            "gap_ahead_s": player.get("gap_ahead_s"),
            "gap_behind_s": player.get("gap_behind_s"),
            "rival_names": [item.get("name") for item in rivals[:4]],
            "assessment": assessment,
        }

    def _extract_strategy_output(self, row: dict) -> dict:
        debug = row.get("debug", {})
        return {
            "risk_profile": debug.get("risk_profile", {}),
            "risk_explain": debug.get("risk_explain", {}),
            "usage_bias": debug.get("usage_bias", {}),
            "candidates": debug.get("candidates", []),
            "messages": row.get("messages", []),
        }

    def _extract_stage_two_model_debug(self, row: dict) -> dict:
        debug = row.get("debug", {})
        arbiter = debug.get("arbiter_v2", {}) or {}
        arbiter_input = arbiter.get("input", {}) or {}
        arbiter_output = arbiter.get("output", {}) or {}
        model_candidates = arbiter_input.get("model_candidates", []) or []
        return {
            "strategy_action_model": {
                "model_candidates": [
                    item for item in model_candidates if (item.get("source") or "").startswith("strategy_action_model")
                ],
            },
            "resource_models": arbiter_input.get("resource_models", {}) or {},
            "rival_pressure_models": arbiter_input.get("rival_pressure_models", {}) or {},
            "driving_quality_models": arbiter_input.get("driving_quality_models", {}) or {},
            "defence_cost_model": arbiter_input.get("defence_cost_model", {}) or {},
            "arbiter_input": {
                "rule_candidates": arbiter_input.get("rule_candidates", []),
                "model_candidates": model_candidates,
                "tactical_context": arbiter_input.get("tactical_context", {}),
                "confidence_context": arbiter_input.get("confidence_context", {}),
                "fallback_context": arbiter_input.get("fallback_context", {}),
                "output_control": arbiter_input.get("output_control", {}),
            },
            "arbiter_output": {
                "final_hud_action": arbiter_output.get("final_hud_action", {}),
                "final_voice_action": arbiter_output.get("final_voice_action", {}),
                "final_strategy_stack": arbiter_output.get("final_strategy_stack", []),
                "ordered_actions": arbiter_output.get("ordered_actions", []),
                "suppressed_actions": arbiter_output.get("suppressed_actions", []),
            },
        }

    def _segment_order(self, track_profile, segment_name: str) -> int | None:
        if track_profile is None:
            return None
        return track_profile.segment_order(segment_name)

    def _render_html(self, payload: dict) -> str:
        embedded = json.dumps(payload, ensure_ascii=False)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Asurada Debug Dashboard</title>
  <style>
    :root {{
      --bg: #f7f7f5;
      --card: #ffffff;
      --text: #141414;
      --muted: #60646c;
      --line: #d9dde3;
      --accent: #005bbb;
      --warn: #d9480f;
      --good: #2b8a3e;
      --heat: #c92a2a;
      --heat-soft: #ffe3e3;
    }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 18px 20px 24px; }}
    h1 {{ margin: 0 0 4px; font-size: 26px; }}
    .sub {{ color: var(--muted); margin-bottom: 12px; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }}
    .grid2 {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; margin-bottom: 16px; }}
    .dashboard-grid {{ position: relative; min-height: 980px; margin-bottom: 16px; }}
    .panel {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 20px rgba(0,0,0,0.04); }}
    .dashboard-card {{ position: absolute; min-height: 0; overflow: hidden; box-sizing: border-box; }}
    .dashboard-card.dragging {{ opacity: 0.78; }}
    .card-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: move; user-select: none; }}
    .card-handle {{ color: var(--muted); font-size: 12px; }}
    .resize-handle {{ position: absolute; right: 10px; bottom: 10px; width: 16px; height: 16px; border-right: 2px solid var(--line); border-bottom: 2px solid var(--line); cursor: nwse-resize; opacity: 0.9; }}
    .metric-panel {{ height: 150px; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; }}
    .primary-panel {{ height: 260px; display: flex; flex-direction: column; overflow: hidden; }}
    .rival-panel {{ height: 170px; overflow: hidden; }}
    .trajectory-panel {{ height: 442px; overflow: hidden; }}
    .trajectory-canvas {{ width: 100%; height: 350px; display: block; border: 1px solid var(--line); border-radius: 12px; background: linear-gradient(180deg, #fcfdff, #f6f8fb); }}
    .scores-panel {{ overflow: hidden; }}
    .trajectory-legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }}
    .legend-dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .metric {{ font-size: 30px; font-weight: 700; margin-top: 6px; }}
    .metric.compact {{ font-size: 24px; line-height: 1.2; }}
    .label {{ color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .label-note {{ color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 6px; }}
    .two {{ display: grid; grid-template-columns: 2fr 1.2fr; gap: 16px; margin-bottom: 16px; }}
    .rival-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }}
    .rival-box {{ border: 1px solid var(--line); border-radius: 12px; padding: 12px; background: #fbfcfe; min-height: 0; overflow: hidden; }}
    .resource-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }}
    .resource-box {{ border: 1px solid var(--line); border-radius: 10px; padding: 6px 8px; background: #fbfcfe; min-height: 0; overflow: hidden; }}
    .resource-value {{ font-size: 15px; font-weight: 700; margin-top: 3px; }}
    .rival-name {{ font-size: 18px; font-weight: 700; line-height: 1.2; }}
    .rival-stats {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; margin-top: 10px; }}
    .rival-stat {{ min-width: 0; }}
    .rival-stat .helper {{ margin-bottom: 2px; }}
    .chart {{ height: 180px; width: 100%; background: linear-gradient(180deg, #fff, #fafbfc); border-radius: 12px; }}
    .list {{ display: grid; gap: 10px; min-height: 0; }}
    .item {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .item:first-child {{ border-top: 0; padding-top: 0; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #eef4ff; color: var(--accent); font-size: 12px; margin-right: 8px; }}
    .prio-high {{ color: var(--warn); }}
    .prio-mid {{ color: #9c6b00; }}
    .ellipsis-2 {{
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
    }}
    .ellipsis-3 {{
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      overflow: hidden;
    }}
    .controls {{ display: grid; grid-template-columns: 140px 1fr 96px; gap: 10px; align-items: end; margin-top: 8px; }}
    .controls4 {{ display: grid; grid-template-columns: 96px 1fr 132px; gap: 10px; align-items: end; margin-top: 8px; }}
    .mono {{ font-variant-numeric: tabular-nums; }}
    input[type=range] {{ width: 100%; }}
    select {{ width: 100%; padding: 8px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
    button {{ width: 100%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fff; cursor: pointer; }}
    button:hover {{ background: #f6f8fb; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 0; border-top: 1px solid var(--line); font-size: 14px; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; border-top: 0; }}
    .heat-row {{ display: grid; grid-template-columns: 210px 1fr 56px; gap: 12px; align-items: center; margin: 8px 0; }}
    .heat-bar {{ position: relative; height: 10px; border-radius: 999px; background: #f1f3f5; overflow: hidden; }}
    .heat-bar > span {{ position: absolute; inset: 0 auto 0 0; display: block; background: linear-gradient(90deg, var(--heat-soft), var(--heat)); }}
    .helper {{ color: var(--muted); font-size: 12px; }}
    .chain-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }}
    .chain-intro {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 14px; }}
    .chain-note {{ padding: 10px 12px; border: 1px dashed var(--line); border-radius: 12px; background: #fcfdff; font-size: 13px; line-height: 1.5; color: var(--muted); }}
    .chain-actions {{ display: grid; grid-template-columns: 220px 1fr; gap: 16px; align-items: end; margin-top: 14px; }}
    .jsonbox {{ margin: 10px 0 0; padding: 12px; border-radius: 12px; background: #fbfcfe; border: 1px solid var(--line); min-height: 280px; max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-word; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .browser-panel {{ min-height: 0; padding: 14px 16px; }}
    @media (max-width: 980px) {{
      .grid, .grid2, .grid3, .two, .controls, .chain-grid, .chain-intro {{ grid-template-columns: 1fr; grid-template-rows: none; }}
      .dashboard-grid {{ min-height: 0; }}
      .dashboard-card {{ position: relative; left: auto !important; top: auto !important; width: auto !important; height: auto !important; margin-bottom: 16px; }}
      .trajectory-panel, .primary-panel, .rival-panel {{ height: auto; }}
      .resize-handle, .card-handle {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Asurada Debug Dashboard</h1>
    <div class="sub">回放观察页。默认桌面视口下一屏查看轨迹、策略、前后车摘要和回放控制。</div>
    <div class="dashboard-grid" id="dashboard-grid">
      <div class="panel dashboard-card trajectory-panel" data-card-id="trajectory">
        <div class="card-head">
          <div class="label">World Trajectory</div>
          <div class="card-handle">拖动</div>
        </div>
        <div class="label-note">按当前播放进度，绘制玩家、前车、后车三辆车在世界坐标下的线路。</div>
        <canvas id="trajectory-canvas" class="trajectory-canvas" width="960" height="270"></canvas>
        <div class="trajectory-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#005bbb;"></span><span id="legend-player">玩家</span></span>
          <span class="legend-item"><span class="legend-dot" style="background:#d9480f;"></span><span id="legend-front">前车</span></span>
          <span class="legend-item"><span class="legend-dot" style="background:#2b8a3e;"></span><span id="legend-rear">后车</span></span>
        </div>
        <div class="resize-handle" title="调整大小"></div>
      </div>
      <div class="panel dashboard-card primary-panel" data-card-id="strategy">
        <div class="card-head">
          <div class="label">Current Strategy Output</div>
          <div class="card-handle">拖动</div>
        </div>
        <div class="label-note">当前时间点排在最前面的策略输出，以及其后的候选消息栈。</div>
        <div class="metric compact ellipsis-2" id="primary-call" style="margin-top:10px;"></div>
        <div id="primary-time" class="helper ellipsis-2" style="margin-top:6px;"></div>
        <div id="primary-detail" class="sub ellipsis-3" style="margin:8px 0 0"></div>
        <div id="strategy-stack" class="list" style="margin-top:12px; overflow:auto; flex:1; min-height:0;"></div>
        <div class="resize-handle" title="调整大小"></div>
      </div>
      <div class="panel dashboard-card rival-panel" data-card-id="rivals">
        <div class="card-head">
          <div class="label">Front / Rear Rival</div>
          <div class="card-handle">拖动</div>
        </div>
        <div class="label-note">当前前车与后车各自的状态摘要。差距字段按该车自身视角展示，不与玩家做换算。</div>
        <div class="rival-grid">
          <div class="rival-box">
            <div class="helper">前车</div>
            <div id="front-rival-name" class="rival-name ellipsis-2">-</div>
            <div id="front-rival-stats" class="rival-stats"></div>
          </div>
          <div class="rival-box">
            <div class="helper">后车</div>
            <div id="rear-rival-name" class="rival-name ellipsis-2">-</div>
            <div id="rear-rival-stats" class="rival-stats"></div>
          </div>
        </div>
        <div class="resize-handle" title="调整大小"></div>
      </div>
      <div class="panel dashboard-card scores-panel" data-card-id="scores">
        <div class="card-head">
          <div class="label">Model Scores</div>
          <div class="card-handle">拖动</div>
        </div>
        <div class="label-note">阶段二旁路模型分数。仅用于调试观察，不直接代表最终动作。</div>
        <div id="resource-model-grid" class="resource-grid"></div>
        <div class="resize-handle" title="调整大小"></div>
      </div>
      <div class="panel dashboard-card browser-panel" data-card-id="browser">
        <div class="card-head">
          <div class="label">Frame Browser</div>
          <div class="card-handle">拖动</div>
        </div>
        <div class="label-note">全量 session 时间轴。支持播放、暂停和拖动。</div>
        <div class="controls">
          <div>
            <div class="helper">浏览范围</div>
            <select id="lap-filter"><option value="all">全量 session</option></select>
          </div>
          <div>
            <div class="helper">回放进度</div>
            <input id="frame-slider" type="range" min="0" max="0" value="0">
          </div>
            <div>
              <div class="helper">选中帧</div>
            <div id="frame-label" class="metric mono" style="font-size:16px; margin-top:4px;"></div>
          </div>
        </div>
        <div class="controls4">
          <div>
            <div class="helper">播放控制</div>
            <button id="play-toggle" type="button">播放</button>
          </div>
          <div>
            <div class="helper">选中时间</div>
            <div id="frame-time-label" class="metric mono" style="font-size:16px; margin-top:4px;"></div>
          </div>
          <div>
            <div class="helper">当前圈段</div>
            <div id="frame-lap-label" class="metric mono" style="font-size:16px; margin-top:4px;"></div>
          </div>
        </div>
        <div class="list" id="frame-detail" style="margin-top:10px; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px 10px;"></div>
        <div class="resize-handle" title="调整大小"></div>
      </div>
    </div>
  </div>
  <script>
    const payload = {embedded};
    const frames = payload.frames || [];
    const board = document.getElementById('dashboard-grid');
    const lapFilter = document.getElementById('lap-filter');
    const slider = document.getElementById('frame-slider');
    const frameLabel = document.getElementById('frame-label');
    const frameDetail = document.getElementById('frame-detail');
    const playToggle = document.getElementById('play-toggle');
    const frameTimeLabel = document.getElementById('frame-time-label');
    const frameLapLabel = document.getElementById('frame-lap-label');
    const frontRivalName = document.getElementById('front-rival-name');
    const rearRivalName = document.getElementById('rear-rival-name');
    const frontRivalStats = document.getElementById('front-rival-stats');
    const rearRivalStats = document.getElementById('rear-rival-stats');
    const resourceModelGrid = document.getElementById('resource-model-grid');
    let filteredFrames = frames.slice();
    let playbackTimer = null;
    let isPlaying = false;
    let playbackIndex = 0;
    let draggingCard = null;
    let draggedCardId = null;
    let resizingCard = null;
    let dragOffsetX = 0;
    let dragOffsetY = 0;
    let resizeStartX = 0;
    let resizeStartY = 0;
    let resizeStartW = 0;
    let resizeStartH = 0;

    const defaultCardLayout = {{
      trajectory: {{ x: 0, y: 0, w: 760, h: 442 }},
      strategy: {{ x: 776, y: 0, w: 548, h: 260 }},
      rivals: {{ x: 776, y: 276, w: 548, h: 170 }},
      scores: {{ x: 0, y: 458, w: 1324, h: 170 }},
      browser: {{ x: 0, y: 644, w: 1324, h: 240 }},
    }};
    const layoutStorageKey = 'asurada:debug-dashboard-layout:absolute:v1';

    function formatSessionTime(seconds) {{
      const total = Number(seconds || 0);
      const minutes = Math.floor(total / 60);
      const remain = total - minutes * 60;
      const whole = Math.floor(remain);
      const tenths = Math.floor((remain - whole) * 10);
      return `${{minutes}}:${{String(whole).padStart(2, '0')}}.${{tenths}}`;
    }}

    function formatMetric(value, formatter) {{
      if (value === null || value === undefined || value === '') return '-';
      return formatter ? formatter(value) : String(value);
    }}

    function renderRivalStats(target, rival) {{
      const stats = [
        ['名次', formatMetric(rival.position)],
        ['前车差距', formatMetric(rival.display_gap_ahead_s, (value) => `${{Number(value).toFixed(1)}} s`)],
        ['后车差距', formatMetric(rival.display_gap_behind_s, (value) => `${{Number(value).toFixed(1)}} s`)],
        ['时速', formatMetric(rival.speed_kph, (value) => `${{Number(value).toFixed(0)}} km/h`)],
        ['ERS', formatMetric(rival.ers_pct, (value) => `${{Number(value).toFixed(0)}}%`)],
        ['DRS', rival.drs_available === null || rival.drs_available === undefined ? '-' : (rival.drs_available ? '可用' : '不可用')],
      ];
      target.innerHTML = stats
        .map(([label, value]) => `<div class="rival-stat"><div class="helper">${{label}}</div><div class="ellipsis-2">${{value}}</div></div>`)
        .join('');
    }}

    function renderResourceModels(resourceModels, defenceCostModel, rivalPressureModels, drivingQualityModels) {{
      const modelOrder = [
        ['fuel_risk', 'Fuel'],
        ['ers_risk', 'ERS'],
        ['tyre_risk', 'Tyre'],
        ['dynamics_risk', 'Dynamics'],
      ];
      const resourceCards = modelOrder
        .map(([key, label]) => {{
          const item = resourceModels?.[key] || {{}};
          const enabled = item.enabled === true;
          const score = enabled && item.score !== undefined && item.score !== null
            ? Number(item.score).toFixed(1)
            : '-';
          const note = enabled ? 'runtime' : (item.disabled_reason || 'disabled');
          return `
            <div class="resource-box">
              <div class="helper">${{label}}</div>
              <div class="resource-value">${{score}}</div>
              <div class="helper ellipsis-2">${{note}}</div>
            </div>
          `;
        }});
      const defenceEnabled = defenceCostModel?.enabled === true;
      const defenceScore = defenceEnabled && defenceCostModel.score !== undefined && defenceCostModel.score !== null
        ? Number(defenceCostModel.score).toFixed(1)
        : '-';
      const defenceNote = defenceEnabled ? 'runtime' : (defenceCostModel?.disabled_reason || 'disabled');
      const rivalPressure = rivalPressureModels || {{}};
      const rivalModel = rivalPressure?.rival_pressure || {{}};
      const rivalEnabled = rivalModel.enabled === true;
      const rivalScore = rivalEnabled && rivalModel.score !== undefined && rivalModel.score !== null
        ? Number(rivalModel.score).toFixed(1)
        : '-';
      const rivalNote = rivalEnabled ? 'runtime' : (rivalModel?.disabled_reason || 'disabled');
      const drivingOrder = [
        ['entry_quality', 'Entry'],
        ['apex_quality', 'Apex'],
        ['exit_traction', 'Exit'],
      ];
      const drivingCards = drivingOrder
        .map(([key, label]) => {{
          const item = drivingQualityModels?.[key] || {{}};
          const enabled = item.enabled === true;
          const score = enabled && item.score !== undefined && item.score !== null
            ? Number(item.score).toFixed(1)
            : '-';
          const note = enabled ? 'runtime' : (item.disabled_reason || 'disabled');
          return `
            <div class="resource-box">
              <div class="helper">${{label}}</div>
              <div class="resource-value">${{score}}</div>
              <div class="helper ellipsis-2">${{note}}</div>
            </div>
          `;
        }});
      resourceModelGrid.innerHTML = resourceCards
        .concat([`
          <div class="resource-box">
            <div class="helper">Defence</div>
            <div class="resource-value">${{defenceScore}}</div>
            <div class="helper ellipsis-2">${{defenceNote}}</div>
          </div>
        `, `
          <div class="resource-box">
            <div class="helper">Pressure</div>
            <div class="resource-value">${{rivalScore}}</div>
            <div class="helper ellipsis-2">${{rivalNote}}</div>
          </div>
        `])
        .concat(drivingCards)
        .join('');
    }}

    function drawTrajectory(index) {{
      const canvas = document.getElementById('trajectory-canvas');
      const ctx = canvas.getContext('2d');
      const subset = filteredFrames.slice(0, index + 1);
      const series = [
        {{
          keyX: 'player_world_x',
          keyZ: 'player_world_z',
          color: '#005bbb',
          labelTarget: document.getElementById('legend-player'),
          label: '玩家',
        }},
        {{
          keyX: 'front_world_x',
          keyZ: 'front_world_z',
          color: '#d9480f',
          labelTarget: document.getElementById('legend-front'),
          label: subset[index]?.front_world_name ? `前车：${{subset[index].front_world_name}}` : '前车',
        }},
        {{
          keyX: 'rear_world_x',
          keyZ: 'rear_world_z',
          color: '#2b8a3e',
          labelTarget: document.getElementById('legend-rear'),
          label: subset[index]?.rear_world_name ? `后车：${{subset[index].rear_world_name}}` : '后车',
        }},
      ];

      for (const item of series) {{
        item.labelTarget.textContent = item.label;
      }}

      const points = [];
      for (const frame of subset) {{
        for (const item of series) {{
          const x = frame[item.keyX];
          const z = frame[item.keyZ];
          if (x !== null && x !== undefined && z !== null && z !== undefined) {{
            points.push([Number(x), Number(z)]);
          }}
        }}
      }}

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!points.length) {{
        ctx.fillStyle = '#60646c';
        ctx.font = '14px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
        ctx.fillText('当前回放没有可用的三车世界坐标。', 24, 36);
        return;
      }}

      const xs = points.map((item) => item[0]);
      const zs = points.map((item) => item[1]);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minZ = Math.min(...zs);
      const maxZ = Math.max(...zs);
      const padding = 18;
      const usableWidth = canvas.width - padding * 2;
      const usableHeight = canvas.height - padding * 2;
      const spanX = Math.max(maxX - minX, 1);
      const spanZ = Math.max(maxZ - minZ, 1);
      const scale = Math.min(usableWidth / spanX, usableHeight / spanZ);

      function mapPoint(x, z) {{
        return [
          padding + (x - minX) * scale,
          canvas.height - padding - (z - minZ) * scale,
        ];
      }}

      ctx.strokeStyle = '#d9dde3';
      ctx.lineWidth = 1;
      ctx.strokeRect(0.5, 0.5, canvas.width - 1, canvas.height - 1);

      for (const item of series) {{
        const line = subset
          .map((frame) => {{
            const x = frame[item.keyX];
            const z = frame[item.keyZ];
            return x !== null && x !== undefined && z !== null && z !== undefined ? mapPoint(Number(x), Number(z)) : null;
          }})
          .filter(Boolean);
        if (line.length < 2) continue;
        ctx.beginPath();
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 2.5;
        ctx.moveTo(line[0][0], line[0][1]);
        for (const point of line.slice(1)) {{
          ctx.lineTo(point[0], point[1]);
        }}
        ctx.stroke();

        const last = line[line.length - 1];
        ctx.fillStyle = item.color;
        ctx.beginPath();
        ctx.arc(last[0], last[1], 4, 0, Math.PI * 2);
        ctx.fill();
      }}
    }}

    function renderFrame(index) {{
      if (!filteredFrames.length) {{
        document.getElementById('primary-call').textContent = 'No active call';
        document.getElementById('primary-time').textContent = '-';
        document.getElementById('primary-detail').textContent = 'No high-priority strategy output in the current frame.';
        resourceModelGrid.innerHTML = '';
        document.getElementById('strategy-stack').innerHTML = '';
        frontRivalName.textContent = '-';
        rearRivalName.textContent = '-';
        frontRivalStats.innerHTML = '';
        rearRivalStats.innerHTML = '';
        frameLabel.textContent = '-';
        frameTimeLabel.textContent = '-';
        frameLapLabel.textContent = '-';
        frameDetail.innerHTML = '<div class="item">没有可显示的帧数据</div>';
        return;
      }}
      const frame = filteredFrames[index];
      const previousFrame = index >= 1 ? filteredFrames[index - 1] : frame;
      const speedDelta = Number(frame.speed || 0) - Number(previousFrame.speed || 0);
      const frameMessages = Array.isArray(frame.messages) ? frame.messages : [];
      document.getElementById('primary-call').textContent = frame.top_message || 'No active call';
      document.getElementById('primary-time').textContent = `session_time=${{formatSessionTime(frame.session_time_s)}} | lap=${{
        frame.total_laps > 0 ? `${{frame.lap}} / ${{frame.total_laps}}` : frame.lap
      }} | pos=${{frame.position ?? '-'}}`;
      document.getElementById('primary-detail').textContent = frame.top_detail || 'No high-priority strategy output in the current frame.';
      renderResourceModels(
        frame.stage_two_model_debug?.resource_models || {{}},
        frame.stage_two_model_debug?.defence_cost_model || {{}},
        frame.stage_two_model_debug?.rival_pressure_models || {{}},
        frame.stage_two_model_debug?.driving_quality_models || {{}},
      );
      document.getElementById('strategy-stack').innerHTML = frameMessages
        .slice(0, 5)
        .map((item) => `<div class="item"><span class="pill">P${{item.priority}}</span><strong>${{item.title}}</strong><div>${{item.detail}}</div></div>`)
        .join('');
      frontRivalName.textContent = frame.front_rival?.name || '-';
      rearRivalName.textContent = frame.rear_rival?.name || '-';
      renderRivalStats(frontRivalStats, frame.front_rival || {{}});
      renderRivalStats(rearRivalStats, frame.rear_rival || {{}});
      drawTrajectory(index);
      frameLabel.textContent = `F${{frame.frame}}`;
      frameTimeLabel.textContent = formatSessionTime(frame.session_time_s);
      frameLapLabel.textContent = frame.total_laps > 0 ? `${{frame.lap}} / ${{frame.total_laps}}` : String(frame.lap);
      const detail = [
        ['Session Time', `${{formatSessionTime(frame.session_time_s)}} (${{Number(frame.session_time_s || 0).toFixed(1)}} s)`],
        ['Track', payload.latest?.track || '-'],
        ['Lap', frame.total_laps > 0 ? `${{frame.lap}} / ${{frame.total_laps}}` : String(frame.lap)],
        ['Position', frame.position ?? '-'],
        ['Speed', `${{Number(frame.speed || 0).toFixed(0)}} km/h`],
      ];
      frameDetail.innerHTML = detail.map(([k, v]) => `<div class="item"><span class="pill">${{k}}</span>${{v}}</div>`).join('');
    }}

    function loadCardLayout() {{
      try {{
        return JSON.parse(localStorage.getItem(layoutStorageKey) || '{{}}');
      }} catch (_) {{
        return {{}};
      }}
    }}

    function saveCardLayout(layout) {{
      localStorage.setItem(layoutStorageKey, JSON.stringify(layout));
    }}

    function updateBoardHeight() {{
      const cards = Array.from(board.querySelectorAll('.dashboard-card'));
      const bottoms = cards.map((card) => {{
        const top = Number(card.style.top.replace('px', '') || 0);
        const height = Number(card.style.height.replace('px', '') || card.offsetHeight || 0);
        return top + height;
      }});
      const maxBottom = bottoms.length ? Math.max(...bottoms) : 0;
      board.style.height = `${{maxBottom + 24}}px`;
    }}

    function applyCardLayout() {{
      const stored = loadCardLayout();
      Array.from(board.querySelectorAll('.dashboard-card')).forEach((card) => {{
        const cardId = card.dataset.cardId;
        const cfg = stored[cardId] || defaultCardLayout[cardId] || {{ x: 0, y: 0, w: 400, h: 240 }};
        card.style.left = `${{cfg.x}}px`;
        card.style.top = `${{cfg.y}}px`;
        card.style.width = `${{cfg.w}}px`;
        card.style.height = `${{cfg.h}}px`;
      }});
      updateBoardHeight();
    }}

    function bindCardInteractions() {{
      Array.from(board.querySelectorAll('.dashboard-card')).forEach((card) => {{
        const head = card.querySelector('.card-head');
        if (head) {{
          head.addEventListener('mousedown', (event) => {{
            if (window.innerWidth <= 980) return;
            if (event.target && event.target.classList && event.target.classList.contains('resize-handle')) return;
            event.preventDefault();
            const rect = card.getBoundingClientRect();
            draggingCard = card;
            draggedCardId = card.dataset.cardId;
            dragOffsetX = event.clientX - rect.left;
            dragOffsetY = event.clientY - rect.top;
            card.classList.add('dragging');
            document.body.style.cursor = 'grabbing';
            document.body.style.userSelect = 'none';
          }});
        }}

        const handle = card.querySelector('.resize-handle');
        if (!handle) return;
        handle.addEventListener('mousedown', (event) => {{
          event.preventDefault();
          event.stopPropagation();
          const stored = loadCardLayout();
          const cardId = card.dataset.cardId;
          const current = stored[cardId] || defaultCardLayout[cardId] || {{ x: 0, y: 0, w: 400, h: 240 }};
          resizingCard = card;
          resizeStartX = event.clientX;
          resizeStartY = event.clientY;
          resizeStartW = current.w;
          resizeStartH = current.h;
          document.body.style.cursor = 'nwse-resize';
          document.body.style.userSelect = 'none';
        }});
      }});
    }}

    function onResizeMove(event) {{
      if (draggingCard) {{
        const card = draggingCard;
        const cardId = card.dataset.cardId;
        const layout = loadCardLayout();
        const width = Number(card.style.width.replace('px', '') || card.offsetWidth || 400);
        const height = Number(card.style.height.replace('px', '') || card.offsetHeight || 240);
        const boardRect = board.getBoundingClientRect();
        const maxX = Math.max(0, board.clientWidth - width);
        const nextX = Math.max(0, Math.min(maxX, event.clientX - boardRect.left - dragOffsetX));
        const nextY = Math.max(0, event.clientY - boardRect.top - dragOffsetY);
        card.style.left = `${{nextX}}px`;
        card.style.top = `${{nextY}}px`;
        layout[cardId] = {{
          ...(layout[cardId] || defaultCardLayout[cardId] || {{ w: width, h: height }}),
          x: nextX,
          y: nextY,
          w: width,
          h: height,
        }};
        saveCardLayout(layout);
        updateBoardHeight();
        return;
      }}
      if (!resizingCard) return;
      const dx = event.clientX - resizeStartX;
      const dy = event.clientY - resizeStartY;
      const cardId = resizingCard.dataset.cardId;
      const layout = loadCardLayout();
      const nextW = Math.max(260, resizeStartW + dx);
      const nextH = Math.max(160, resizeStartH + dy);
      resizingCard.style.width = `${{nextW}}px`;
      resizingCard.style.height = `${{nextH}}px`;
      layout[cardId] = {{
        ...(layout[cardId] || defaultCardLayout[cardId] || {{ x: 0, y: 0 }}),
        x: Number(resizingCard.style.left.replace('px', '') || 0),
        y: Number(resizingCard.style.top.replace('px', '') || 0),
        w: nextW,
        h: nextH,
      }};
      saveCardLayout(layout);
      updateBoardHeight();
    }}

    function onResizeEnd(event) {{
      if (draggingCard) {{
        draggingCard.classList.remove('dragging');
        draggingCard = null;
        draggedCardId = null;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        return;
      }}
      if (!resizingCard) return;
      resizingCard = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }}

    function clearPlaybackTimer() {{
      if (playbackTimer !== null) {{
        clearInterval(playbackTimer);
        playbackTimer = null;
      }}
    }}

    function updatePlayToggle() {{
      playToggle.textContent = isPlaying ? '暂停' : '播放';
    }}

    function schedulePlaybackStep() {{
      clearPlaybackTimer();
      if (!isPlaying || !filteredFrames.length) return;
      playbackTimer = setInterval(() => {{
        if (!isPlaying || !filteredFrames.length) {{
          clearPlaybackTimer();
          return;
        }}
        if (playbackIndex >= filteredFrames.length - 1) {{
          isPlaying = false;
          updatePlayToggle();
          clearPlaybackTimer();
          return;
        }}
        playbackIndex += 1;
        slider.value = String(playbackIndex);
        renderFrame(playbackIndex);
      }}, 120);
    }}

    function applyLapFilter() {{
      clearPlaybackTimer();
      isPlaying = false;
      updatePlayToggle();
      const selectedLap = lapFilter.value;
      filteredFrames = selectedLap === 'all' ? frames.slice() : frames.filter((item) => String(item.lap) === selectedLap);
      slider.min = 0;
      slider.max = Math.max(filteredFrames.length - 1, 0);
      playbackIndex = Math.max(filteredFrames.length - 1, 0);
      slider.value = playbackIndex;
      renderFrame(playbackIndex);
    }}

    lapFilter.addEventListener('change', applyLapFilter);
    slider.addEventListener('input', () => {{
      clearPlaybackTimer();
      isPlaying = false;
      updatePlayToggle();
      playbackIndex = Number(slider.value || 0);
      renderFrame(playbackIndex);
    }});
    playToggle.addEventListener('click', () => {{
      isPlaying = !isPlaying;
      updatePlayToggle();
      if (isPlaying) {{
        if (filteredFrames.length && playbackIndex >= filteredFrames.length - 1) {{
          playbackIndex = 0;
          slider.value = '0';
          renderFrame(playbackIndex);
        }}
        schedulePlaybackStep();
      }} else {{
        clearPlaybackTimer();
      }}
    }});
    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('mouseup', onResizeEnd);
    applyCardLayout();
    bindCardInteractions();
    updatePlayToggle();
    applyLapFilter();
  </script>
</body>
</html>
"""

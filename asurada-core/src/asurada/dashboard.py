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
        last_rows = rows[-360:]
        timing_summary = self._build_timing_summary(rows)
        track_name = latest.get("track") if latest else None
        track_profile = load_track_profile(str(track_name)) if track_name else None
        priorities: list[float] = []
        fuel_series: list[float] = []
        ers_series: list[float] = []
        tyre_series: list[float] = []
        speed_series: list[float] = []
        recent_messages = []
        code_counter: Counter[str] = Counter()
        track_segments: Counter[str] = Counter()
        rival_counter: Counter[str] = Counter()
        heatmap_rows: dict[str, dict] = defaultdict(
            lambda: {
                "segment": "",
                "zone": "",
                "frames": 0,
                "risk_score": 0,
                "max_priority": 0,
                "unstable": 0,
                "front_load": 0,
                "heavy_braking": 0,
            }
        )
        frames = []
        laps = []
        seen_laps = set()

        for row_index, row in enumerate(last_rows):
            player = row.get("player", {})
            raw = row.get("raw", {})
            debug = row.get("debug", {})
            context = debug.get("context", {})
            messages = row.get("messages", [])
            tags = set(player.get("status_tags", []))
            top_priority = messages[0]["priority"] if messages else 0
            segment = context.get("track_segment") or "Unknown"
            zone = context.get("track_zone") or "unknown"
            usage = context.get("track_usage") or ""
            lap_number = int(row.get("lap_number", 0))
            frame_identifier = int(raw.get("frame_identifier", 0))
            rival_names = [item.get("name", "Unknown") for item in row.get("rivals", [])[:4]]

            priorities.append(top_priority)
            fuel_series.append(float(player.get("fuel_laps_remaining", 0.0)))
            ers_series.append(float(player.get("ers_pct", 0.0)))
            tyre_series.append(float(player.get("tyre", {}).get("wear_pct", 0.0)))
            speed_series.append(float(player.get("speed_kph", 0.0)))
            track_segments[segment] += 1
            for rival_name in rival_names:
                rival_counter[rival_name] += 1

            if lap_number not in seen_laps:
                laps.append(lap_number)
                seen_laps.add(lap_number)

            heat = heatmap_rows[segment]
            heat["segment"] = segment
            heat["zone"] = zone
            heat["usage"] = usage
            heat["order"] = self._segment_order(track_profile, segment)
            heat["frames"] += 1
            heat["max_priority"] = max(heat["max_priority"], top_priority)
            heat["unstable"] += int("unstable" in tags)
            heat["front_load"] += int("front_tyre_overload" in tags)
            heat["heavy_braking"] += int("heavy_braking" in tags)
            heat["risk_score"] += top_priority + int("unstable" in tags) * 12 + int("front_tyre_overload" in tags) * 8

            for msg in messages[:1]:
                code_counter[msg["code"]] += 1
                recent_messages.append(
                    {
                        "title": msg["title"],
                        "priority": msg["priority"],
                        "detail": msg["detail"],
                        "lap": lap_number,
                        "frame": frame_identifier,
                    }
                )

            frames.append(
                {
                    "frame": frame_identifier,
                    "lap": lap_number,
                    "segment": segment,
                    "zone": zone,
                    "usage": usage,
                    "speed": float(player.get("speed_kph", 0.0)),
                    "fuel": float(player.get("fuel_laps_remaining", 0.0)),
                    "ers": float(player.get("ers_pct", 0.0)),
                    "tyre_wear": float(player.get("tyre", {}).get("wear_pct", 0.0)),
                    "tyre_compound": player.get("tyre", {}).get("compound", "-"),
                    "top_priority": top_priority,
                    "top_message": messages[0]["title"] if messages else "",
                    "top_detail": messages[0]["detail"] if messages else "",
                    "tags": list(player.get("status_tags", [])),
                    "position": int(player.get("position", 0)),
                    "rivals": len(row.get("rivals", [])),
                    "rival_names": rival_names,
                    "wing_front_left": int(raw.get("wing_damage_pct", {}).get("front_left", 0)),
                    "wing_front_right": int(raw.get("wing_damage_pct", {}).get("front_right", 0)),
                    "event_code": raw.get("event_code"),
                    "chain": {
                        "parsed_packet_fields": self._extract_parsed_packet_fields(row),
                        "field_sources": self._extract_field_sources(),
                        "field_trace": self._extract_field_trace(),
                        "semantic_layer": self._extract_semantic_layer(row),
                        "strategy_output": self._extract_strategy_output(row),
                    },
                }
            )
            if row_index >= 1:
                frames[-1]["chain"]["frame_diff"] = self._extract_frame_diff(row, last_rows[row_index - 1])
            else:
                frames[-1]["chain"]["frame_diff"] = {"parsed_packet_fields": {}, "semantic_layer": {}, "strategy_output": {}}
            frames[-1]["chain"]["trigger_highlights"] = self._extract_trigger_highlights(row)

        heatmap = sorted(
            heatmap_rows.values(),
            key=lambda item: (
                item.get("order") is None,
                item.get("order") if item.get("order") is not None else 999,
                -item["risk_score"],
                -item["frames"],
            ),
        )
        ordered_segments = sorted(
            track_segments.items(),
            key=lambda item: (
                self._segment_order(track_profile, item[0]) is None,
                self._segment_order(track_profile, item[0]) if self._segment_order(track_profile, item[0]) is not None else 999,
                -item[1],
            ),
        )[:12]

        payload = {
            "latest": latest,
            "latest_chain": {
                "parsed_packet_fields": self._extract_parsed_packet_fields(latest),
                "field_sources": self._extract_field_sources(),
                "field_trace": self._extract_field_trace(),
                "semantic_layer": self._extract_semantic_layer(latest),
                "strategy_output": self._extract_strategy_output(latest),
                "frame_diff": self._extract_frame_diff(latest, last_rows[-2] if len(last_rows) >= 2 else {}),
                "trigger_highlights": self._extract_trigger_highlights(latest),
            },
            "capture_summary": capture_summary,
            "timing_summary": timing_summary,
            "packet_filters": sorted(self._extract_field_sources().keys()),
            "totals": {
                "frames": len(rows),
                "recent_frames": len(last_rows),
                "message_counts": code_counter.most_common(8),
                "segments": ordered_segments,
                "rivals": rival_counter.most_common(8),
            },
            "series": {
                "priority": priorities,
                "fuel": fuel_series,
                "ers": ers_series,
                "tyre_wear": tyre_series,
                "speed": speed_series,
            },
            "recent_messages": recent_messages[-40:],
            "frames": frames,
            "laps": sorted(laps),
            "heatmap": heatmap,
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
            "delta_to_car_in_front_s": raw.get("delta_to_car_in_front_s"),
            "delta_to_race_leader_s": raw.get("delta_to_race_leader_s"),
            "gap_source_ahead": raw.get("gap_source_ahead"),
            "gap_source_behind": raw.get("gap_source_behind"),
            "gap_confidence_ahead": raw.get("gap_confidence_ahead"),
            "gap_confidence_behind": raw.get("gap_confidence_behind"),
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
                "delta_to_car_in_front_s",
                "delta_to_race_leader_s",
                "gap_source_ahead",
                "gap_source_behind",
                "gap_confidence_ahead",
                "gap_confidence_behind",
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
            "delta_to_car_in_front_s": {"packet": "LapData", "decoder_method": "_lap_delta_seconds", "snapshot_key": "raw.delta_to_car_in_front_s"},
            "delta_to_race_leader_s": {"packet": "LapData", "decoder_method": "_lap_delta_seconds", "snapshot_key": "raw.delta_to_race_leader_s"},
            "gap_source_ahead": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.gap_source_ahead"},
            "gap_source_behind": {"packet": "LapData", "decoder_method": "_build_rivals", "snapshot_key": "raw.gap_source_behind"},
            "gap_confidence_ahead": {"packet": "LapData", "decoder_method": "_gap_confidence_from_source", "snapshot_key": "raw.gap_confidence_ahead"},
            "gap_confidence_behind": {"packet": "LapData", "decoder_method": "_gap_confidence_from_source", "snapshot_key": "raw.gap_confidence_behind"},
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
            semantic.append({"field": "gap_ahead_s", "value": player.get("gap_ahead_s"), "reason": "attack_state -> available"})
            semantic.append({"field": "drs_available", "value": player.get("drs_available"), "reason": "DRS open"})
            strategy.append({"field": "attack_opportunity", "value": risk_profile.get("attack_opportunity"), "reason": "ATTACK_WINDOW"})
        if assessment.get("defend_state") == "urgent":
            semantic.append({"field": "gap_behind_s", "value": player.get("gap_behind_s"), "reason": "defend_state -> urgent"})
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
  <meta http-equiv="refresh" content="4">
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
    .wrap {{ max-width: 1360px; margin: 0 auto; padding: 28px 24px 48px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .sub {{ color: var(--muted); margin-bottom: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }}
    .grid2 {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; margin-bottom: 16px; }}
    .panel {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 20px rgba(0,0,0,0.04); }}
    .metric {{ font-size: 30px; font-weight: 700; margin-top: 6px; }}
    .label {{ color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .label-note {{ color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 6px; }}
    .two {{ display: grid; grid-template-columns: 2fr 1.2fr; gap: 16px; margin-bottom: 16px; }}
    .chart {{ height: 180px; width: 100%; background: linear-gradient(180deg, #fff, #fafbfc); border-radius: 12px; }}
    .list {{ display: grid; gap: 10px; }}
    .item {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .item:first-child {{ border-top: 0; padding-top: 0; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #eef4ff; color: var(--accent); font-size: 12px; margin-right: 8px; }}
    .prio-high {{ color: var(--warn); }}
    .prio-mid {{ color: #9c6b00; }}
    .controls {{ display: grid; grid-template-columns: 200px 1fr 120px; gap: 16px; align-items: center; margin-top: 12px; }}
    .mono {{ font-variant-numeric: tabular-nums; }}
    input[type=range] {{ width: 100%; }}
    select {{ width: 100%; padding: 8px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
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
    @media (max-width: 980px) {{
      .grid, .grid2, .grid3, .two, .controls, .chain-grid, .chain-intro {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Asurada Debug Dashboard</h1>
    <div class="sub">本地自动刷新调试面板。页面每 4 秒刷新一次，回放运行期间可持续观察变化。</div>
    <div class="grid">
      <div class="panel"><div class="label">Track</div><div class="label-note">当前会话识别到的赛道。</div><div class="metric" id="track"></div></div>
      <div class="panel"><div class="label">Latest Lap</div><div class="label-note">最新一帧所属圈数。</div><div class="metric" id="lap"></div></div>
      <div class="panel"><div class="label">Fuel Laps</div><div class="label-note">按当前口径估算的剩余燃油可支撑圈数。</div><div class="metric" id="fuel"></div></div>
      <div class="panel"><div class="label">ERS</div><div class="label-note">玩家当前 ERS 百分比。</div><div class="metric" id="ers"></div></div>
    </div>
    <div class="grid">
      <div class="panel"><div class="label">Capture Wall Time</div><div class="label-note">抓包文件从第一条到最后一条数据的真实录制时间跨度。</div><div class="metric" id="capture-wall-time" style="font-size:24px"></div></div>
      <div class="panel"><div class="label">Game Session Time</div><div class="label-note">游戏包头中的 session_time 实际推进跨度。</div><div class="metric" id="session-span-time" style="font-size:24px"></div></div>
      <div class="panel"><div class="label">Capture Wall Seconds</div><div class="label-note">抓包录制时间跨度，单位秒。</div><div class="metric" id="capture-wall-seconds" style="font-size:24px"></div></div>
      <div class="panel"><div class="label">Session Span Seconds</div><div class="label-note">游戏 session_time 跨度，单位秒。</div><div class="metric" id="session-span-seconds" style="font-size:24px"></div></div>
    </div>
    <div class="grid3">
      <div class="panel"><div class="label">Top Priority</div><div class="label-note">当前帧最高优先级策略消息的优先级数值。</div><div class="metric" id="top-priority"></div></div>
      <div class="panel"><div class="label">Track Usage</div><div class="label-note">当前赛道区段在策略模型里的用途标签。</div><div class="metric" id="top-usage" style="font-size:22px"></div></div>
      <div class="panel"><div class="label">Rival Count</div><div class="label-note">当前帧被追踪并进入模型的对手数量。</div><div class="metric" id="rival-count"></div></div>
    </div>
    <div class="grid2">
      <div class="panel">
        <div class="label">Primary Call</div>
        <div class="label-note">当前帧排在最前面的主要策略播报，以及其后的候选消息栈。</div>
        <div class="metric" id="primary-call" style="font-size:24px"></div>
        <div id="primary-detail" class="sub" style="margin:10px 0 0"></div>
        <div id="strategy-stack" class="list" style="margin-top:16px"></div>
      </div>
      <div class="panel">
        <div class="label">Protocol Coverage</div>
        <div class="label-note">当前抓包里出现了哪些 packet，以及解码覆盖到什么程度。</div>
        <div class="list" id="protocol-coverage"></div>
      </div>
    </div>
    <div class="two">
      <div class="panel">
        <div class="label">Recent Trends</div>
        <div class="label-note">最近窗口内的优先级、燃油、ERS、胎耗和速度变化趋势。</div>
        <svg id="trend" class="chart" viewBox="0 0 900 180" preserveAspectRatio="none"></svg>
      </div>
      <div class="panel">
        <div class="label">Latest State</div>
        <div class="label-note">最新一帧的玩家状态、赛道上下文和对手概况。</div>
        <div class="list" id="latest-state"></div>
      </div>
    </div>
    <div class="two">
      <div class="panel">
        <div class="label">Frame Browser</div>
        <div class="label-note">按圈筛选并逐帧查看该帧的状态、消息和链路结果。</div>
        <div class="controls">
          <div>
            <div class="helper">按圈筛选</div>
            <select id="lap-filter"></select>
          </div>
          <div>
            <div class="helper">最近帧浏览</div>
            <input id="frame-slider" type="range" min="0" max="0" value="0">
          </div>
          <div>
            <div class="helper">选中帧</div>
            <div id="frame-label" class="metric mono" style="font-size:20px"></div>
          </div>
        </div>
        <div class="list" id="frame-detail" style="margin-top:16px"></div>
      </div>
      <div class="panel">
        <div class="label">Segment Heatmap</div>
        <div class="label-note">按赛道顺序查看哪些区段累计了更高风险和更多高优先级事件。</div>
        <div id="heatmap"></div>
      </div>
    </div>
    <div class="panel" style="margin-bottom:16px;">
      <div class="label">Parse To Model Chain</div>
      <div class="sub" style="margin:8px 0 0;">选中帧的真实包解析字段 -> 语义层 -> 策略输出。用于检查数据如何进入模型语义与策略仲裁。</div>
      <div class="chain-intro">
        <div class="chain-note"><strong>Parsed Packet Fields</strong><br>真实包里直接解析出来的字段，还没有做策略语义解释。</div>
        <div class="chain-note"><strong>Field Sources</strong><br>上面这些字段分别来自哪个 packet，用于核对来源和解码路径。</div>
        <div class="chain-note"><strong>Semantic Layer</strong><br>把原始字段转换成赛道上下文、驾驶状态和模型语义后的结果。</div>
        <div class="chain-note"><strong>Strategy Output</strong><br>策略引擎基于语义层算出的风险、候选动作和最终消息。</div>
      </div>
      <div class="chain-actions">
        <div>
          <div class="helper">按 packet 过滤解析字段</div>
          <select id="packet-filter"></select>
        </div>
        <div class="helper">`Field Sources` 现在同时显示 packet -> fields 和 field -> packet / decoder 方法 / snapshot raw key 映射。</div>
      </div>
      <div class="chain-grid">
        <div>
          <div class="label">Parsed Packet Fields</div>
          <pre id="chain-parsed" class="jsonbox"></pre>
        </div>
        <div>
          <div class="label">Field Sources</div>
          <pre id="chain-sources" class="jsonbox"></pre>
        </div>
        <div>
          <div class="label">Semantic Layer</div>
          <pre id="chain-semantics" class="jsonbox"></pre>
        </div>
        <div>
          <div class="label">Strategy Output</div>
          <pre id="chain-output" class="jsonbox"></pre>
        </div>
      </div>
      <div class="chain-grid" style="margin-top:16px;">
        <div style="grid-column: span 2;">
          <div class="label">Trigger Highlights</div>
          <div class="label-note">当前帧哪些字段直接触发了语义变化或策略变化。</div>
          <pre id="chain-triggers" class="jsonbox" style="min-height:220px;"></pre>
        </div>
        <div style="grid-column: span 2;">
          <div class="label">Frame Change Diff</div>
          <div class="label-note">与上一帧相比，哪些解析字段、语义字段和策略输出发生了变化。</div>
          <pre id="chain-diff" class="jsonbox" style="min-height:220px;"></pre>
        </div>
      </div>
    </div>
    <div class="two">
      <div class="panel">
        <div class="label">Recent Strategy Events</div>
        <div class="label-note">最近触发的策略消息，按最近帧倒序展示。</div>
        <div class="list" id="events"></div>
      </div>
      <div class="panel">
        <div class="label">Rival Overview</div>
        <div class="label-note">最近窗口里最常出现的对手、消息代码和赛道区段统计。</div>
        <table><thead><tr><th>Rival</th><th>Frames</th></tr></thead><tbody id="rivals"></tbody></table>
        <div class="label">Top Message Codes</div>
        <div class="label-note">最近窗口里最常出现的策略消息代码。</div>
        <table><thead><tr><th>Code</th><th>Count</th></tr></thead><tbody id="codes"></tbody></table>
        <div class="label" style="margin-top: 18px;">Top Track Segments</div>
        <div class="label-note">最近窗口里出现频率最高的赛道区段。</div>
        <table><thead><tr><th>Segment</th><th>Frames</th></tr></thead><tbody id="segments"></tbody></table>
      </div>
    </div>
  </div>
  <script>
    const payload = {embedded};
    const latest = payload.latest || {{}};
    const player = latest.player || {{}};
    const rivals = latest.rivals || [];
    const debug = latest.debug || {{}};
    const context = debug.context || {{}};
    const raw = latest.raw || {{}};
    const captureSummary = payload.capture_summary || {{}};
    const frames = payload.frames || [];
    const laps = payload.laps || [];
    const latestMessages = latest.messages || [];
    const latestChain = payload.latest_chain || {{}};
    const packetFilters = payload.packet_filters || [];
    const timingSummary = payload.timing_summary || {{}};

    document.getElementById('track').textContent = latest.track || '-';
    document.getElementById('lap').textContent = latest.lap_number ?? '-';
    document.getElementById('fuel').textContent = Number(player.fuel_laps_remaining || 0).toFixed(1);
    document.getElementById('ers').textContent = `${{Number(player.ers_pct || 0).toFixed(0)}}%`;
    document.getElementById('capture-wall-time').textContent = timingSummary.capture_wall_label || '-';
    document.getElementById('session-span-time').textContent = timingSummary.session_span_label || '-';
    document.getElementById('capture-wall-seconds').textContent = String(timingSummary.capture_wall_seconds ?? '-');
    document.getElementById('session-span-seconds').textContent = String(timingSummary.session_span_seconds ?? '-');
    document.getElementById('top-priority').textContent = String((latest.messages || [])[0]?.priority ?? 0);
    document.getElementById('top-usage').textContent = context.track_usage || '-';
    document.getElementById('rival-count').textContent = String(rivals.length || 0);
    document.getElementById('primary-call').textContent = latestMessages[0]?.title || 'No active call';
    document.getElementById('primary-detail').textContent = latestMessages[0]?.detail || 'No high-priority strategy output in the latest frame.';
    document.getElementById('strategy-stack').innerHTML = latestMessages.slice(0, 5).map((item) => `<div class="item"><span class="pill">P${{item.priority}}</span><strong>${{item.title}}</strong><div>${{item.detail}}</div></div>`).join('');
    const coverage = captureSummary.coverage || {{}};
    document.getElementById('protocol-coverage').innerHTML = [
      ['Packets Present', coverage.present_packet_kinds ?? '-'],
      ['Packets Decoded', coverage.decoded_packet_kinds ?? '-'],
      ['Unknown Packet Kinds', coverage.unknown_packet_kinds ?? '-'],
      ['Snapshots', captureSummary.normalized_snapshots ?? '-'],
      ['Strategy Events', captureSummary.emitted_strategy_events ?? '-'],
      ['Decoded Kinds', (captureSummary.decoded_kinds || []).join(', ') || '-'],
      ['Unknown Kinds', (captureSummary.unknown_kinds || []).join(', ') || '-'],
    ].map(([k, v]) => `<div class="item"><span class="pill">${{k}}</span>${{v}}</div>`).join('');

    const latestState = [
      ['Driver', player.name || 'Player'],
      ['Position', player.position],
      ['Speed', `${{Number(player.speed_kph || 0).toFixed(0)}} km/h`],
      ['Tyre', `${{player.tyre?.compound || '-'}} / ${{Number(player.tyre?.wear_pct || 0).toFixed(1)}}%`],
      ['Segment', context.track_segment || '-'],
      ['Zone', context.track_zone || '-'],
      ['Usage', context.track_usage || '-'],
      ['Tags', (player.status_tags || []).join(', ') || 'stable'],
      ['Front Wing', `${{raw.wing_damage_pct?.front_left ?? 0}} / ${{raw.wing_damage_pct?.front_right ?? 0}}`],
      ['Rivals', rivals.length ? rivals.map((item) => item.name).join(', ') : '0 tracked'],
    ];
    document.getElementById('latest-state').innerHTML = latestState.map(([k,v]) => `<div class="item"><span class="pill">${{k}}</span>${{v}}</div>`).join('');

    const events = payload.recent_messages || [];
    document.getElementById('events').innerHTML = events.slice().reverse().map((item) => {{
      const cls = item.priority >= 90 ? 'prio-high' : item.priority >= 70 ? 'prio-mid' : '';
      return `<div class="item"><div><span class="pill">Lap ${{item.lap ?? '-'}}</span><span class="pill">F${{item.frame ?? '-'}}</span><strong class="${{cls}}">P${{item.priority}} ${{item.title}}</strong></div><div>${{item.detail}}</div></div>`;
    }}).join('');

    document.getElementById('codes').innerHTML = (payload.totals?.message_counts || []).map(([code, count]) => `<tr><td>${{code}}</td><td>${{count}}</td></tr>`).join('');
    document.getElementById('segments').innerHTML = (payload.totals?.segments || []).map(([name, count]) => `<tr><td>${{name}}</td><td>${{count}}</td></tr>`).join('');
    document.getElementById('rivals').innerHTML = (payload.totals?.rivals || []).map(([name, count]) => `<tr><td>${{name}}</td><td>${{count}}</td></tr>`).join('');

    const heatmap = payload.heatmap || [];
    const heatMax = Math.max(...heatmap.map(item => item.risk_score || 0), 1);
    document.getElementById('heatmap').innerHTML = heatmap.map((item) => {{
      const width = ((item.risk_score || 0) / heatMax) * 100;
      return `<div class="heat-row"><div><strong>${{item.segment}}</strong><div class="helper">${{item.zone}} | ${{item.usage || '-'}} | frames=${{item.frames}} | maxP=${{item.max_priority}}</div></div><div class="heat-bar"><span style="width:${{width}}%"></span></div><div class="mono">${{item.risk_score}}</div></div>`;
    }}).join('');

    const svg = document.getElementById('trend');
    const series = payload.series || {{}};
    const colors = [
      ['priority', '#d9480f', 120],
      ['fuel', '#005bbb', 12],
      ['ers', '#2b8a3e', 100],
      ['tyre_wear', '#9c6b00', 100],
      ['speed', '#6c2bd9', 350],
    ];
    const w = 900, h = 180, pad = 10;
    function linePath(values, maxValue) {{
      if (!values.length) return '';
      return values.map((v, i) => {{
        const x = pad + (i * (w - pad * 2) / Math.max(values.length - 1, 1));
        const y = h - pad - ((Math.min(v, maxValue) / maxValue) * (h - pad * 2));
        return `${{i === 0 ? 'M' : 'L'}}${{x.toFixed(2)}},${{y.toFixed(2)}}`;
      }}).join(' ');
    }}
    svg.innerHTML = colors.map(([key, color, maxValue]) => `<path d="${{linePath(series[key] || [], maxValue)}}" fill="none" stroke="${{color}}" stroke-width="2.2"/>`).join('');

    const lapFilter = document.getElementById('lap-filter');
    lapFilter.innerHTML = ['<option value="all">全部最近帧</option>'].concat(laps.map((lap) => `<option value="${{lap}}">Lap ${{lap}}</option>`)).join('');
    const slider = document.getElementById('frame-slider');
    const frameLabel = document.getElementById('frame-label');
    const frameDetail = document.getElementById('frame-detail');
    const packetFilter = document.getElementById('packet-filter');
    const chainParsed = document.getElementById('chain-parsed');
    const chainSources = document.getElementById('chain-sources');
    const chainSemantics = document.getElementById('chain-semantics');
    const chainOutput = document.getElementById('chain-output');
    const chainTriggers = document.getElementById('chain-triggers');
    const chainDiff = document.getElementById('chain-diff');
    let filteredFrames = frames.slice();
    packetFilter.innerHTML = ['<option value="all">全部 packet</option>'].concat(packetFilters.map((name) => `<option value="${{name}}">${{name}}</option>`)).join('');

    function pretty(value) {{
      return JSON.stringify(value ?? {{}}, null, 2);
    }}

    function filterParsedFields(chain, selectedPacket) {{
      const parsed = Object.assign({{}}, chain.parsed_packet_fields || {{}});
      const trace = chain.field_trace || {{}};
      if (selectedPacket === 'all') return parsed;
      const filtered = {{}};
      Object.entries(parsed).forEach(([key, value]) => {{
        if ((trace[key] || {{}}).packet === selectedPacket) filtered[key] = value;
      }});
      return filtered;
    }}

    function filterFieldSources(chain, selectedPacket) {{
      const packetFields = chain.field_sources || {{}};
      const fieldTrace = chain.field_trace || {{}};
      if (selectedPacket === 'all') {{
        return {{
          packet_fields: packetFields,
          field_trace: fieldTrace,
        }};
      }}
      const filteredTrace = {{}};
      Object.entries(fieldTrace).forEach(([field, meta]) => {{
        if ((meta || {{}}).packet === selectedPacket) filteredTrace[field] = meta;
      }});
      return {{
        packet_fields: {{
          [selectedPacket]: packetFields[selectedPacket] || [],
        }},
        field_trace: filteredTrace,
      }};
    }}

    function renderChain(chain) {{
      const fallback = latestChain || {{}};
      const active = chain || fallback;
      const selectedPacket = packetFilter.value || 'all';
      chainParsed.textContent = pretty(filterParsedFields(active, selectedPacket));
      chainSources.textContent = pretty(filterFieldSources(active, selectedPacket));
      chainSemantics.textContent = pretty(active.semantic_layer || {{}});
      chainOutput.textContent = pretty(active.strategy_output || {{}});
      chainTriggers.textContent = pretty(active.trigger_highlights || {{}});
      chainDiff.textContent = pretty(active.frame_diff || {{}});
    }}

    function renderFrame(index) {{
      if (!filteredFrames.length) {{
        frameLabel.textContent = '-';
        frameDetail.innerHTML = '<div class="item">没有可显示的帧数据</div>';
        renderChain(latestChain);
        return;
      }}
      const frame = filteredFrames[index];
      frameLabel.textContent = `F${{frame.frame}}`;
      const detail = [
        ['Lap', frame.lap],
        ['Segment', `${{frame.segment}} (${{frame.zone}})`],
        ['Usage', frame.usage || '-'],
        ['Speed', `${{Number(frame.speed || 0).toFixed(0)}} km/h`],
        ['Fuel', Number(frame.fuel || 0).toFixed(2)],
        ['ERS', `${{Number(frame.ers || 0).toFixed(0)}}%`],
        ['Tyre', `${{frame.tyre_compound}} / ${{Number(frame.tyre_wear || 0).toFixed(1)}}%`],
        ['Priority', frame.top_priority || 0],
        ['Message', frame.top_message || '-'],
        ['Tags', (frame.tags || []).join(', ') || 'stable'],
        ['Rivals', frame.rival_names?.join(', ') || `${{frame.rivals}} tracked`],
        ['Wing', `${{frame.wing_front_left}} / ${{frame.wing_front_right}}`],
        ['Event', frame.event_code || '-'],
      ];
      frameDetail.innerHTML = detail.map(([k, v]) => `<div class="item"><span class="pill">${{k}}</span>${{v}}</div>`).join('');
      renderChain(frame.chain);
    }}

    function applyLapFilter() {{
      const selectedLap = lapFilter.value;
      filteredFrames = selectedLap === 'all' ? frames.slice() : frames.filter((item) => String(item.lap) === selectedLap);
      slider.min = 0;
      slider.max = Math.max(filteredFrames.length - 1, 0);
      slider.value = Math.max(filteredFrames.length - 1, 0);
      renderFrame(Number(slider.value));
    }}

    lapFilter.addEventListener('change', applyLapFilter);
    slider.addEventListener('input', () => renderFrame(Number(slider.value)));
    packetFilter.addEventListener('change', () => renderFrame(Number(slider.value || 0)));
    renderChain(latestChain);
    applyLapFilter();
  </script>
</body>
</html>
"""

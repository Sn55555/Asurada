from __future__ import annotations

import json
from pathlib import Path

from .track_model import load_track_profile
from .dashboard_template import load_dashboard_template


class DebugDashboardBuilder:
    """Builds a compact offline debug dashboard from the replay log."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_rows(self, session_log_path: Path) -> list[dict]:
        rows: list[dict] = []
        if not session_log_path.exists():
            return rows
        with session_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def build_from_session_log(self, session_log_path: Path) -> Path:
        rows = self._load_rows(session_log_path)
        latest = rows[-1] if rows else {}
        track_name = latest.get("track") if latest else None
        track_profile = load_track_profile(str(track_name)) if track_name else None
        laps: list[int] = []
        seen_laps: set[int] = set()
        frames: list[dict] = []

        for row in rows:
            player = row.get("player", {}) or {}
            raw = row.get("raw", {}) or {}
            debug = row.get("debug", {}) or {}
            context = debug.get("context", {}) or {}
            rivals = row.get("rivals", []) or []
            messages = row.get("messages", []) or []

            lap_number = int(row.get("lap_number", 0) or 0)
            if lap_number not in seen_laps:
                seen_laps.add(lap_number)
                laps.append(lap_number)

            player_position = int(player.get("position", 0) or 0)
            front_rival = next((item for item in rivals if int(item.get("position", 0) or 0) == player_position - 1), None)
            rear_rival = next((item for item in rivals if int(item.get("position", 0) or 0) == player_position + 1), None)

            frames.append(
                {
                    "frame": int(raw.get("frame_identifier", 0) or 0),
                    "lap": lap_number,
                    "session_time_s": float(raw.get("session_time_s", 0.0) or 0.0),
                    "total_laps": int(row.get("total_laps") or (raw.get("session_packet", {}) or {}).get("total_laps", 0) or 0),
                    "lap_distance_m": float(raw.get("lap_distance_m", 0.0) or 0.0),
                    "front_rival_lap_distance_m": raw.get("front_rival_lap_distance_m"),
                    "rear_rival_lap_distance_m": raw.get("rear_rival_lap_distance_m"),
                    "track": row.get("track"),
                    "weather": row.get("weather"),
                    "speed": float(player.get("speed_kph", 0.0) or 0.0),
                    "position": player_position,
                    "fuel_laps_remaining": player.get("fuel_laps_remaining"),
                    "ers_pct": player.get("ers_pct"),
                    "tyre_wear_pct": (player.get("tyre") or {}).get("wear_pct"),
                    "gap_ahead_s": player.get("gap_ahead_s"),
                    "gap_behind_s": player.get("gap_behind_s"),
                    "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
                    "official_gap_behind_s": raw.get("official_gap_behind_s"),
                    "estimated_gap_ahead_s": raw.get("estimated_gap_ahead_s"),
                    "estimated_gap_behind_s": raw.get("estimated_gap_behind_s"),
                    "throttle": raw.get("throttle"),
                    "brake": raw.get("brake"),
                    "steer": raw.get("steer"),
                    "gear": raw.get("gear"),
                    "rpm": raw.get("rpm"),
                    "top_priority": messages[0].get("priority", 0) if messages else 0,
                    "top_message": messages[0].get("code") or messages[0].get("title") if messages else "",
                    "top_detail": messages[0].get("detail", "") if messages else "",
                    "messages": messages,
                    "track_zone": context.get("track_zone"),
                    "track_segment": context.get("track_segment"),
                    "track_usage": context.get("track_usage"),
                    "driving_mode": context.get("driving_mode"),
                    "assessment": debug.get("assessment", {}) or {},
                    "player_world_x": raw.get("world_position_x"),
                    "player_world_z": raw.get("world_position_z"),
                    "front_world_x": raw.get("front_rival_world_position_x"),
                    "front_world_z": raw.get("front_rival_world_position_z"),
                    "rear_world_x": raw.get("rear_rival_world_position_x"),
                    "rear_world_z": raw.get("rear_rival_world_position_z"),
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
                    "runtime_timing": debug.get("runtime_timing", {}) or {},
                }
            )

        payload = {
            "latest": {
                "track": latest.get("track"),
                "weather": latest.get("weather"),
            },
            "timing_summary": self._build_timing_summary(rows),
            "track_profile": self._serialize_track_profile(track_profile),
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

        timestamps = [
            int(
                row.get("source_timestamp_ms")
                if row.get("source_timestamp_ms") is not None
                else row.get("raw", {}).get("source_timestamp_ms", 0)
            )
            for row in rows
            if row.get("source_timestamp_ms") is not None
            or row.get("raw", {}).get("source_timestamp_ms") is not None
        ]
        session_times = [
            float(row.get("raw", {}).get("session_time_s", 0.0))
            for row in rows
            if row.get("raw", {}).get("session_time_s") is not None
        ]
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
            "official_gap_ahead_s": rival.get("official_gap_ahead_s"),
            "official_gap_behind_s": rival.get("official_gap_behind_s"),
            "estimated_gap_ahead_s": rival.get("estimated_gap_ahead_s"),
            "estimated_gap_behind_s": rival.get("estimated_gap_behind_s"),
            "gap_source_ahead": rival.get("gap_source_ahead"),
            "gap_source_behind": rival.get("gap_source_behind"),
            "relation": relation,
        }

    def _extract_stage_two_model_debug(self, row: dict) -> dict:
        debug = row.get("debug", {}) or {}
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
            "tyre_degradation_trend_models": arbiter_input.get("tyre_degradation_trend_models", {}) or {},
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

    def _serialize_track_profile(self, track_profile) -> dict:
        if track_profile is None:
            return {}
        return {
            "track": track_profile.track,
            "lap_length_m": track_profile.lap_length_m,
            "semantic_segments": [
                {
                    "name": segment.name,
                    "zone_type": segment.zone_type,
                    "start_m": segment.start_m,
                    "end_m": segment.end_m,
                    "usage": segment.usage,
                }
                for segment in track_profile.semantic_segments
            ],
            "braking_zones": [
                {
                    "name": zone.name,
                    "start_m": zone.start_m,
                    "end_m": zone.end_m,
                }
                for zone in track_profile.braking_zones
            ],
            "corner_apexes": [
                {
                    "name": apex.name,
                    "distance_m": apex.distance_m,
                    "window_m": apex.window_m,
                }
                for apex in track_profile.corner_apexes
            ],
        }

    def _render_html(self, payload: dict) -> str:
        embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        template = load_dashboard_template()
        return template.replace("__EMBEDDED_PAYLOAD__", embedded)

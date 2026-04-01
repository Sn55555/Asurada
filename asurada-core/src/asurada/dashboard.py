from __future__ import annotations

import json
from pathlib import Path

from .track_model import load_track_profile


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
                    "total_laps": int((raw.get("session_packet", {}) or {}).get("total_laps", 0) or 0),
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
        template = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Asurada Offline Debug Dashboard</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --card: #ffffff;
      --line: #d6ddea;
      --line-strong: #b7c2d4;
      --text: #0f1b2d;
      --muted: #5f6e85;
      --accent: #0b63ce;
      --good: #117a5a;
      --warn: #a45a00;
      --bad: #b33d3f;
      --shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "SF Pro Display", "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .wrap {
      max-width: 1500px;
      margin: 0 auto;
      padding: 20px;
    }
    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
      margin-bottom: 16px;
    }
    .page-header h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.1;
    }
    .page-header p {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
      max-width: 760px;
    }
    .meta-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    .meta-chip {
      padding: 8px 12px;
      border-radius: 999px;
      background: #eef4fb;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .section-title {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 12px;
    }
    .section-title h2 {
      margin: 0;
      font-size: 16px;
    }
    .section-title span {
      color: var(--muted);
      font-size: 12px;
    }
    .controls {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr) 96px 96px 96px 150px;
      gap: 12px;
      align-items: end;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    select, input[type="range"], button {
      width: 100%;
      font: inherit;
    }
    select, button {
      height: 40px;
      border-radius: 10px;
      border: 1px solid var(--line-strong);
      background: #fff;
      color: var(--text);
      padding: 0 12px;
    }
    button { cursor: pointer; }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.16fr) minmax(0, 0.84fr);
      gap: 16px;
      margin-top: 16px;
    }
    .stack {
      display: grid;
      gap: 16px;
      min-width: 0;
    }
    .kv-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .kv {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fafcff;
    }
    .kv small {
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .kv strong {
      display: block;
      font-size: 18px;
      line-height: 1.25;
    }
    .subtext {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .trace-list, .signal-list {
      display: grid;
      gap: 10px;
    }
    .trace-row, .signal-row {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fafcff;
    }
    .trace-row header, .signal-row header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }
    .trace-row header strong, .signal-row header strong {
      font-size: 14px;
    }
    .trace-row header span, .signal-row header span {
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }
    .trace-row p, .signal-row p {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .pill-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }
    .pill {
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      font-size: 12px;
      color: var(--text);
    }
    .pill.muted { color: var(--muted); }
    .rival-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .rival-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fafcff;
    }
    .rival-card h3 {
      margin: 0 0 10px;
      font-size: 14px;
    }
    .rival-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .rival-stats div {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fff;
    }
    .rival-stats small {
      display: block;
      color: var(--muted);
      font-size: 10px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .rival-stats strong {
      display: block;
      font-size: 15px;
    }
    .track-context-wrap {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fcfdff;
      padding: 12px;
    }
    .track-bar {
      position: relative;
      width: 100%;
      height: 28px;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--line);
      background: #eef3fa;
    }
    .track-segments {
      position: absolute;
      inset: 0;
    }
    .track-segment {
      position: absolute;
      top: 0;
      bottom: 0;
    }
    .track-marker {
      position: absolute;
      top: -8px;
      width: 12px;
      height: 44px;
      transform: translateX(-50%);
      pointer-events: none;
    }
    .track-marker::before {
      content: "";
      position: absolute;
      left: 50%;
      top: 0;
      transform: translateX(-50%);
      width: 0;
      height: 0;
      border-left: 7px solid transparent;
      border-right: 7px solid transparent;
      border-top: 0;
      border-bottom: 12px solid #0f1b2d;
    }
    .track-marker::after {
      content: "";
      position: absolute;
      left: 50%;
      top: 12px;
      transform: translateX(-50%);
      width: 4px;
      height: 32px;
      background: #0f1b2d;
      border-radius: 999px;
    }
    .track-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .track-legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .track-legend i {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      display: inline-block;
    }
    .track-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .track-context-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .track-context-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fafcff;
    }
    .track-context-card small {
      display: block;
      color: var(--muted);
      font-size: 10px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .track-context-card strong {
      display: block;
      font-size: 15px;
      line-height: 1.3;
    }
    .track-context-card .subtext {
      margin-top: 6px;
    }
    .timeline-summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .timeline-summary .kv strong {
      font-size: 16px;
    }
    .event-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .event-table th,
    .event-table td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    .event-table th {
      color: var(--muted);
      font-weight: 600;
    }
    .json-block {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #0f172a;
      color: #d6e1f2;
      min-height: 180px;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SF Mono", "JetBrains Mono", monospace;
      font-size: 11px;
      line-height: 1.55;
    }
    .tone-good { color: var(--good); }
    .tone-warn { color: var(--warn); }
    .tone-bad { color: var(--bad); }
    @media (max-width: 1200px) {
      .layout { grid-template-columns: 1fr; }
      .controls { grid-template-columns: 1fr 1fr; }
      .kv-grid, .rival-grid, .timeline-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .controls, .kv-grid, .rival-grid, .timeline-summary { grid-template-columns: 1fr; }
      .page-header { flex-direction: column; }
      .meta-strip { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="page-header">
      <div>
        <h1>Asurada Offline Debug Dashboard</h1>
        <p>围绕单帧和短时回放检查状态、策略、仲裁和模型输出。页面只保留离线复盘需要的核心信息，不再承担实时 HUD 观察职责。</p>
      </div>
      <div class="meta-strip" id="meta-strip"></div>
    </header>

    <section class="panel">
      <div class="controls">
        <div class="field">
          <label for="lap-filter">圈数</label>
          <select id="lap-filter"></select>
        </div>
        <div class="field">
          <label for="frame-slider">时间轴</label>
          <input id="frame-slider" type="range" min="0" max="0" step="1">
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button id="prev-frame">上一帧</button>
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button id="play-toggle">播放</button>
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button id="next-frame">下一帧</button>
        </div>
        <div class="field">
          <label>当前索引</label>
          <div class="meta-chip" id="frame-index">0 / 0</div>
        </div>
      </div>

      <div class="timeline-summary">
        <div class="kv"><small>当前帧</small><strong id="timeline-frame">-</strong><div class="subtext" id="timeline-time">-</div></div>
        <div class="kv"><small>赛道段</small><strong id="timeline-track">-</strong><div class="subtext" id="timeline-usage">-</div></div>
        <div class="kv"><small>当前输出</small><strong id="timeline-message">-</strong><div class="subtext" id="timeline-priority">-</div></div>
      </div>
    </section>

    <main class="layout">
      <div class="stack">
        <section class="panel">
          <div class="section-title"><h2>Decision Trace</h2><span>策略、仲裁、输出</span></div>
          <div class="trace-list" id="decision-trace"></div>
        </section>

        <section class="panel">
          <div class="section-title"><h2>Current Frame</h2><span>状态快照</span></div>
          <div class="kv-grid" id="current-frame-grid"></div>
        </section>

        <section class="panel">
          <div class="section-title"><h2>Nearby Frames</h2><span>前后帧对照</span></div>
          <table class="event-table">
            <thead>
              <tr><th>位置</th><th>帧</th><th>时间</th><th>策略</th><th>速度</th><th>后车差距</th></tr>
            </thead>
            <tbody id="neighbor-rows"></tbody>
          </table>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <div class="section-title"><h2>Model Signals</h2><span>参与判断的模型信号</span></div>
          <div class="signal-list" id="model-signals"></div>
        </section>

        <section class="panel">
          <div class="section-title"><h2>Front / Rear Rival</h2><span>相邻车辆状态</span></div>
          <div class="rival-grid" id="rival-grid"></div>
        </section>

        <section class="panel">
          <div class="section-title"><h2>Track Context</h2><span>当前赛段与赛道语义</span></div>
          <div class="track-context-wrap">
            <div class="track-bar">
              <div class="track-segments" id="track-segments"></div>
              <div class="track-marker" id="track-marker"></div>
            </div>
            <div class="track-legend">
              <span><i style="background:#0b63ce"></i>玩家位置</span>
              <span><i style="background:#b33d3f"></i>制动分段</span>
              <span><i style="background:#a45a00"></i>弯道分段</span>
              <span><i style="background:#117a5a"></i>部署直道</span>
            </div>
            <div class="track-meta" id="trajectory-meta"></div>
            <div class="track-context-grid" id="track-context-grid"></div>
          </div>
        </section>

        <section class="panel">
          <div class="section-title"><h2>Raw Debug</h2><span>原始调试信息</span></div>
          <div class="json-block"><pre id="debug-json">-</pre></div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const payload = __EMBEDDED_PAYLOAD__;
    const latest = payload.latest || {};
    const timingSummary = payload.timing_summary || {};
    const trackProfile = payload.track_profile || {};
    const frames = payload.frames || [];
    const laps = payload.laps || [];

    const metaStrip = document.getElementById('meta-strip');
    const lapFilter = document.getElementById('lap-filter');
    const slider = document.getElementById('frame-slider');
    const playToggle = document.getElementById('play-toggle');
    const prevFrameButton = document.getElementById('prev-frame');
    const nextFrameButton = document.getElementById('next-frame');
    const frameIndex = document.getElementById('frame-index');
    const timelineFrame = document.getElementById('timeline-frame');
    const timelineTime = document.getElementById('timeline-time');
    const timelineTrack = document.getElementById('timeline-track');
    const timelineUsage = document.getElementById('timeline-usage');
    const timelineMessage = document.getElementById('timeline-message');
    const timelinePriority = document.getElementById('timeline-priority');
    const currentFrameGrid = document.getElementById('current-frame-grid');
    const rivalGrid = document.getElementById('rival-grid');
    const decisionTrace = document.getElementById('decision-trace');
    const modelSignals = document.getElementById('model-signals');
    const neighborRows = document.getElementById('neighbor-rows');
    const debugJson = document.getElementById('debug-json');
    const trackSegments = document.getElementById('track-segments');
    const trackMarker = document.getElementById('track-marker');
    const trajectoryMeta = document.getElementById('trajectory-meta');
    const trackContextGrid = document.getElementById('track-context-grid');

    let filteredFrames = frames.slice();
    let playbackIndex = Math.max(filteredFrames.length - 1, 0);
    let playbackTimer = null;
    let isPlaying = false;

    function num(value, digits = 1) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return parsed.toFixed(digits);
    }

    function gap(value) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return `${parsed.toFixed(3)}s`;
    }

    function gapWithSource(officialValue, estimatedValue) {
      if (officialValue !== null && officialValue !== undefined && officialValue !== '') {
        return { value: gap(officialValue), detail: 'official' };
      }
      if (estimatedValue !== null && estimatedValue !== undefined && estimatedValue !== '') {
        return { value: gap(estimatedValue), detail: 'estimated' };
      }
      return { value: '-', detail: 'missing' };
    }

    function pct(value) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return `${parsed.toFixed(1)}%`;
    }

    function listCodes(items) {
      if (!Array.isArray(items) || !items.length) return ['-'];
      return items.map((item) => item.code || item.title || '-');
    }

    function chip(text, muted = false) {
      return `<span class="pill${muted ? ' muted' : ''}">${text}</span>`;
    }

    function toneClassForAction(code) {
      if (code === 'LOW_FUEL') return 'tone-warn';
      if (code === 'DYNAMICS_UNSTABLE' || code === 'SAFETY_CAR') return 'tone-bad';
      if (code && code !== 'NONE') return 'tone-good';
      return '';
    }

    function kvCell(label, value, detail = '') {
      return `<div class="kv"><small>${label}</small><strong>${value}</strong><div class="subtext">${detail || '&nbsp;'}</div></div>`;
    }

    function renderMeta() {
      const chips = [
        `赛道 ${latest.track || '-'}`,
        `天气 ${latest.weather || '-'}`,
        `采样时长 ${timingSummary.capture_wall_label || '-'}`,
        `会话跨度 ${timingSummary.session_span_label || '-'}`,
        `总帧数 ${frames.length}`,
      ];
      metaStrip.innerHTML = chips.map((item) => `<div class="meta-chip">${item}</div>`).join('');
      lapFilter.innerHTML = `<option value="all">全部圈数</option>` + laps.map((lap) => `<option value="${lap}">Lap ${lap}</option>`).join('');
    }

    function renderCurrentFrame(frame) {
      const gapAhead = gapWithSource(frame.official_gap_ahead_s, frame.estimated_gap_ahead_s);
      const gapBehind = gapWithSource(frame.official_gap_behind_s, frame.estimated_gap_behind_s);
      currentFrameGrid.innerHTML = [
        kvCell('Top Message', `<span class="${toneClassForAction(frame.top_message)}">${frame.top_message || 'NONE'}</span>`, frame.top_detail || '无额外说明'),
        kvCell('Lap / Total', `${frame.lap || '-'} / ${frame.total_laps || '-'}`, `frame=${frame.frame}`),
        kvCell('Position / Speed', `P${frame.position || '-'} / ${num(frame.speed)} km/h`, frame.track || '-'),
        kvCell('Track Context', `${frame.track_segment || '-'} / ${frame.track_usage || '-'}`, frame.track_zone || '-'),
        kvCell('Gap Ahead', gapAhead.value, `玩家与前车 · ${gapAhead.detail}`),
        kvCell('Gap Behind', gapBehind.value, `玩家与后车 · ${gapBehind.detail}`),
        kvCell('Fuel / ERS', `${num(frame.fuel_laps_remaining, 2)} laps / ${pct(frame.ers_pct)}`, `wear=${pct(frame.tyre_wear_pct)}`),
        kvCell('Controls', `T${num(frame.throttle, 2)} B${num(frame.brake, 2)} S${num(frame.steer, 2)}`, `G${frame.gear ?? '-'} / ${frame.rpm ?? '-'} rpm`),
      ].join('');
    }

    function renderRivals(frame) {
      const rivals = [
        ['前车', frame.front_rival],
        ['后车', frame.rear_rival],
      ];
      rivalGrid.innerHTML = rivals.map(([label, rival]) => `
        <div class="rival-card">
          <h3>${label} · ${rival?.name || '-'}</h3>
          <div class="rival-stats">
            <div><small>位置</small><strong>${rival?.position ? `P${rival.position}` : '-'}</strong></div>
            <div><small>与前车差距</small><strong>${gap(rival?.display_gap_ahead_s)}</strong><div class="subtext">${rival?.official_gap_ahead_s != null ? 'official' : (rival?.estimated_gap_ahead_s != null ? 'estimated' : 'missing')}</div></div>
            <div><small>与后车差距</small><strong>${gap(rival?.display_gap_behind_s)}</strong><div class="subtext">${rival?.official_gap_behind_s != null ? 'official' : (rival?.estimated_gap_behind_s != null ? 'estimated' : 'missing')}</div></div>
            <div><small>速度</small><strong>${rival?.speed_kph != null ? `${num(rival.speed_kph)} km/h` : '-'}</strong></div>
            <div><small>ERS</small><strong>${pct(rival?.ers_pct)}</strong></div>
            <div><small>DRS</small><strong>${rival?.drs_available ? 'OPEN' : 'OFF'}</strong></div>
          </div>
        </div>
      `).join('');
    }

    function renderDecisionTrace(frame) {
      const modelDebug = frame.stage_two_model_debug || {};
      const arbiterInput = modelDebug.arbiter_input || {};
      const arbiterOutput = modelDebug.arbiter_output || {};
      const tactical = arbiterInput.tactical_context || {};
      const confidence = arbiterInput.confidence_context || {};
      const fallback = arbiterInput.fallback_context || {};
      const outputControl = arbiterInput.output_control || {};
      const traces = [
        {
          title: 'Messages',
          value: listCodes(frame.messages || []).join(' / '),
          detail: frame.top_detail || '当前帧输出栈。',
          pills: (frame.messages || []).map((item) => chip(`${item.code || item.title || '-'}@${item.priority ?? '-'}`)),
        },
        {
          title: 'Arbiter',
          value: `${arbiterOutput.final_hud_action?.code || '-'} / ${arbiterOutput.final_voice_action?.code || '-'}`,
          detail: `ordered=${listCodes(arbiterOutput.ordered_actions || []).join(' / ')} | suppressed=${listCodes(arbiterOutput.suppressed_actions || []).join(' / ')}`,
          pills: [
            chip(`rules ${listCodes(arbiterInput.rule_candidates || []).join(' / ')}`, true),
            chip(`models ${listCodes(arbiterInput.model_candidates || []).join(' / ')}`, true),
          ],
        },
        {
          title: 'Tactical State',
          value: tactical.tactical_state || '-',
          detail: `transition=${tactical.state_transition || '-'} | lock=${tactical.state_lock ? 'yes' : 'no'} | priority=${tactical.state_priority_hint || '-'}`,
          pills: [
            chip(`recommended ${tactical.recommended_action || '-'}`),
            chip(`history-hold ${tactical.history_hold_applied ? 'yes' : 'no'}`, true),
          ],
        },
        {
          title: 'Confidence / Fallback',
          value: `${confidence.confidence_level || '-'} / ${fallback.fallback_mode || '-'}`,
          detail: `score=${num(confidence.confidence_score, 2)} | mainline=${fallback.mainline_allowed ? 'yes' : 'no'} | voice=${outputControl.voice_allowed === false ? 'muted' : 'open'}`,
          pills: [
            chip(`hud-only ${outputControl.hud_only ? 'yes' : 'no'}`, true),
            chip(`cooldown ${outputControl.cooldown_hint || '-'}`, true),
          ],
        },
      ];
      decisionTrace.innerHTML = traces.map((item) => `
        <div class="trace-row">
          <header><strong>${item.title}</strong><span>${item.value}</span></header>
          <p>${item.detail}</p>
          <div class="pill-list">${item.pills.join('')}</div>
        </div>
      `).join('');
    }

    function renderModelSignals(frame) {
      const modelDebug = frame.stage_two_model_debug || {};
      const resource = modelDebug.resource_models || {};
      const pressure = modelDebug.rival_pressure_models || {};
      const quality = modelDebug.driving_quality_models || {};
      const tyreTrend = modelDebug.tyre_degradation_trend_models || {};
      const defence = modelDebug.defence_cost_model || {};
      const rows = [
        ['Fuel Risk', num(resource.fuel_risk?.score, 1), '参与 LOW_FUEL 偏置'],
        ['Dynamics Risk', num(resource.dynamics_risk?.score, 1), '参与 DYNAMICS_UNSTABLE 偏置'],
        ['Rear Pressure', num(pressure.rear_pressure?.score, 1), '参与 DEFEND_WINDOW 偏置'],
        ['Defence Cost', num(defence.score, 1), '防守代价侧信号'],
        ['Entry / Apex / Exit', `${num(quality.entry_quality?.score, 1)} / ${num(quality.apex_quality?.score, 1)} / ${num(quality.exit_traction?.score, 1)}`, '驾驶质量分数'],
        ['Tyre / Grip Trend', `${num(tyreTrend.future_tyre_wear_delta?.score, 1)} / ${num(tyreTrend.future_grip_drop_score?.score, 1)}`, '轮胎趋势分数'],
        ['Strategy Candidates', String((modelDebug.strategy_action_model?.model_candidates || []).length), listCodes(modelDebug.strategy_action_model?.model_candidates || []).join(' / ')],
      ];
      modelSignals.innerHTML = rows.map(([label, value, detail]) => `
        <div class="signal-row">
          <header><strong>${label}</strong><span>${value}</span></header>
          <p>${detail}</p>
        </div>
      `).join('');
    }

    function renderNeighbors(index) {
      const rows = [
        ['上一帧', filteredFrames[index - 1]],
        ['当前帧', filteredFrames[index]],
        ['下一帧', filteredFrames[index + 1]],
      ];
      neighborRows.innerHTML = rows.map(([label, item]) => {
        if (!item) {
          return `<tr><td>${label}</td><td colspan="5" class="tone-warn">无数据</td></tr>`;
        }
        return `
          <tr>
            <td>${label}</td>
            <td>${item.frame}</td>
            <td>${num(item.session_time_s, 3)}s</td>
            <td>${item.top_message || 'NONE'}</td>
            <td>${num(item.speed, 1)} km/h</td>
            <td>${gap(item.gap_behind_s)}</td>
          </tr>
        `;
      }).join('');
    }

    function segmentColor(zoneType) {
      if ((zoneType || '').includes('braking')) return '#b33d3f';
      if ((zoneType || '').includes('corner')) return '#a45a00';
      if ((zoneType || '').includes('deployment')) return '#117a5a';
      return '#0b63ce';
    }

    function renderTrackContext(frame) {
      const lapLength = Number(trackProfile.lap_length_m || 0);
      const segments = Array.isArray(trackProfile.semantic_segments) ? trackProfile.semantic_segments : [];
      const lapDistance = Number(frame.lap_distance_m);
      if (!lapLength || Number.isNaN(lapDistance) || !segments.length || !trackSegments || !trackMarker) {
        trajectoryMeta.textContent = '当前样本没有可用的赛道语义分段。';
        if (trackSegments) trackSegments.innerHTML = '';
        if (trackContextGrid) trackContextGrid.innerHTML = '';
        return;
      }

      const currentSegment = segments.find((segment) => lapDistance >= Number(segment.start_m || 0) && lapDistance <= Number(segment.end_m || 0));
      const currentIndex = currentSegment ? segments.findIndex((segment) => segment.name === currentSegment.name) : -1;
      const previousSegment = currentIndex > 0 ? segments[currentIndex - 1] : null;
      const nextSegment = currentIndex >= 0 && currentIndex < segments.length - 1 ? segments[currentIndex + 1] : null;
      const nearestApexes = (Array.isArray(trackProfile.corner_apexes) ? trackProfile.corner_apexes : [])
        .map((apex) => ({ ...apex, delta: Math.abs(Number(apex.distance_m || 0) - lapDistance) }))
        .sort((a, b) => a.delta - b.delta);
      const nearestApex = nearestApexes[0] || null;
      const activeBrakingZone = (Array.isArray(trackProfile.braking_zones) ? trackProfile.braking_zones : []).find((zone) => {
        const start = Number(zone.start_m || 0);
        const end = Number(zone.end_m || 0);
        return lapDistance >= start && lapDistance <= end;
      });

      trackSegments.innerHTML = segments.map((segment) => {
        const start = Number(segment.start_m || 0);
        const end = Number(segment.end_m || 0);
        const left = (start / lapLength) * 100;
        const width = Math.max(((end - start) / lapLength) * 100, 0.35);
        const active = currentSegment && currentSegment.name === segment.name;
        return `<div class="track-segment" style="left:${left}%;width:${width}%;background:${segmentColor(segment.zone_type)};opacity:${active ? '1' : '0.72'}"></div>`;
      }).join('');

      const playerLeft = (Math.max(Math.min(lapDistance, lapLength), 0) / lapLength) * 100;
      trackMarker.style.left = `${playerLeft}%`;

      trajectoryMeta.innerHTML = [
        `当前落点 ${lapDistance.toFixed(0)}m / ${lapLength.toFixed(0)}m`,
        `Lap ${frame.lap || '-'} / ${frame.total_laps || '-'}`,
        `当前位置 ${currentSegment ? currentSegment.name : '-'}`,
        `Usage ${currentSegment?.usage || frame.track_usage || '-'}`,
        `P${frame.position || '-'} · ${num(frame.speed, 1)} km/h`,
      ].map((item) => `<span>${item}</span>`).join('');

      trackContextGrid.innerHTML = [
        ['当前赛段', currentSegment?.name || '-', currentSegment?.zone_type || '-'],
        ['上一赛段', previousSegment?.name || '-', previousSegment?.usage || '-'],
        ['下一赛段', nextSegment?.name || '-', nextSegment?.usage || '-'],
        ['最近 Apex', nearestApex?.name || '-', nearestApex ? `距离 ${nearestApex.delta.toFixed(0)}m` : '-'],
        ['Braking Zone', activeBrakingZone?.name || '当前不在制动区', activeBrakingZone ? `${activeBrakingZone.start_m.toFixed(0)}m - ${activeBrakingZone.end_m.toFixed(0)}m` : '-'],
        ['前后车判断', `前车 ${gap(frame.gap_ahead_s)} / 后车 ${gap(frame.gap_behind_s)}`, '这里统一用时间差，不再显示圈内米数'],
      ].map(([label, value, detail]) => `
        <div class="track-context-card">
          <small>${label}</small>
          <strong>${value}</strong>
          <div class="subtext">${detail}</div>
        </div>
      `).join('');
    }

    function renderDebug(frame) {
      debugJson.textContent = JSON.stringify({
        frame: frame.frame,
        lap: frame.lap,
        messages: frame.messages,
        runtime_timing: frame.runtime_timing,
        stage_two_model_debug: frame.stage_two_model_debug,
      }, null, 2);
    }

    function renderFrame(index) {
      if (!filteredFrames.length) return;
      playbackIndex = Math.min(Math.max(index, 0), filteredFrames.length - 1);
      const frame = filteredFrames[playbackIndex];
      frameIndex.textContent = `${playbackIndex + 1} / ${filteredFrames.length}`;
      timelineFrame.textContent = `#${frame.frame}`;
      timelineTime.textContent = `Lap ${frame.lap || '-'} · ${num(frame.session_time_s, 3)}s`;
      timelineTrack.textContent = frame.track_segment || '-';
      timelineUsage.textContent = `${frame.track_usage || '-'} / ${frame.track_zone || '-'}`;
      timelineMessage.innerHTML = `<span class="${toneClassForAction(frame.top_message)}">${frame.top_message || 'NONE'}</span>`;
      timelinePriority.textContent = `priority=${frame.top_priority || 0}`;
      slider.value = String(playbackIndex);
      renderCurrentFrame(frame);
      renderRivals(frame);
      renderDecisionTrace(frame);
      renderModelSignals(frame);
      renderNeighbors(playbackIndex);
      renderTrackContext(frame);
      renderDebug(frame);
    }

    function clearPlayback() {
      if (playbackTimer !== null) {
        clearInterval(playbackTimer);
        playbackTimer = null;
      }
    }

    function updatePlayLabel() {
      playToggle.textContent = isPlaying ? '暂停' : '播放';
    }

    function applyLapFilter() {
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      const selectedLap = lapFilter.value;
      filteredFrames = selectedLap === 'all' ? frames.slice() : frames.filter((frame) => String(frame.lap) === selectedLap);
      slider.min = 0;
      slider.max = String(Math.max(filteredFrames.length - 1, 0));
      playbackIndex = Math.max(filteredFrames.length - 1, 0);
      renderFrame(playbackIndex);
    }

    function step(delta) {
      if (!filteredFrames.length) return;
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      renderFrame(Math.min(Math.max(playbackIndex + delta, 0), filteredFrames.length - 1));
    }

    lapFilter.addEventListener('change', applyLapFilter);
    slider.addEventListener('input', () => {
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      renderFrame(Number(slider.value || 0));
    });
    prevFrameButton.addEventListener('click', () => step(-1));
    nextFrameButton.addEventListener('click', () => step(1));
    playToggle.addEventListener('click', () => {
      isPlaying = !isPlaying;
      updatePlayLabel();
      clearPlayback();
      if (!isPlaying) return;
      playbackTimer = setInterval(() => {
        if (playbackIndex >= filteredFrames.length - 1) {
          clearPlayback();
          isPlaying = false;
          updatePlayLabel();
          return;
        }
        renderFrame(playbackIndex + 1);
      }, 120);
    });

    renderMeta();
    updatePlayLabel();
    applyLapFilter();
  </script>
</body>
</html>
"""
        return template.replace("__EMBEDDED_PAYLOAD__", embedded)

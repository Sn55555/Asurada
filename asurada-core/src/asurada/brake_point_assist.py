from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import SessionState
from .track_model import SemanticSegment, TrackProfile, load_track_profile


@dataclass(frozen=True)
class BrakePointAssistTarget:
    track: str
    braking_zone_name: str
    braking_zone_start_m: float
    braking_zone_end_m: float
    straight_length_m: float
    trigger_distance_m: float
    marker_board_m: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrakePointAssistState:
    mode: str = "off"
    target: BrakePointAssistTarget | None = None
    last_distance_to_target_m: float | None = None
    last_eta_to_target_s: float | None = None
    last_adaptive_offset_m: float | None = None
    next_countdown_value: int | None = None
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.target is not None:
            payload["target"] = self.target.to_dict()
        return payload


@dataclass(frozen=True)
class BrakeAssistArmResult:
    armed: bool
    speak_text: str
    reason: str


@dataclass(frozen=True)
class BrakeAssistReminder:
    speak_text: str
    action_code: str
    target: BrakePointAssistTarget
    countdown_value: int | None = None


class BrakePointAssistController:
    """One-shot 3-2-1 brake-point countdown for the next long straight."""

    MIN_LONG_STRAIGHT_M = 250.0
    DEFAULT_TTS_LATENCY_COMPENSATION_S = 0.55
    DEFAULT_TTS_TUNE_STEP_S = 0.10
    MAX_TTS_LATENCY_COMPENSATION_S = 1.50

    def __init__(self) -> None:
        self._state = BrakePointAssistState()
        self._runtime_tts_latency_offset_s = 0.0
        self._state_path = self._resolve_state_path()
        self._load_state()

    def snapshot(self) -> dict[str, Any]:
        self._load_state()
        payload = self._state.to_dict()
        payload["tts_latency_compensation_s"] = self._tts_latency_compensation_s()
        payload["tts_latency_base_s"] = self._base_tts_latency_compensation_s()
        payload["tts_latency_runtime_offset_s"] = self._runtime_tts_latency_offset_s
        return payload

    def arm_next_long_straight(self, *, state: SessionState) -> BrakeAssistArmResult:
        self._load_state()
        profile = load_track_profile(state.track)
        if profile is None:
            self._state = BrakePointAssistState(mode="off", last_reason="track_profile_unavailable")
            self._persist_state()
            return BrakeAssistArmResult(
                armed=False,
                speak_text="当前赛道还没有可用的刹车点辅助。",
                reason="track_profile_unavailable",
            )

        lap_distance_m = self._lap_distance_m(state)
        if lap_distance_m is None:
            self._state = BrakePointAssistState(mode="off", last_reason="lap_distance_unavailable")
            self._persist_state()
            return BrakeAssistArmResult(
                armed=False,
                speak_text="当前还拿不到赛道位置，暂时没法设置刹车点提醒。",
                reason="lap_distance_unavailable",
            )

        target = self._select_next_long_straight_target(profile=profile, lap_distance_m=lap_distance_m)
        if target is None:
            self._state = BrakePointAssistState(mode="off", last_reason="no_long_straight_target")
            self._persist_state()
            return BrakeAssistArmResult(
                armed=False,
                speak_text="当前这一圈后面没有找到合适的长直道刹车点提醒。",
                reason="no_long_straight_target",
            )

        self._state = BrakePointAssistState(mode="armed", target=target, last_reason="armed")
        self._persist_state()
        return BrakeAssistArmResult(
            armed=True,
            speak_text=f"收到。到 {target.braking_zone_name} 之前，我会给你报三二一。",
            reason="armed",
        )

    def cancel(self) -> BrakeAssistArmResult:
        self._load_state()
        if self._state.mode != "armed" or self._state.target is None:
            self._state = BrakePointAssistState(mode="off", last_reason="nothing_armed")
            self._persist_state()
            return BrakeAssistArmResult(
                armed=False,
                speak_text="当前没有在等待触发的刹车点提醒。",
                reason="nothing_armed",
            )
        target = self._state.target
        self._state = BrakePointAssistState(mode="off", last_reason="cancelled")
        self._persist_state()
        return BrakeAssistArmResult(
            armed=False,
            speak_text=f"已取消 {target.braking_zone_name} 的刹车点提醒。",
            reason="cancelled",
        )

    def status(self) -> BrakeAssistArmResult:
        self._load_state()
        if self._state.mode != "armed" or self._state.target is None:
            return BrakeAssistArmResult(
                armed=False,
                speak_text=f"当前刹车点提醒是关闭的。当前补偿 {self._tts_latency_compensation_s():.2f} 秒。",
                reason="off",
            )
        target = self._state.target
        return BrakeAssistArmResult(
            armed=True,
            speak_text=(
                f"刹车点提醒已开启，目标是 {target.braking_zone_name}，"
                f"当前补偿 {self._tts_latency_compensation_s():.2f} 秒，"
                f"我会在最佳刹车点前给你报三二一。"
            ),
            reason="armed",
        )

    def tune_earlier(self) -> BrakeAssistArmResult:
        self._load_state()
        self._runtime_tts_latency_offset_s = min(
            self.MAX_TTS_LATENCY_COMPENSATION_S - self._base_tts_latency_compensation_s(),
            self._runtime_tts_latency_offset_s + self._tts_tune_step_s(),
        )
        self._persist_state()
        return BrakeAssistArmResult(
            armed=self._state.mode == "armed",
            speak_text=f"收到。刹车点提醒提前一点，当前补偿 {self._tts_latency_compensation_s():.2f} 秒。",
            reason="tuned_earlier",
        )

    def tune_later(self) -> BrakeAssistArmResult:
        self._load_state()
        self._runtime_tts_latency_offset_s = max(
            -self._base_tts_latency_compensation_s(),
            self._runtime_tts_latency_offset_s - self._tts_tune_step_s(),
        )
        self._persist_state()
        return BrakeAssistArmResult(
            armed=self._state.mode == "armed",
            speak_text=f"收到。刹车点提醒晚一点，当前补偿 {self._tts_latency_compensation_s():.2f} 秒。",
            reason="tuned_later",
        )

    def maybe_build_reminder(self, *, state: SessionState) -> BrakeAssistReminder | None:
        self._load_state()
        if self._state.mode != "armed" or self._state.target is None:
            return None

        target = self._state.target
        lap_distance_m = self._lap_distance_m(state)
        if lap_distance_m is None:
            return None

        track_profile = load_track_profile(target.track)
        lap_length_m = track_profile.lap_length_m if track_profile is not None else self._track_length_m(state)
        if lap_length_m is None or lap_length_m <= 0.0:
            return None

        if self._is_inside_target_zone(lap_distance_m=lap_distance_m, target=target):
            self._state = BrakePointAssistState(mode="off", last_reason="zone_passed")
            self._persist_state()
            return None

        speed_kph = float(state.player.speed_kph or 0.0)
        speed_mps = max(speed_kph / 3.6, 0.0)
        if speed_mps <= 0.1:
            return None

        adaptive_offset_m = self._adaptive_brake_offset_m(state=state, speed_kph=speed_kph)
        adjusted_target_distance_m = target.braking_zone_start_m - adaptive_offset_m
        if adjusted_target_distance_m < 0.0:
            adjusted_target_distance_m += lap_length_m
        distance_to_target_m = self._distance_ahead(
            lap_length_m=lap_length_m,
            current_distance_m=lap_distance_m,
            target_distance_m=adjusted_target_distance_m,
        )
        self._state.last_distance_to_target_m = distance_to_target_m
        self._state.last_adaptive_offset_m = adaptive_offset_m
        eta_to_target_s = distance_to_target_m / speed_mps
        self._state.last_eta_to_target_s = eta_to_target_s
        next_countdown_value = self._state.next_countdown_value
        if next_countdown_value is None:
            next_countdown_value = 3
            self._state.next_countdown_value = next_countdown_value

        countdown_value = self._resolve_countdown_value(
            eta_to_target_s=eta_to_target_s,
            speed_kph=speed_kph,
            next_countdown_value=next_countdown_value,
        )
        if countdown_value is None:
            return None

        next_value = countdown_value - 1
        self._state.next_countdown_value = next_value if next_value >= 1 else None
        if countdown_value == 1:
            self._state = BrakePointAssistState(mode="off", last_reason="fired")
        self._persist_state()
        return BrakeAssistReminder(
            speak_text=self._countdown_speak_text(countdown_value),
            action_code=f"BRAKE_POINT_ASSIST_{countdown_value}",
            target=target,
            countdown_value=countdown_value,
        )

    def _resolve_state_path(self) -> Path:
        raw_value = os.getenv("ASURADA_BRAKE_POINT_ASSIST_STATE_PATH")
        if raw_value:
            return Path(raw_value).expanduser().resolve()
        return Path(__file__).resolve().parents[2] / "runtime_logs" / "brake_point_assist_state.json"

    def _load_state(self) -> None:
        path = self._state_path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        self._state = self._state_from_dict(payload.get("state"))
        try:
            self._runtime_tts_latency_offset_s = float(payload.get("runtime_tts_latency_offset_s") or 0.0)
        except (TypeError, ValueError):
            self._runtime_tts_latency_offset_s = 0.0

    def _persist_state(self) -> None:
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "state": self._state.to_dict(),
            "runtime_tts_latency_offset_s": self._runtime_tts_latency_offset_s,
        }
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)

    def _state_from_dict(self, payload: Any) -> BrakePointAssistState:
        if not isinstance(payload, dict):
            return BrakePointAssistState()
        target_payload = payload.get("target")
        target = self._target_from_dict(target_payload)
        return BrakePointAssistState(
            mode=str(payload.get("mode") or "off"),
            target=target,
            last_distance_to_target_m=self._float_or_none(payload.get("last_distance_to_target_m")),
            last_eta_to_target_s=self._float_or_none(payload.get("last_eta_to_target_s")),
            last_adaptive_offset_m=self._float_or_none(payload.get("last_adaptive_offset_m")),
            next_countdown_value=self._int_or_none(payload.get("next_countdown_value")),
            last_reason=str(payload.get("last_reason")) if payload.get("last_reason") is not None else None,
        )

    def _target_from_dict(self, payload: Any) -> BrakePointAssistTarget | None:
        if not isinstance(payload, dict):
            return None
        try:
            return BrakePointAssistTarget(
                track=str(payload["track"]),
                braking_zone_name=str(payload["braking_zone_name"]),
                braking_zone_start_m=float(payload["braking_zone_start_m"]),
                braking_zone_end_m=float(payload["braking_zone_end_m"]),
                straight_length_m=float(payload["straight_length_m"]),
                trigger_distance_m=float(payload["trigger_distance_m"]),
                marker_board_m=int(payload["marker_board_m"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _float_or_none(self, value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    def _select_next_long_straight_target(
        self,
        *,
        profile: TrackProfile,
        lap_distance_m: float,
    ) -> BrakePointAssistTarget | None:
        candidates = self._build_targets(profile)
        if not candidates:
            return None
        best: tuple[float, BrakePointAssistTarget] | None = None
        for target in candidates:
            distance_ahead = self._distance_ahead(
                lap_length_m=profile.lap_length_m,
                current_distance_m=lap_distance_m,
                target_distance_m=target.braking_zone_start_m,
            )
            if distance_ahead < 30.0:
                continue
            if best is None or distance_ahead < best[0]:
                best = (distance_ahead, target)
        return None if best is None else best[1]

    def _build_targets(self, profile: TrackProfile) -> list[BrakePointAssistTarget]:
        targets: list[BrakePointAssistTarget] = []
        segments = profile.semantic_segments
        if not segments:
            return targets
        for index, segment in enumerate(segments):
            if segment.zone_type != "braking_entry":
                continue
            straight_length_m = self._contiguous_straight_length(segments=segments, braking_index=index)
            if straight_length_m < self.MIN_LONG_STRAIGHT_M:
                continue
            trigger_distance_m = self._trigger_distance_m(straight_length_m)
            marker_board_m = max(50, int(round(trigger_distance_m / 50.0) * 50))
            targets.append(
                BrakePointAssistTarget(
                    track=profile.track,
                    braking_zone_name=segment.name,
                    braking_zone_start_m=float(segment.start_m),
                    braking_zone_end_m=float(segment.end_m),
                    straight_length_m=straight_length_m,
                    trigger_distance_m=trigger_distance_m,
                    marker_board_m=marker_board_m,
                )
            )
        return targets

    def _contiguous_straight_length(self, *, segments: list[SemanticSegment], braking_index: int) -> float:
        total = 0.0
        index = braking_index - 1
        while index >= 0:
            segment = segments[index]
            if segment.zone_type != "deployment_straight":
                break
            total += max(float(segment.end_m) - float(segment.start_m), 0.0)
            index -= 1
        return total

    def _trigger_distance_m(self, straight_length_m: float) -> float:
        if straight_length_m >= 900.0:
            return 220.0
        if straight_length_m >= 500.0:
            return 180.0
        return 150.0

    def _resolve_countdown_value(
        self,
        *,
        eta_to_target_s: float,
        speed_kph: float,
        next_countdown_value: int,
    ) -> int | None:
        if speed_kph < 80.0 or next_countdown_value < 1:
            return None
        lead_s = self._tts_latency_compensation_s()
        for countdown_value in range(next_countdown_value, 0, -1):
            if eta_to_target_s <= float(countdown_value) + lead_s:
                return countdown_value
        return None

    def _tts_latency_compensation_s(self) -> float:
        return min(
            self.MAX_TTS_LATENCY_COMPENSATION_S,
            max(0.0, self._base_tts_latency_compensation_s() + self._runtime_tts_latency_offset_s),
        )

    def _base_tts_latency_compensation_s(self) -> float:
        raw_value = os.getenv("ASURADA_BRAKE_POINT_ASSIST_TTS_LATENCY_S")
        if not raw_value:
            return self.DEFAULT_TTS_LATENCY_COMPENSATION_S
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            return self.DEFAULT_TTS_LATENCY_COMPENSATION_S

    def _tts_tune_step_s(self) -> float:
        raw_value = os.getenv("ASURADA_BRAKE_POINT_ASSIST_TUNE_STEP_S")
        if not raw_value:
            return self.DEFAULT_TTS_TUNE_STEP_S
        try:
            return max(0.01, float(raw_value))
        except (TypeError, ValueError):
            return self.DEFAULT_TTS_TUNE_STEP_S

    def _countdown_speak_text(self, countdown_value: int) -> str:
        mapping = {
            3: "三",
            2: "二",
            1: "一",
        }
        return mapping.get(countdown_value, str(countdown_value))

    def _adaptive_brake_offset_m(self, *, state: SessionState, speed_kph: float) -> float:
        offset_m = 0.0
        weather = (state.weather or "").strip().lower()
        if any(token in weather for token in ("rain", "wet", "storm", "inter", "monsoon")):
            offset_m += 25.0
        elif any(token in weather for token in ("drizzle", "lightrain", "light_rain", "showers")):
            offset_m += 15.0

        tyre = state.player.tyre
        compound = str(getattr(tyre, "compound", "") or "").strip().lower()
        if compound in {"wet", "fullwet", "full_wet"}:
            offset_m += 28.0
        elif compound in {"inter", "intermediate", "intermediates"}:
            offset_m += 16.0
        elif compound in {"hard"}:
            offset_m += 6.0
        elif compound in {"soft"}:
            offset_m = max(0.0, offset_m - 3.0)

        wear_pct = max(float(getattr(tyre, "wear_pct", 0.0) or 0.0), 0.0)
        if wear_pct >= 70.0:
            offset_m += 28.0
        elif wear_pct >= 50.0:
            offset_m += 18.0
        elif wear_pct >= 30.0:
            offset_m += 8.0

        avg_surface_temp = self._avg_numeric(getattr(tyre, "surface_temperature_c", []))
        avg_inner_temp = self._avg_numeric(getattr(tyre, "inner_temperature_c", []))
        hot_temp_c = max(avg_surface_temp or 0.0, avg_inner_temp or 0.0)
        cold_temp_c = min(value for value in (avg_surface_temp, avg_inner_temp) if value is not None) if (avg_surface_temp is not None or avg_inner_temp is not None) else None
        if hot_temp_c >= 108.0:
            offset_m += 10.0
        elif hot_temp_c >= 100.0:
            offset_m += 5.0
        if cold_temp_c is not None and cold_temp_c <= 78.0:
            offset_m += 6.0

        tyre_damage_pct = float(getattr(state.player, "tyre_damage_pct", None) or 0.0)
        if tyre_damage_pct >= 40.0:
            offset_m += 14.0
        elif tyre_damage_pct >= 20.0:
            offset_m += 7.0

        aero_damage_pct = float(getattr(state.player, "aero_damage_pct", None) or 0.0)
        if aero_damage_pct >= 40.0:
            offset_m += 12.0
        elif aero_damage_pct >= 20.0:
            offset_m += 6.0

        fuel_laps_remaining = max(float(state.player.fuel_laps_remaining or 0.0), 0.0)
        if fuel_laps_remaining >= 25.0:
            offset_m += 8.0
        elif fuel_laps_remaining >= 15.0:
            offset_m += 4.0

        if speed_kph >= 300.0:
            offset_m += 4.0
        elif speed_kph <= 140.0:
            offset_m = max(0.0, offset_m - 4.0)
        return min(offset_m, 60.0)

    def _avg_numeric(self, values: list[Any]) -> float | None:
        numeric_values: list[float] = []
        for value in values:
            try:
                numeric_values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not numeric_values:
            return None
        return sum(numeric_values) / len(numeric_values)

    def _lap_distance_m(self, state: SessionState) -> float | None:
        player_lap_distance = getattr(state.player, "lap_distance_m", None)
        if player_lap_distance is not None:
            return float(player_lap_distance)
        raw_value = state.raw.get("lap_distance_m")
        try:
            return None if raw_value is None else float(raw_value)
        except (TypeError, ValueError):
            return None

    def _track_length_m(self, state: SessionState) -> float | None:
        raw_value = state.raw.get("track_length_m")
        try:
            return None if raw_value is None else float(raw_value)
        except (TypeError, ValueError):
            return None

    def _distance_ahead(
        self,
        *,
        lap_length_m: float,
        current_distance_m: float,
        target_distance_m: float,
    ) -> float:
        delta = float(target_distance_m) - float(current_distance_m)
        if delta < 0.0:
            delta += float(lap_length_m)
        return delta

    def _is_inside_target_zone(self, *, lap_distance_m: float, target: BrakePointAssistTarget) -> bool:
        return target.braking_zone_start_m <= lap_distance_m <= target.braking_zone_end_m + 10.0

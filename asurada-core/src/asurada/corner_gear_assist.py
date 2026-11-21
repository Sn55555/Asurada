from __future__ import annotations

from .paths import RUNTIME_ROOT

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import SessionState
from .track_model import CornerApex, TrackProfile, load_track_profile


_TRACK_CORNER_GEAR_MAP: dict[str, dict[str, int]] = {
    "shanghai": {
        "T1/T2": 4,
        "T3": 3,
        "T6": 2,
        "T7": 6,
        "T8": 4,
        "T9": 4,
        "T10": 4,
        "T11": 4,
        "T12": 4,
        "T13": 4,
        "T14": 2,
        "T16": 3,
    },
    "austria": {
        "T1 Apex": 4,
        "T3 Apex": 2,
        "T4 Apex": 4,
        "T6 Apex": 5,
        "T8 Flow Apex": 6,
        "T10 Apex": 3,
    },
    "suzuka": {
        "T1 First Curve": 6,
        "T2": 5,
        "T3": 4,
        "T4": 4,
        "T5 S Curve 1": 5,
        "T6 S Curve 2": 5,
        "T7 S Curve 3": 4,
        "T8": 3,
        "T9 Degner 1": 5,
        "T10 Degner 2": 4,
        "T11 Hairpin": 2,
        "T12": 6,
        "T13": 5,
        "T14 Spoon": 4,
        "T15 Spoon Exit": 5,
        "T16 130R": 7,
        "T17 Casio Triangle": 3,
    },
}


@dataclass(frozen=True)
class CornerGearAssistTarget:
    track: str
    corner_name: str
    apex_distance_m: float
    trigger_distance_m: float
    recommended_gear: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CornerGearAssistState:
    mode: str = "off"
    track: str | None = None
    lap_number: int | None = None
    announced_target_keys: list[str] = field(default_factory=list)
    last_target_name: str | None = None
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CornerGearAssistControlResult:
    enabled: bool
    speak_text: str
    reason: str


@dataclass(frozen=True)
class CornerGearAssistReminder:
    speak_text: str
    action_code: str
    target: CornerGearAssistTarget


class CornerGearAssistController:
    def __init__(self) -> None:
        self._state = CornerGearAssistState()
        self._state_path = self._resolve_state_path()
        self._load_state()

    def enable(self, *, state: SessionState) -> CornerGearAssistControlResult:
        self._load_state()
        profile = load_track_profile(state.track)
        if profile is None or not self._build_targets(profile):
            self._state = CornerGearAssistState(mode="off", last_reason="track_profile_unavailable")
            self._persist_state()
            return CornerGearAssistControlResult(
                enabled=False,
                speak_text="当前赛道还没有可用的入弯档位建议。",
                reason="track_profile_unavailable",
            )
        self._state = CornerGearAssistState(
            mode="on",
            track=state.track,
            lap_number=state.lap_number,
            announced_target_keys=[],
            last_reason="enabled",
        )
        self._persist_state()
        return CornerGearAssistControlResult(
            enabled=True,
            speak_text="收到。入弯档位语音建议已开启，我会在每个弯前提醒建议档位。",
            reason="enabled",
        )

    def disable(self) -> CornerGearAssistControlResult:
        self._load_state()
        self._state = CornerGearAssistState(mode="off", last_reason="disabled")
        self._persist_state()
        return CornerGearAssistControlResult(
            enabled=False,
            speak_text="已关闭入弯档位语音建议。",
            reason="disabled",
        )

    def status(self) -> CornerGearAssistControlResult:
        self._load_state()
        if self._state.mode != "on":
            return CornerGearAssistControlResult(
                enabled=False,
                speak_text="当前入弯档位语音建议是关闭的。",
                reason="off",
            )
        return CornerGearAssistControlResult(
            enabled=True,
            speak_text="入弯档位语音建议已开启。",
            reason="on",
        )

    def snapshot(self) -> dict[str, Any]:
        self._load_state()
        return self._state.to_dict()

    def maybe_build_reminder(self, *, state: SessionState) -> CornerGearAssistReminder | None:
        self._load_state()
        if self._state.mode != "on":
            return None
        profile = load_track_profile(state.track)
        if profile is None:
            return None
        lap_distance_m = self._lap_distance_m(state)
        if lap_distance_m is None:
            return None
        self._roll_state_for_lap(state=state)
        targets = self._build_targets(profile)
        if not targets:
            return None
        best: tuple[float, CornerGearAssistTarget] | None = None
        for target in targets:
            target_key = self._target_key(target=target, lap_number=state.lap_number)
            if target_key in self._state.announced_target_keys:
                continue
            distance_ahead = self._distance_ahead(
                lap_length_m=profile.lap_length_m,
                current_distance_m=lap_distance_m,
                target_distance_m=target.apex_distance_m,
            )
            if distance_ahead <= 0.0 or distance_ahead > target.trigger_distance_m:
                continue
            if best is None or distance_ahead < best[0]:
                best = (distance_ahead, target)
        if best is None:
            return None
        target = best[1]
        target_key = self._target_key(target=target, lap_number=state.lap_number)
        self._state.announced_target_keys.append(target_key)
        self._state.last_target_name = target.corner_name
        self._state.last_reason = "announced"
        self._persist_state()
        return CornerGearAssistReminder(
            speak_text=f"{target.corner_name}，{target.recommended_gear}档。",
            action_code=f"CORNER_GEAR_{target.corner_name.replace('/', '_').replace(' ', '_').upper()}",
            target=target,
        )

    def _resolve_state_path(self) -> Path:
        raw_value = os.getenv("ASURADA_CORNER_GEAR_ASSIST_STATE_PATH")
        if raw_value:
            return Path(raw_value).expanduser().resolve()
        return RUNTIME_ROOT / "corner_gear_assist_state.json"

    def _load_state(self) -> None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        self._state = CornerGearAssistState(
            mode=str(payload.get("mode") or "off"),
            track=(None if payload.get("track") is None else str(payload.get("track"))),
            lap_number=self._int_or_none(payload.get("lap_number")),
            announced_target_keys=[str(item) for item in (payload.get("announced_target_keys") or []) if item is not None],
            last_target_name=(None if payload.get("last_target_name") is None else str(payload.get("last_target_name"))),
            last_reason=(None if payload.get("last_reason") is None else str(payload.get("last_reason"))),
        )

    def _persist_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._state_path.parent,
            prefix=f"{self._state_path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(json.dumps(self._state.to_dict(), ensure_ascii=False))
            temp_path = Path(handle.name)
        temp_path.replace(self._state_path)

    def _roll_state_for_lap(self, *, state: SessionState) -> None:
        if self._state.track != state.track or self._state.lap_number != state.lap_number:
            self._state.track = state.track
            self._state.lap_number = state.lap_number
            self._state.announced_target_keys = []
            self._state.last_target_name = None
            self._state.last_reason = "lap_reset"
            self._persist_state()

    def _build_targets(self, profile: TrackProfile) -> list[CornerGearAssistTarget]:
        gear_map = _TRACK_CORNER_GEAR_MAP.get(profile.track.strip().lower(), {})
        targets: list[CornerGearAssistTarget] = []
        for apex in profile.corner_apexes:
            recommended_gear = apex.recommended_gear or gear_map.get(apex.name)
            if recommended_gear is None:
                continue
            targets.append(
                CornerGearAssistTarget(
                    track=profile.track,
                    corner_name=apex.name,
                    apex_distance_m=float(apex.distance_m),
                    trigger_distance_m=self._trigger_distance_m(apex=apex, recommended_gear=recommended_gear),
                    recommended_gear=recommended_gear,
                )
            )
        return targets

    def _trigger_distance_m(self, *, apex: CornerApex, recommended_gear: int) -> float:
        if recommended_gear <= 2:
            return 135.0
        if recommended_gear == 3:
            return 110.0
        if recommended_gear == 4:
            return 95.0
        if recommended_gear == 5:
            return 80.0
        return 65.0

    def _lap_distance_m(self, state: SessionState) -> float | None:
        try:
            player_lap_distance = getattr(state.player, "lap_distance_m", None)
            if player_lap_distance is not None:
                return float(player_lap_distance)
            raw_value = state.raw.get("lap_distance_m")
            return None if raw_value is None else float(raw_value)
        except (TypeError, ValueError):
            return None

    def _distance_ahead(self, *, lap_length_m: float, current_distance_m: float, target_distance_m: float) -> float:
        delta = float(target_distance_m) - float(current_distance_m)
        if delta < 0.0:
            delta += float(lap_length_m)
        return delta

    def _target_key(self, *, target: CornerGearAssistTarget, lap_number: int) -> str:
        return f"{lap_number}:{target.corner_name}"

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

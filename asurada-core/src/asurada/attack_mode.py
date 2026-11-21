from __future__ import annotations

from .paths import RUNTIME_ROOT

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .attack_taxonomy import attack_method_label
from .attack_opportunity import AttackOpportunities
from .models import SessionState


@dataclass
class AttackModeState:
    mode: str = "off"
    track: str | None = None
    lap_number: int | None = None
    announced_keys: list[str] = field(default_factory=list)
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttackModeControlResult:
    enabled: bool
    speak_text: str
    reason: str


@dataclass(frozen=True)
class AttackModeReminder:
    speak_text: str
    action_code: str
    reminder_type: str
    metadata: dict[str, Any]


class AttackModeController:
    def __init__(self) -> None:
        self._state = AttackModeState()
        self.opportunities = AttackOpportunities()
        self._state_path = self._resolve_state_path()
        self._load_state()

    def enable(self, *, state: SessionState) -> AttackModeControlResult:
        self._load_state()
        self._state = AttackModeState(
            mode="on",
            track=state.track,
            lap_number=state.lap_number,
            announced_keys=[],
            last_reason="enabled",
        )
        self._persist_state()
        return AttackModeControlResult(
            enabled=True,
            speak_text="收到。进攻模式已开启。我会在每个进攻机会开始前提示进攻方式和注意事项，当前不适合进攻时也会给出原因。",
            reason="enabled",
        )

    def disable(self) -> AttackModeControlResult:
        self._load_state()
        self._state = AttackModeState(mode="off", last_reason="disabled")
        self._persist_state()
        return AttackModeControlResult(
            enabled=False,
            speak_text="已关闭进攻模式。",
            reason="disabled",
        )

    def status(self) -> AttackModeControlResult:
        self._load_state()
        if self._state.mode != "on":
            return AttackModeControlResult(
                enabled=False,
                speak_text="当前进攻模式是关闭的。",
                reason="off",
            )
        return AttackModeControlResult(
            enabled=True,
            speak_text="进攻模式已开启。",
            reason="on",
        )

    def snapshot(self) -> dict[str, Any]:
        self._load_state()
        return self._state.to_dict()

    def manages_opportunities(self, *, automatic: bool, live_decision: bool) -> bool:
        return automatic or (live_decision and self._state.mode == "on")

    def on_started(self, job):
        self.opportunities.on_started(job)

    def on_completed(self, job):
        self.opportunities.on_completed(job)

    def maybe_build_reminder(
        self,
        *,
        state: SessionState,
        decision: Any,
    ) -> AttackModeReminder | None:
        self._load_state()
        if self._state.mode != "on" or state.raw.get("marshal_zone_flag") == 3:
            return None
        self._roll_state_for_lap(state=state)

        messages = list(getattr(decision, "messages", []) or [])
        primary_code = messages[0].code if messages else "NONE"
        context = dict((getattr(decision, "debug", {}) or {}).get("context", {}) or {})
        track_segment = str(context.get("track_segment") or "segment")
        track_usage = str(context.get("track_usage") or "general")
        setup_method = str(context.get("attack_setup_method") or "none")
        commit_method = str(context.get("attack_commit_method") or "none")
        gap_ahead = state.player.gap_ahead_s

        if primary_code == "ATTACK_WINDOW":
            method = commit_method if commit_method != "none" else setup_method
            key = self._key(
                lap_number=state.lap_number,
                track_segment=track_segment,
                reminder_type="attack",
                method=method,
            )
            if key in self._state.announced_keys:
                return None
            self._state.announced_keys.append(key)
            self._state.last_reason = "attack_reminder"
            self._persist_state()
            caution = self._attack_caution(method=method)
            return AttackModeReminder(
                speak_text=(
                    f"进攻模式。当前方式 {attack_method_label(method)}。"
                    f"{caution}"
                ),
                action_code="ATTACK_MODE_REMINDER",
                reminder_type="attack",
                metadata={
                    "track_segment": track_segment,
                    "track_usage": track_usage,
                    "attack_setup_method": setup_method,
                    "attack_commit_method": commit_method,
                },
            )

        should_explain_hold = (
            (gap_ahead is not None and gap_ahead <= 1.2)
            or setup_method != "none"
            or commit_method != "none"
        )
        if not should_explain_hold:
            return None

        key = self._key(
            lap_number=state.lap_number,
            track_segment=track_segment,
            reminder_type="hold",
            method=commit_method if commit_method != "none" else setup_method,
        )
        if key in self._state.announced_keys:
            return None
        reason = self._hold_reason(
            state=state,
            primary_code=primary_code,
            setup_method=setup_method,
            commit_method=commit_method,
        )
        self._state.announced_keys.append(key)
        self._state.last_reason = "hold_reminder"
        self._persist_state()
        return AttackModeReminder(
            speak_text=f"进攻模式。当前先不攻。{reason}",
            action_code="ATTACK_MODE_HOLD",
            reminder_type="hold",
            metadata={
                "track_segment": track_segment,
                "track_usage": track_usage,
                "attack_setup_method": setup_method,
                "attack_commit_method": commit_method,
            },
        )

    def _attack_caution(self, *, method: str) -> str:
        return {
            "drs_tow": "先贴住前车，别过早离开尾流，保留直道部署和重刹点位置。",
            "pressure_build": "先持续施压，不要提前把轮胎和电量消耗在低质量尝试上。",
            "inside_outbrake": "重点是内线重刹和受控制动，拿到位置后别把出口送掉。",
            "late_braking_lunge": "动作可以更晚，但必须收得住；一旦锁死或推头，立刻放弃。",
            "outside_carry": "守住外线速度，避免被逼到脏侧或出口收口区。",
            "switchback": "别抢 apex，优先要出口姿态和更早给油。",
            "traction_pass": "先把出弯牵引和直线初速做好，不要急着在弯心硬上。",
            "none": "先等更完整的兑现条件。",
        }.get(method or "none", "先等更完整的兑现条件。")

    def _hold_reason(
        self,
        *,
        state: SessionState,
        primary_code: str,
        setup_method: str,
        commit_method: str,
    ) -> str:
        if "unstable" in set(state.player.status_tags):
            return "当前车辆姿态还不够稳，强行上会把出口和后续节奏一起丢掉。"
        gap = state.player.gap_ahead_s
        if gap is None:
            return "前车时差当前不够可靠，先不做低把握度尝试。"
        if gap > 1.0:
            return f"前车差距还有 {gap:.1f} 秒，还没进入高质量进攻窗口。"
        if not state.player.drs_available and setup_method == "drs_tow":
            return "当前主要还是 DRS/尾流铺垫，但现在没有 DRS，兑现条件不够。"
        if commit_method == "none" and setup_method != "none":
            return f"当前更像 {attack_method_label(setup_method)} 的铺垫，还没到直接兑现窗口。"
        if primary_code == "DEFEND_WINDOW":
            return "后车压力更高，贸然进攻会把当前位置暴露出去。"
        if commit_method != "none":
            return f"当前最像 {attack_method_label(commit_method)}，但执行条件还没完整。"
        return "当前进攻收益还不够高，先把窗口继续铺出来。"

    def _key(self, *, lap_number: int, track_segment: str, reminder_type: str, method: str) -> str:
        return f"{lap_number}:{track_segment}:{reminder_type}:{method}"

    def _resolve_state_path(self) -> Path:
        raw_value = os.getenv("ASURADA_ATTACK_MODE_STATE_PATH")
        if raw_value:
            return Path(raw_value).expanduser().resolve()
        return RUNTIME_ROOT / "attack_mode_state.json"

    def _load_state(self) -> None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        self._state = AttackModeState(
            mode=str(payload.get("mode") or "off"),
            track=(None if payload.get("track") is None else str(payload.get("track"))),
            lap_number=self._int_or_none(payload.get("lap_number")),
            announced_keys=[str(item) for item in (payload.get("announced_keys") or []) if item is not None],
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
            self._state.announced_keys = []
            self._state.last_reason = "lap_reset"
            self._persist_state()

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

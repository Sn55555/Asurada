from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .arbiter import ModelCandidate
from .config import PROJECT_ROOT
from .models import ContextProfile, DriverState, SessionState

DEFAULT_STRATEGY_ACTION_REPORT = (
    PROJECT_ROOT / "training" / "reports" / "strategy_action_baseline" / "strategy_action_baseline_report.json"
)


@dataclass
class StrategyActionModelRuntime:
    """Optional runtime loader for the strategy-action baseline model."""

    report_path: Path = DEFAULT_STRATEGY_ACTION_REPORT

    def __post_init__(self) -> None:
        self._enabled = False
        self._disabled_reason: str | None = None
        self._report: dict[str, Any] | None = None
        self._booster: Any = None
        self._pd: Any = None
        self._feature_columns: list[str] = []
        self._target_actions: list[str] = []
        self._load()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def predict_top_k(self, *, state: SessionState, context: ContextProfile, k: int = 2) -> list[ModelCandidate]:
        """Predict top-k strategy-action candidates for the current state."""

        if not self._enabled or self._booster is None or self._pd is None:
            return []

        row = self._build_feature_row(state=state, context=context)
        frame = self._pd.DataFrame([row], columns=self._feature_columns)
        for column in self._numeric_columns():
            if column in frame.columns:
                frame[column] = self._pd.to_numeric(frame[column], errors="coerce")
        for column in self._categorical_columns():
            if column in frame.columns:
                frame[column] = frame[column].fillna("UNKNOWN").astype("category")

        proba = self._booster.predict(frame, num_iteration=self._best_iteration())
        if not len(proba):
            return []

        scores = list(proba[0])
        ranked = sorted(
            enumerate(scores),
            key=lambda item: item[1],
            reverse=True,
        )[: max(1, k)]
        return [
            ModelCandidate(
                code=self._target_actions[index],
                score=float(score),
                rank=rank + 1,
                source_model="strategy_action_model",
                title=self._title_for_code(self._target_actions[index]),
                detail=self._detail_for_code(self._target_actions[index], score),
            )
            for rank, (index, score) in enumerate(ranked)
        ]

    def _load(self) -> None:
        if not self.report_path.exists():
            self._disabled_reason = "missing_strategy_action_report"
            return

        try:
            import lightgbm as lgb  # type: ignore
            import pandas as pd  # type: ignore
        except ModuleNotFoundError as exc:
            self._disabled_reason = f"missing_dependency:{exc.name}"
            return

        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        model_path = Path(report.get("model_path") or "")
        if not model_path.exists():
            self._disabled_reason = "missing_strategy_action_model"
            return

        self._report = report
        self._feature_columns = list(report.get("feature_columns") or [])
        self._target_actions = list(report.get("target_actions") or [])
        self._pd = pd
        self._booster = lgb.Booster(model_file=str(model_path))
        self._enabled = True

    def _build_feature_row(self, *, state: SessionState, context: ContextProfile) -> dict[str, Any]:
        raw = state.raw
        front_rival = self._closest_rival(state.rivals, state.player.position - 1)
        rear_rival = self._closest_rival(state.rivals, state.player.position + 1)

        return {
            "lap_number": state.lap_number,
            "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
            "official_gap_behind_s": raw.get("official_gap_behind_s"),
            "speed_kph": state.player.speed_kph,
            "throttle": raw.get("throttle"),
            "brake": raw.get("brake"),
            "steer": raw.get("steer"),
            "fuel_laps_remaining": state.player.fuel_laps_remaining,
            "ers_pct": state.player.ers_pct,
            "tyre_wear_pct": state.player.tyre.wear_pct,
            "tyre_age_laps": state.player.tyre.age_laps,
            "recent_unstable_ratio": context.recent_unstable_ratio,
            "recent_front_overload_ratio": context.recent_front_overload_ratio,
            "g_force_lateral": raw.get("g_force_lateral"),
            "g_force_longitudinal": raw.get("g_force_longitudinal"),
            "front_rival_speed_delta": self._speed_delta(state.player.speed_kph, front_rival.speed_kph if front_rival else None),
            "rear_rival_speed_delta": self._speed_delta(rear_rival.speed_kph if rear_rival else None, state.player.speed_kph),
            "drs_available": int(state.player.drs_available),
            "timing_support_level": raw.get("timing_support_level") or "UNKNOWN",
            "session_type": raw.get("session_type") or "UNKNOWN",
            "track_segment": context.track_segment or "UNKNOWN",
            "track_usage": context.track_usage or "UNKNOWN",
            "driving_mode": context.driving_mode or "UNKNOWN",
        }

    def _categorical_columns(self) -> list[str]:
        return ["timing_support_level", "session_type", "track_segment", "track_usage", "driving_mode"]

    def _numeric_columns(self) -> list[str]:
        return [
            "lap_number",
            "official_gap_ahead_s",
            "official_gap_behind_s",
            "speed_kph",
            "throttle",
            "brake",
            "steer",
            "fuel_laps_remaining",
            "ers_pct",
            "tyre_wear_pct",
            "tyre_age_laps",
            "recent_unstable_ratio",
            "recent_front_overload_ratio",
            "g_force_lateral",
            "g_force_longitudinal",
            "front_rival_speed_delta",
            "rear_rival_speed_delta",
            "drs_available",
        ]

    def _best_iteration(self) -> int | None:
        if self._report is None:
            return None
        value = self._report.get("best_iteration")
        if value in (None, 0):
            return None
        return int(value)

    def _closest_rival(self, rivals: list[DriverState], target_position: int) -> DriverState | None:
        if target_position <= 0:
            return None
        for rival in rivals:
            if rival.position == target_position:
                return rival
        return None

    def _speed_delta(self, lhs: float | None, rhs: float | None) -> float | None:
        if lhs is None or rhs is None:
            return None
        return float(lhs) - float(rhs)

    def _title_for_code(self, code: str) -> str:
        return {
            "NONE": "保持当前策略",
            "LOW_FUEL": "燃油紧张",
            "DEFEND_WINDOW": "防守窗口",
            "DYNAMICS_UNSTABLE": "动态不稳",
        }.get(code, code)

    def _detail_for_code(self, code: str, score: float) -> str:
        return f"{code} 候选分数 {score:.3f}"

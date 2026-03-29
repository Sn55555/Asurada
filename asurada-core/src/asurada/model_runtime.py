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
DEFAULT_RESOURCE_RISK_REPORTS = {
    "fuel_risk": PROJECT_ROOT
    / "training"
    / "reports"
    / "resource_risk_baselines"
    / "fuel_risk"
    / "fuel_risk_baseline_report.json",
    "ers_risk": PROJECT_ROOT
    / "training"
    / "reports"
    / "resource_risk_baselines"
    / "ers_risk"
    / "ers_risk_baseline_report.json",
    "tyre_risk": PROJECT_ROOT
    / "training"
    / "reports"
    / "resource_risk_baselines"
    / "tyre_risk"
    / "tyre_risk_baseline_report.json",
    "dynamics_risk": PROJECT_ROOT
    / "training"
    / "reports"
    / "resource_risk_baselines"
    / "dynamics_risk"
    / "dynamics_risk_baseline_report.json",
}
DEFAULT_DEFENCE_COST_REPORT = (
    PROJECT_ROOT / "training" / "reports" / "defence_cost_baseline" / "defence_cost_baseline_report.json"
)
DEFAULT_RIVAL_PRESSURE_REPORTS = {
    "front_pressure": PROJECT_ROOT
    / "training"
    / "reports"
    / "rival_pressure_baseline"
    / "front_pressure"
    / "front_pressure_baseline_report.json",
    "rear_pressure": PROJECT_ROOT
    / "training"
    / "reports"
    / "rival_pressure_baseline"
    / "rear_pressure"
    / "rear_pressure_baseline_report.json",
    "rival_pressure": PROJECT_ROOT
    / "training"
    / "reports"
    / "rival_pressure_baseline"
    / "rival_pressure"
    / "rival_pressure_baseline_report.json",
}
DEFAULT_DRIVING_QUALITY_REPORTS = {
    "entry_quality": PROJECT_ROOT
    / "training"
    / "reports"
    / "driving_quality_baselines"
    / "entry_quality"
    / "entry_quality_baseline_report.json",
    "apex_quality": PROJECT_ROOT
    / "training"
    / "reports"
    / "driving_quality_baselines"
    / "apex_quality"
    / "apex_quality_baseline_report.json",
    "exit_traction": PROJECT_ROOT
    / "training"
    / "reports"
    / "driving_quality_baselines"
    / "exit_traction"
    / "exit_traction_baseline_report.json",
}
DEFAULT_TYRE_DEGRADATION_TREND_REPORTS = {
    "future_tyre_wear_delta": PROJECT_ROOT
    / "training"
    / "reports"
    / "tyre_degradation_trend_baseline"
    / "future_tyre_wear_delta"
    / "future_tyre_wear_delta_baseline_report.json",
    "future_grip_drop_score": PROJECT_ROOT
    / "training"
    / "reports"
    / "tyre_degradation_trend_baseline"
    / "future_grip_drop_score"
    / "future_grip_drop_score_baseline_report.json",
}


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
        self._class_min_score_thresholds: dict[str, float] = {}
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
        scores = self._apply_class_thresholds(scores)
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
        self._class_min_score_thresholds = {
            str(key): float(value)
            for key, value in (report.get("class_min_score_thresholds") or {}).items()
        }
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

    def _apply_class_thresholds(self, scores: list[float]) -> list[float]:
        if not self._class_min_score_thresholds:
            return scores
        calibrated = list(scores)
        for index, action in enumerate(self._target_actions):
            threshold = self._class_min_score_thresholds.get(action)
            if threshold is None:
                continue
            if float(calibrated[index]) < threshold:
                calibrated[index] = 0.0
        return calibrated


@dataclass
class ResourceRiskModelRuntime:
    """Optional runtime loader for a single LightGBM resource-risk regressor."""

    name: str
    report_path: Path

    def __post_init__(self) -> None:
        self._enabled = False
        self._disabled_reason: str | None = None
        self._report: dict[str, Any] | None = None
        self._booster: Any = None
        self._pd: Any = None
        self._feature_columns: list[str] = []
        self._load()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def predict_score(self, *, state: SessionState, context: ContextProfile) -> dict[str, Any]:
        if not self._enabled or self._booster is None or self._pd is None:
            return {
                "enabled": False,
                "model": self.name,
                "disabled_reason": self._disabled_reason,
            }

        row = build_runtime_feature_row(state=state, context=context)
        frame = self._pd.DataFrame([row], columns=self._feature_columns)
        for column in self._categorical_columns():
            if column in frame.columns:
                frame[column] = frame[column].fillna("UNKNOWN").astype("category")
        for column in self._numeric_columns():
            if column in frame.columns:
                frame[column] = self._pd.to_numeric(frame[column], errors="coerce")
        raw_score = float(self._booster.predict(frame, num_iteration=self._best_iteration())[0])
        score = max(0.0, min(100.0, raw_score))
        return {
            "enabled": True,
            "model": self.name,
            "score": score,
            "best_iteration": self._best_iteration(),
            "top_features": (self._report or {}).get("top_feature_importance", [])[:5],
        }

    def _load(self) -> None:
        if not self.report_path.exists():
            self._disabled_reason = f"missing_report:{self.name}"
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
            self._disabled_reason = f"missing_model:{self.name}"
            return

        self._report = report
        self._feature_columns = list(report.get("feature_columns") or [])
        self._pd = pd
        self._booster = lgb.Booster(model_file=str(model_path))
        self._enabled = True

    def _best_iteration(self) -> int | None:
        if self._report is None:
            return None
        value = self._report.get("best_iteration")
        if value in (None, 0):
            return None
        return int(value)

    def _categorical_columns(self) -> list[str]:
        known = {
            "session_type",
            "timing_mode",
            "timing_support_level",
            "track",
            "track_zone",
            "track_segment",
            "track_usage",
            "next_track_usage",
            "next_track_segment",
            "next_two_segments",
            "weather",
            "safety_car",
            "driving_mode",
            "fuel_laps_remaining_source",
            "ers_deploy_mode",
            "tyre_compound",
            "status_tags",
        }
        return [column for column in self._feature_columns if column in known]

    def _numeric_columns(self) -> list[str]:
        categorical = set(self._categorical_columns())
        return [column for column in self._feature_columns if column not in categorical]


@dataclass
class ResourceRiskRuntimeSet:
    """Convenience wrapper for all four resource/stability regressors."""

    report_paths: dict[str, Path] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_RESOURCE_RISK_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(name=name, report_path=path)
            for name, path in paths.items()
        }

    def predict_all(self, *, state: SessionState, context: ContextProfile) -> dict[str, dict[str, Any]]:
        return {
            name: runtime.predict_score(state=state, context=context)
            for name, runtime in self._runtimes.items()
        }


@dataclass
class RivalPressureRuntimeSet:
    """Convenience wrapper for front/rear/aggregate rival-pressure regressors."""

    report_paths: dict[str, Path] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_RIVAL_PRESSURE_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(name=name, report_path=path)
            for name, path in paths.items()
        }

    def predict_all(self, *, state: SessionState, context: ContextProfile) -> dict[str, dict[str, Any]]:
        return {
            name: runtime.predict_score(state=state, context=context)
            for name, runtime in self._runtimes.items()
        }


@dataclass
class DrivingQualityRuntimeSet:
    """Convenience wrapper for entry/apex/exit driving-quality regressors."""

    report_paths: dict[str, Path] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_DRIVING_QUALITY_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(name=name, report_path=path)
            for name, path in paths.items()
        }

    def predict_all(self, *, state: SessionState, context: ContextProfile) -> dict[str, dict[str, Any]]:
        return {
            name: runtime.predict_score(state=state, context=context)
            for name, runtime in self._runtimes.items()
        }


@dataclass
class TyreDegradationTrendRuntimeSet:
    """Convenience wrapper for tyre degradation trend regressors."""

    report_paths: dict[str, Path] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_TYRE_DEGRADATION_TREND_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(name=name, report_path=path)
            for name, path in paths.items()
        }

    def predict_all(self, *, state: SessionState, context: ContextProfile) -> dict[str, dict[str, Any]]:
        return {
            name: runtime.predict_score(state=state, context=context)
            for name, runtime in self._runtimes.items()
        }


def build_runtime_feature_row(*, state: SessionState, context: ContextProfile) -> dict[str, Any]:
    raw = state.raw
    front_rival = _closest_rival(state.rivals, state.player.position - 1)
    rear_rival = _closest_rival(state.rivals, state.player.position + 1)
    completed_laps = max(state.lap_number - 1, 0)
    remaining_race_laps = max(state.total_laps - completed_laps, 0)
    derived_fuel_laps_remaining = raw.get("derived_fuel_laps_remaining")
    fuel_margin_laps = (
        float(derived_fuel_laps_remaining) - remaining_race_laps
        if derived_fuel_laps_remaining is not None
        else None
    )
    return {
        "session_time_s": raw.get("session_time_s"),
        "lap_number": state.lap_number,
        "total_laps": state.total_laps,
        "player_position": state.player.position,
        "speed_kph": state.player.speed_kph,
        "throttle": raw.get("throttle"),
        "brake": raw.get("brake"),
        "steer": raw.get("steer"),
        "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
        "official_gap_behind_s": raw.get("official_gap_behind_s"),
        "fuel_in_tank": raw.get("fuel_in_tank"),
        "fuel_capacity": raw.get("fuel_capacity"),
        "fuel_laps_remaining": state.player.fuel_laps_remaining,
        "raw_fuel_laps_remaining": raw.get("raw_fuel_laps_remaining"),
        "derived_fuel_laps_remaining": raw.get("derived_fuel_laps_remaining"),
        "fuel_laps_remaining_source": raw.get("fuel_laps_remaining_source") or "UNKNOWN",
        "remaining_race_laps": remaining_race_laps,
        "fuel_margin_laps": fuel_margin_laps,
        "ers_store_energy": raw.get("ers_store_energy"),
        "ers_pct": state.player.ers_pct,
        "ers_deploy_mode": raw.get("ers_deploy_mode"),
        "drs_available": int(state.player.drs_available),
        "tyre_compound": state.player.tyre.compound,
        "tyre_wear_pct": state.player.tyre.wear_pct,
        "tyre_age_laps": state.player.tyre.age_laps,
        "status_tags": "|".join(state.player.status_tags),
        "g_force_lateral": raw.get("g_force_lateral"),
        "g_force_longitudinal": raw.get("g_force_longitudinal"),
        "g_force_vertical": raw.get("g_force_vertical"),
        "yaw": raw.get("yaw"),
        "pitch": raw.get("pitch"),
        "roll": raw.get("roll"),
        "wheel_slip_ratio_fl": _array_item(raw.get("wheel_slip_ratio"), 0),
        "wheel_slip_ratio_fr": _array_item(raw.get("wheel_slip_ratio"), 1),
        "wheel_slip_ratio_rl": _array_item(raw.get("wheel_slip_ratio"), 2),
        "wheel_slip_ratio_rr": _array_item(raw.get("wheel_slip_ratio"), 3),
        "track": state.track or "UNKNOWN",
        "track_zone": context.track_zone or "UNKNOWN",
        "track_segment": context.track_segment or "UNKNOWN",
        "track_usage": context.track_usage or "UNKNOWN",
        "next_track_usage": context.track_usage or "UNKNOWN",
        "next_track_segment": context.track_segment or "UNKNOWN",
        "weather": state.weather or "UNKNOWN",
        "safety_car": state.safety_car or "UNKNOWN",
        "driving_mode": context.driving_mode or "UNKNOWN",
        "timing_mode": raw.get("timing_mode") or "UNKNOWN",
        "session_type": raw.get("session_type") or "UNKNOWN",
        "recent_unstable_ratio": context.recent_unstable_ratio,
        "recent_front_overload_ratio": context.recent_front_overload_ratio,
        "tyre_age_factor": context.tyre_age_factor,
        "front_rival_ers_pct": front_rival.ers_pct if front_rival else None,
        "front_rival_speed_kph": front_rival.speed_kph if front_rival else None,
        "rear_rival_ers_pct": rear_rival.ers_pct if rear_rival else None,
        "rear_rival_speed_kph": rear_rival.speed_kph if rear_rival else None,
        "front_rival_speed_delta": _speed_delta(state.player.speed_kph, front_rival.speed_kph if front_rival else None),
        "rear_rival_speed_delta": _speed_delta(rear_rival.speed_kph if rear_rival else None, state.player.speed_kph),
    }


def _closest_rival(rivals: list[DriverState], target_position: int) -> DriverState | None:
    if target_position <= 0:
        return None
    for rival in rivals:
        if rival.position == target_position:
            return rival
    return None


def _speed_delta(lhs: float | None, rhs: float | None) -> float | None:
    if lhs is None or rhs is None:
        return None
    return float(lhs) - float(rhs)


def _array_item(values: Any, index: int) -> float | None:
    if not isinstance(values, list):
        return None
    if index >= len(values):
        return None
    value = values[index]
    return float(value) if value is not None else None

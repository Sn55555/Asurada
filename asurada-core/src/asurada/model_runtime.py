from __future__ import annotations

from .model_assets import read_model_asset
from .model_input_quality import prepare_model_inputs

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .arbiter import ModelCandidate
from .config import PROJECT_ROOT
from .model_admission import validate_mode
from .models import ContextProfile, DriverState, SessionState
from .wheel_telemetry import WHEEL_ORDER_VERSION, wheel_value


class RuntimeFeatureEncoder:
    """Encode one row using the model's saved categorical vocabulary."""

    def __init__(self, pd, booster, columns, numeric, categorical):
        self.pd = pd
        self.columns = list(columns)
        self.numeric = set(numeric)
        self.categorical = set(categorical)
        ordered_categories = [name for name in columns if name in self.categorical]
        vocabulary = booster.pandas_categorical
        self.fast = (
            vocabulary is not None and len(vocabulary) == len(ordered_categories)
            and set(columns) <= self.numeric | self.categorical
            and not self.numeric & self.categorical
        )
        self.codes = {
            name: {value: index for index, value in enumerate(values)}
            for name, values in zip(ordered_categories, vocabulary or [])
        }

    def legacy_frame(self, row):
        frame = self.pd.DataFrame([row], columns=self.columns)
        for name in self.columns:
            if name in self.numeric:
                frame[name] = self.pd.to_numeric(frame[name], errors="coerce")
            elif name in self.categorical:
                frame[name] = frame[name].fillna("UNKNOWN").astype("category")
        return frame

    def encode(self, row):
        if not self.fast:
            return self.legacy_frame(row)
        import numpy as np

        values = []
        for name in self.columns:
            value = row.get(name)
            if name in self.categorical:
                value = "UNKNOWN" if self.pd.isna(value) else value
                value = self.codes[name].get(value, np.nan)
            values.append(value)
        # Preserve coercion of numeric strings and missing values without a DataFrame.
        return np.asarray(self.pd.to_numeric(values, errors="coerce"), dtype=np.float64).reshape(1, -1)

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
    mode: str = "observe"

    def __post_init__(self) -> None:
        self._enabled = False
        self._disabled_reason: str | None = None
        self._report: dict[str, Any] | None = None
        self._booster: Any = None
        self._pd: Any = None
        self._feature_columns: list[str] = []
        self._target_actions: list[str] = []
        self._class_min_score_thresholds: dict[str, float] = {}
        self.last_input_quality = None
        self.last_output_quality = {'valid': None, 'reason': 'not_run'}
        self._load()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def predict_top_k(self, *, state: SessionState, context: ContextProfile, k: int = 2) -> list[ModelCandidate]:
        """Predict top-k strategy-action candidates for the current state."""

        self.last_input_quality = None
        self.last_output_quality = {'valid': None, 'reason': 'not_run'}
        if not self._enabled or self._booster is None or self._pd is None:
            self.last_output_quality['reason'] = self._disabled_reason or 'model_unavailable'
            return []

        row = self._build_feature_row(state=state, context=context)
        row, self.last_input_quality = prepare_model_inputs(row, self._feature_columns)
        if self.last_input_quality['absent_columns']:
            self.last_output_quality['reason'] = 'feature_columns_not_generated'
            return []
        if self.mode == 'active' and self.last_input_quality['unavailable_features']:
            self.last_output_quality['reason'] = 'required_physical_input_unavailable'
            return []
        frame = self._encoder.encode(row)
        from .model_output_quality import probability_row
        try:
            proba = self._booster.predict(frame, num_iteration=self._best_iteration(), num_threads=1)
            scores = probability_row(proba, len(self._target_actions))
        except Exception as exc:
            self.last_output_quality = {'valid': False, 'reason': 'invalid_model_output', 'error_type': type(exc).__name__}
            return []
        self.last_output_quality = {'valid': True}
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
        validate_mode(self.mode)
        try:
            self._load_assets()
        except Exception as exc:
            self._enabled = False
            self._booster = None
            self._disabled_reason = f"asset_load_failed:{type(exc).__name__}:{exc}"

    def _load_assets(self) -> None:
        validate_mode(self.mode)
        if self.mode == "disabled":
            self._disabled_reason = "admission_disabled"
            return
        if not self.report_path.exists():
            self._disabled_reason = "missing_strategy_action_report"
            return

        try:
            import lightgbm as lgb  # type: ignore
            import pandas as pd  # type: ignore
        except ModuleNotFoundError as exc:
            self._disabled_reason = f"missing_dependency:{exc.name}"
            return

        report, model_path = read_model_asset(self.report_path, require_manifest=True)
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
        if self._booster.feature_name() != self._feature_columns:
            raise ValueError("booster_feature_order_mismatch")
        self._encoder = RuntimeFeatureEncoder(pd, self._booster, self._feature_columns, self._numeric_columns(), self._categorical_columns())
        self._enabled = True

    def _build_feature_row(self, *, state: SessionState, context: ContextProfile) -> dict[str, Any]:
        raw = state.raw
        front_rival = self._closest_rival(state.rivals, state.player.position - 1)
        rear_rival = self._closest_rival(state.rivals, state.player.position + 1)

        return {
            "lap_number": state.lap_number,
            "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
            "official_gap_behind_s": raw.get("official_gap_behind_s"),
            "front_rival_gap_confidence": front_rival.gap_confidence if front_rival else None,
            "rear_rival_gap_confidence": rear_rival.gap_confidence if rear_rival else None,
            "front_rival_pit_status": front_rival.pit_status if front_rival else None,
            "rear_rival_pit_status": rear_rival.pit_status if rear_rival else None,
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
            "front_rival_engine_damage_pct": front_rival.engine_damage_pct if front_rival else None,
            "rear_rival_engine_damage_pct": rear_rival.engine_damage_pct if rear_rival else None,
            "front_rival_aero_damage_pct": front_rival.aero_damage_pct if front_rival else None,
            "rear_rival_aero_damage_pct": rear_rival.aero_damage_pct if rear_rival else None,
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
        return [
            "timing_support_level",
            "session_type",
            "track_segment",
            "track_usage",
            "driving_mode",
            "front_rival_gap_confidence",
            "rear_rival_gap_confidence",
            "front_rival_pit_status",
            "rear_rival_pit_status",
        ]

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
            "front_rival_engine_damage_pct",
            "rear_rival_engine_damage_pct",
            "front_rival_aero_damage_pct",
            "rear_rival_aero_damage_pct",
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
    mode: str = "observe"

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
                "admission_mode": self.mode,
            }

        row = build_runtime_feature_row(state=state, context=context)
        provenance = (self._report or {}).get("training_provenance") or {}
        if provenance.get("wheel_order_version") != WHEEL_ORDER_VERSION:
            # Existing weights were fitted to the reversed axle names in older exports.
            for front, rear in (("wheel_slip_ratio_fl", "wheel_slip_ratio_rl"),
                                ("wheel_slip_ratio_fr", "wheel_slip_ratio_rr")):
                row[front], row[rear] = row[rear], row[front]
        row, quality = prepare_model_inputs(row, self._feature_columns)
        if quality['absent_columns']:
            return {'enabled': False, 'model': self.name, 'admission_mode': self.mode,
                    'disabled_reason': 'feature_columns_not_generated', 'input_quality': quality}
        if self.mode == 'active' and quality['unavailable_features']:
            return {'enabled': False, 'model': self.name, 'admission_mode': self.mode,
                    'disabled_reason': 'required_physical_input_unavailable', 'input_quality': quality}
        frame = self._encoder.encode(row)
        from .model_output_quality import regression_score
        try:
            raw_score = regression_score(self._booster.predict(frame, num_iteration=self._best_iteration(), num_threads=1))
        except Exception as exc:
            return {'enabled': False, 'model': self.name, 'admission_mode': self.mode,
                    'disabled_reason': 'invalid_model_output', 'error_type': type(exc).__name__, 'input_quality': quality}
        score = max(0.0, min(100.0, raw_score))
        return {
            "enabled": True,
            "model": self.name,
            "score": score,
            "input_quality": quality,
            "admission_mode": self.mode,
            "best_iteration": self._best_iteration(),
            "top_features": (self._report or {}).get("top_feature_importance", [])[:5],
        }

    def _load(self) -> None:
        validate_mode(self.mode)
        try:
            self._load_assets()
        except Exception as exc:
            self._enabled = False
            self._booster = None
            self._disabled_reason = f"asset_load_failed:{type(exc).__name__}:{exc}"

    def _load_assets(self) -> None:
        validate_mode(self.mode)
        if self.mode == "disabled":
            self._disabled_reason = "admission_disabled"
            return
        if not self.report_path.exists():
            self._disabled_reason = f"missing_report:{self.name}"
            return
        try:
            import lightgbm as lgb  # type: ignore
            import pandas as pd  # type: ignore
        except ModuleNotFoundError as exc:
            self._disabled_reason = f"missing_dependency:{exc.name}"
            return

        report, model_path = read_model_asset(self.report_path, require_manifest=True)
        if not model_path.exists():
            self._disabled_reason = f"missing_model:{self.name}"
            return

        self._report = report
        self._feature_columns = list(report.get("feature_columns") or [])
        self._pd = pd
        self._booster = lgb.Booster(model_file=str(model_path))
        if self._booster.feature_name() != self._feature_columns:
            raise ValueError("booster_feature_order_mismatch")
        self._encoder = RuntimeFeatureEncoder(pd, self._booster, self._feature_columns, self._numeric_columns(), self._categorical_columns())
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
    modes: dict[str, str] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_RESOURCE_RISK_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(
                name=name, report_path=path, mode=(self.modes or {}).get(name, "observe")
            )
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
    modes: dict[str, str] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_RIVAL_PRESSURE_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(
                name=name, report_path=path, mode=(self.modes or {}).get(name, "observe")
            )
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
    modes: dict[str, str] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_DRIVING_QUALITY_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(
                name=name, report_path=path, mode=(self.modes or {}).get(name, "observe")
            )
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
    modes: dict[str, str] | None = None

    def __post_init__(self) -> None:
        paths = self.report_paths or DEFAULT_TYRE_DEGRADATION_TREND_REPORTS
        self._runtimes = {
            name: ResourceRiskModelRuntime(
                name=name, report_path=path, mode=(self.modes or {}).get(name, "observe")
            )
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
        "gap_closing_rate_behind": context.gap_closing_rate_behind,
        "next_two_segments": context.next_two_segments,
        "brake_phase_factor": context.brake_phase_factor,
        "throttle_phase_factor": context.throttle_phase_factor,
        "steering_phase_factor": context.steering_phase_factor,
        "timing_support_level": raw.get("timing_support_level") or "UNKNOWN",
        "lap_number": state.lap_number,
        "total_laps": state.total_laps,
        "player_position": state.player.position,
        "speed_kph": state.player.speed_kph,
        "throttle": raw.get("throttle"),
        "brake": raw.get("brake"),
        "steer": raw.get("steer"),
        "official_gap_ahead_s": raw.get("official_gap_ahead_s"),
        "official_gap_behind_s": raw.get("official_gap_behind_s"),
        "front_rival_gap_confidence": front_rival.gap_confidence if front_rival else None,
        "rear_rival_gap_confidence": rear_rival.gap_confidence if rear_rival else None,
        "front_rival_pit_status": front_rival.pit_status if front_rival else None,
        "rear_rival_pit_status": rear_rival.pit_status if rear_rival else None,
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
        "wheel_slip_ratio_fl": wheel_value(raw.get("wheel_slip_ratio"), "fl"),
        "wheel_slip_ratio_fr": wheel_value(raw.get("wheel_slip_ratio"), "fr"),
        "wheel_slip_ratio_rl": wheel_value(raw.get("wheel_slip_ratio"), "rl"),
        "wheel_slip_ratio_rr": wheel_value(raw.get("wheel_slip_ratio"), "rr"),
        "track": state.track or "UNKNOWN",
        "track_zone": context.track_zone or "UNKNOWN",
        "track_segment": context.track_segment or "UNKNOWN",
        "track_usage": context.track_usage or "UNKNOWN",
        "next_track_usage": context.next_track_usage or "UNKNOWN",
        "next_track_segment": context.next_track_segment or "UNKNOWN",
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
        "front_rival_engine_damage_pct": front_rival.engine_damage_pct if front_rival else None,
        "front_rival_aero_damage_pct": front_rival.aero_damage_pct if front_rival else None,
        "rear_rival_ers_pct": rear_rival.ers_pct if rear_rival else None,
        "rear_rival_speed_kph": rear_rival.speed_kph if rear_rival else None,
        "rear_rival_engine_damage_pct": rear_rival.engine_damage_pct if rear_rival else None,
        "rear_rival_aero_damage_pct": rear_rival.aero_damage_pct if rear_rival else None,
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

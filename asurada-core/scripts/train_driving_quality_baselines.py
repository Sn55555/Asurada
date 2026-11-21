from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from asurada.training_partition import session_partitions
from asurada.training_provenance import training_provenance
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "driving_quality_baselines"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    target: str
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


MODEL_SPECS: dict[str, ModelSpec] = {
    "entry_quality": ModelSpec(
        name="entry_quality",
        target="entry_quality_label",
        numeric_features=(
            "speed_kph",
            "brake",
            "steer",
            "g_force_longitudinal",
            "g_force_lateral",
            "wheel_slip_ratio_fl",
            "wheel_slip_ratio_fr",
            "recent_front_overload_ratio",
            "recent_unstable_ratio",
            "brake_phase_factor",
        ),
        categorical_features=(
            "session_type",
            "track_segment",
            "track_usage",
            "track_zone",
            "driving_mode",
            "status_tags",
        ),
    ),
    "apex_quality": ModelSpec(
        name="apex_quality",
        target="apex_quality_label",
        numeric_features=(
            "speed_kph",
            "steer",
            "g_force_lateral",
            "yaw",
            "roll",
            "wheel_slip_ratio_fl",
            "wheel_slip_ratio_fr",
            "recent_front_overload_ratio",
            "recent_unstable_ratio",
            "steering_phase_factor",
        ),
        categorical_features=(
            "session_type",
            "track_segment",
            "track_usage",
            "track_zone",
            "driving_mode",
            "status_tags",
        ),
    ),
    "exit_traction": ModelSpec(
        name="exit_traction",
        target="exit_traction_label",
        numeric_features=(
            "speed_kph",
            "throttle",
            "steer",
            "g_force_longitudinal",
            "wheel_slip_ratio_rl",
            "wheel_slip_ratio_rr",
            "tyre_wear_pct",
            "recent_unstable_ratio",
            "throttle_phase_factor",
        ),
        categorical_features=(
            "session_type",
            "track_segment",
            "track_usage",
            "next_track_segment",
            "next_track_usage",
            "driving_mode",
            "status_tags",
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train baseline regressors for driving-quality models.")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="Path to features.csv.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for reports and model artifacts.")
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_SPECS.keys()),
        default=sorted(MODEL_SPECS.keys()),
        help="Subset of driving-quality models to train.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas`, `lightgbm`, and `scikit-learn` in /Users/sn5/Asurada/asurada-core/.venv before training."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    provenance = training_provenance(args.features)
    features_df = pd.read_csv(args.features, low_memory=False, dtype={"session_uid": "string"})
    features_df = features_df[features_df["timing_support_level"] == "official_preferred"].copy()
    if features_df.empty:
        raise SystemExit("No official-preferred rows available for driving-quality training.")

    features_df["entry_quality_label"] = features_df.apply(derive_entry_quality_label, axis=1)
    features_df["apex_quality_label"] = features_df.apply(derive_apex_quality_label, axis=1)
    features_df["exit_traction_label"] = features_df.apply(derive_exit_traction_label, axis=1)

    aggregate: dict[str, object] = {
        "features": str(args.features),
        "filter": "timing_support_level == official_preferred",
        "labeling": "proxy_distillation_from_features",
        "models": {},
    }

    for model_name in args.models:
        spec = MODEL_SPECS[model_name]
        summary = train_one_model(
            df=features_df.copy(),
            spec=spec,
            output_dir=args.output_dir / model_name,
            lgb=lgb,
            mean_absolute_error=mean_absolute_error,
            mean_squared_error=mean_squared_error,
            r2_score=r2_score,
            provenance=provenance,
        )
        aggregate["models"][model_name] = summary

    aggregate_path = args.output_dir / "driving_quality_baselines_report.json"
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


def train_one_model(
    *,
    df,
    spec: ModelSpec,
    output_dir: Path,
    lgb,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    provenance=None,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    for column in spec.numeric_features:
        if column in df.columns:
            df[column] = df[column].apply(optional_float)
    for column in spec.categorical_features:
        df[column] = df[column].fillna("UNKNOWN").astype("category")

    model_columns = list(spec.numeric_features + spec.categorical_features)
    data = df[model_columns + [spec.target, "split", "session_uid"]].dropna(subset=[spec.target]).copy()
    train_df, val_df, test_df, partition_manifest = session_partitions(data)

    X_train = train_df[model_columns]
    y_train = train_df[spec.target].astype(float)
    X_val = val_df[model_columns]
    y_val = val_df[spec.target].astype(float)
    X_test = test_df[model_columns]
    y_test = test_df[spec.target].astype(float)

    estimator = lgb.LGBMRegressor(
        objective="regression",
        learning_rate=0.05,
        n_estimators=400,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
    )
    estimator.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        eval_metric="l2",
        categorical_feature=[column for column in spec.categorical_features if column in X_train.columns],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    predictions = estimator.predict(X_test)
    mae = float(mean_absolute_error(y_test, predictions))
    rmse = float(math.sqrt(mean_squared_error(y_test, predictions)))
    r2 = float(r2_score(y_test, predictions))

    importances = sorted(
        (
            {"feature": feature, "importance": float(importance)}
            for feature, importance in zip(model_columns, estimator.feature_importances_)
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    model_path = output_dir / f"{spec.name}_baseline.txt"
    estimator.booster_.save_model(str(model_path))

    summary = {
        "model_name": spec.name,
        "target": spec.target,
        "training_provenance": provenance or {"export_metadata_status": "not_provided"},
        "context_window_version": (provenance or {}).get("context_window_version"),
        "label_provenance": {"kind": "proxy_derived_from_features", "human_validated": False},
        "feature_columns": model_columns,
        "categorical_features": list(spec.categorical_features),
        "train_rows": int(len(X_train)),
        "val_rows": int(len(X_val)),
        "test_rows": int(len(X_test)),
        "validation_source": "session_disjoint_validation",
        "test_source": "session_disjoint_exported_test",
        "partition_manifest": partition_manifest,
        "best_iteration": int(estimator.best_iteration_ or 0),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "labeling": "proxy_distillation_from_features",
        "top_feature_importance": importances[:10],
        "model_path": model_path.name,
    }
    report_path = output_dir / f"{spec.name}_baseline_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def derive_entry_quality_label(row) -> float:
    brake = optional_float(row.get("brake"))
    steer = abs(optional_float(row.get("steer")))
    g_long = abs(optional_float(row.get("g_force_longitudinal")))
    front_slip = mean_pair(row.get("wheel_slip_ratio_fl"), row.get("wheel_slip_ratio_fr"))
    overload = optional_float(row.get("recent_front_overload_ratio"))
    unstable = optional_float(row.get("recent_unstable_ratio"))
    usage = str(row.get("track_usage") or "")

    score = 75.0
    score += 8.0 if "brak" in usage.lower() else 0.0
    score += clamp(brake * 18.0, 0.0, 18.0)
    score -= clamp(abs(brake - 0.45) * 30.0, 0.0, 15.0)
    score -= clamp(steer * 20.0, 0.0, 16.0)
    score -= clamp(front_slip * 30.0, 0.0, 18.0)
    score -= clamp(overload * 24.0, 0.0, 16.0)
    score -= clamp(unstable * 30.0, 0.0, 18.0)
    score += clamp((g_long - 0.4) * 6.0, 0.0, 8.0)
    return round(clamp(score, 0.0, 100.0), 4)


def derive_apex_quality_label(row) -> float:
    steer = abs(optional_float(row.get("steer")))
    g_lat = abs(optional_float(row.get("g_force_lateral")))
    yaw = abs(optional_float(row.get("yaw")))
    roll = abs(optional_float(row.get("roll")))
    front_slip = mean_pair(row.get("wheel_slip_ratio_fl"), row.get("wheel_slip_ratio_fr"))
    overload = optional_float(row.get("recent_front_overload_ratio"))
    unstable = optional_float(row.get("recent_unstable_ratio"))

    score = 72.0
    score += clamp(g_lat * 5.0, 0.0, 12.0)
    score -= clamp(steer * 16.0, 0.0, 14.0)
    score -= clamp(yaw * 10.0, 0.0, 16.0)
    score -= clamp(roll * 10.0, 0.0, 14.0)
    score -= clamp(front_slip * 26.0, 0.0, 18.0)
    score -= clamp(overload * 18.0, 0.0, 12.0)
    score -= clamp(unstable * 28.0, 0.0, 18.0)
    return round(clamp(score, 0.0, 100.0), 4)


def derive_exit_traction_label(row) -> float:
    throttle = optional_float(row.get("throttle"))
    steer = abs(optional_float(row.get("steer")))
    speed = optional_float(row.get("speed_kph"))
    rear_slip = mean_pair(row.get("wheel_slip_ratio_rl"), row.get("wheel_slip_ratio_rr"))
    unstable = optional_float(row.get("recent_unstable_ratio"))
    tyre_wear = optional_float(row.get("tyre_wear_pct"))
    usage = str(row.get("track_usage") or "")

    score = 70.0
    score += 8.0 if "traction" in usage.lower() or "exit" in usage.lower() else 0.0
    score += clamp(throttle * 20.0, 0.0, 20.0)
    score += clamp(speed / 25.0, 0.0, 10.0)
    score -= clamp(steer * 18.0, 0.0, 14.0)
    score -= clamp(rear_slip * 34.0, 0.0, 22.0)
    score -= clamp(unstable * 28.0, 0.0, 18.0)
    score -= clamp((tyre_wear / 100.0) * 12.0, 0.0, 12.0)
    return round(clamp(score, 0.0, 100.0), 4)


def mean_pair(a, b) -> float:
    vals = [optional_float(a), optional_float(b)]
    return sum(vals) / len(vals)


def optional_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


if __name__ == "__main__":
    raise SystemExit(main())

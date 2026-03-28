from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_LABELS = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "labels.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "resource_risk_baselines"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    target: str
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


MODEL_SPECS: dict[str, ModelSpec] = {
    "fuel_risk": ModelSpec(
        name="fuel_risk",
        target="fuel_risk_label",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "total_laps",
            "speed_kph",
            "throttle",
            "brake",
            "fuel_in_tank",
            "fuel_capacity",
            "fuel_laps_remaining",
            "raw_fuel_laps_remaining",
            "derived_fuel_laps_remaining",
            "remaining_race_laps",
            "fuel_margin_laps",
            "ers_pct",
            "tyre_wear_pct",
            "tyre_age_laps",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "track",
            "track_usage",
            "weather",
            "safety_car",
            "driving_mode",
            "fuel_laps_remaining_source",
        ),
    ),
    "ers_risk": ModelSpec(
        name="ers_risk",
        target="ers_risk_label",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "total_laps",
            "speed_kph",
            "throttle",
            "brake",
            "official_gap_ahead_s",
            "official_gap_behind_s",
            "ers_store_energy",
            "ers_pct",
            "drs_available",
            "front_rival_ers_pct",
            "rear_rival_ers_pct",
            "front_rival_speed_delta",
            "rear_rival_speed_delta",
            "fuel_laps_remaining",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "track_usage",
            "next_track_usage",
            "ers_deploy_mode",
            "safety_car",
            "driving_mode",
        ),
    ),
    "tyre_risk": ModelSpec(
        name="tyre_risk",
        target="tyre_risk_label",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "total_laps",
            "speed_kph",
            "throttle",
            "brake",
            "steer",
            "tyre_wear_pct",
            "tyre_age_laps",
            "tyre_age_factor",
            "g_force_lateral",
            "g_force_longitudinal",
            "wheel_slip_ratio_fl",
            "wheel_slip_ratio_fr",
            "wheel_slip_ratio_rl",
            "wheel_slip_ratio_rr",
            "recent_front_overload_ratio",
            "recent_unstable_ratio",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "track_segment",
            "track_usage",
            "next_track_segment",
            "tyre_compound",
            "driving_mode",
        ),
    ),
    "dynamics_risk": ModelSpec(
        name="dynamics_risk",
        target="dynamics_risk_label",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "speed_kph",
            "throttle",
            "brake",
            "steer",
            "g_force_lateral",
            "g_force_longitudinal",
            "g_force_vertical",
            "yaw",
            "pitch",
            "roll",
            "wheel_slip_ratio_fl",
            "wheel_slip_ratio_fr",
            "wheel_slip_ratio_rl",
            "wheel_slip_ratio_rr",
            "recent_unstable_ratio",
            "recent_front_overload_ratio",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "track_zone",
            "track_segment",
            "track_usage",
            "status_tags",
            "driving_mode",
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train baseline regressors for stage-two resource risk models.")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="Path to features.csv.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Path to labels.csv.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for reports and model artifacts.")
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_SPECS.keys()),
        default=sorted(MODEL_SPECS.keys()),
        help="Subset of resource models to train.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # type: ignore
        from sklearn.model_selection import train_test_split  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas`, `lightgbm`, and `scikit-learn` in /Users/sn5/Asurada/asurada-core/.venv before training."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    features_df = pd.read_csv(args.features, low_memory=False)
    labels_df = pd.read_csv(args.labels, low_memory=False)
    merged = features_df.merge(
        labels_df[
            [
                "record_id",
                "fuel_risk_label",
                "ers_risk_label",
                "tyre_risk_label",
                "dynamics_risk_label",
            ]
        ],
        on="record_id",
        how="inner",
    )

    # 第一轮资源模型只使用官方可用 session，避免 estimated_only 干扰。
    merged = merged[merged["timing_support_level"] == "official_preferred"].copy()
    if merged.empty:
        raise SystemExit("No official-preferred rows available for resource-risk training.")

    aggregate: dict[str, object] = {
        "features": str(args.features),
        "labels": str(args.labels),
        "filter": "timing_support_level == official_preferred",
        "models": {},
    }

    for model_name in args.models:
        spec = MODEL_SPECS[model_name]
        summary = train_one_model(
            merged_df=merged.copy(),
            spec=spec,
            output_dir=args.output_dir / model_name,
            lgb=lgb,
            mean_absolute_error=mean_absolute_error,
            mean_squared_error=mean_squared_error,
            r2_score=r2_score,
            train_test_split=train_test_split,
        )
        aggregate["models"][model_name] = summary

    aggregate_path = args.output_dir / "resource_risk_baselines_report.json"
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


def train_one_model(
    *,
    merged_df,
    spec: ModelSpec,
    output_dir: Path,
    lgb,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    train_test_split,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    df = merged_df[merged_df[spec.target].notna()].copy()
    if df.empty:
        raise SystemExit(f"No rows available for {spec.name} after target filtering.")

    for column in spec.numeric_features:
        if column in df.columns:
            df[column] = df[column].astype(float)
    for column in spec.categorical_features:
        df[column] = df[column].fillna("UNKNOWN").astype("category")

    train_df = df[df["split"] == "train"].copy()
    test_df = df[df["split"] == "test"].copy()
    if train_df.empty or test_df.empty:
        raise SystemExit(f"Missing exported train/test rows for {spec.name}.")

    stratify_values = build_regression_stratify_labels(train_df[spec.target].tolist())
    train_df, val_df = train_test_split(
        train_df,
        test_size=0.2,
        random_state=42,
        stratify=stratify_values,
    )

    feature_columns = list(spec.numeric_features + spec.categorical_features)
    train_set = lgb.Dataset(
        train_df[feature_columns],
        label=train_df[spec.target],
        categorical_feature=list(spec.categorical_features),
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        val_df[feature_columns],
        label=val_df[spec.target],
        categorical_feature=list(spec.categorical_features),
        free_raw_data=False,
    )

    params = {
        "objective": "regression",
        "metric": ["l1", "l2"],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "min_data_in_leaf": 20,
        "verbosity": -1,
        "seed": 42,
    }

    booster = lgb.train(
        params=params,
        train_set=train_set,
        num_boost_round=300,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(30)],
    )

    best_iteration = booster.best_iteration or 300
    predictions = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    truth = test_df[spec.target].to_numpy()

    mae = float(mean_absolute_error(truth, predictions))
    rmse = float(math.sqrt(mean_squared_error(truth, predictions)))
    r2 = float(r2_score(truth, predictions))
    spearman = safe_spearman(truth.tolist(), predictions.tolist())
    within_5 = float(sum(1 for t, p in zip(truth, predictions) if abs(float(t) - float(p)) <= 5.0) / len(truth))
    within_10 = float(sum(1 for t, p in zip(truth, predictions) if abs(float(t) - float(p)) <= 10.0) / len(truth))

    importance = sorted(
        (
            {"feature": name, "importance": int(value)}
            for name, value in zip(feature_columns, booster.feature_importance(importance_type="gain"))
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    model_path = output_dir / f"{spec.name}_baseline.txt"
    summary_path = output_dir / f"{spec.name}_baseline_report.json"
    booster.save_model(str(model_path))

    summary = {
        "model": spec.name,
        "target": spec.target,
        "rows": {
            "all": int(len(df)),
            "train": int(len(train_df)),
            "val": int(len(val_df)),
            "test": int(len(test_df)),
        },
        "feature_columns": feature_columns,
        "validation_source": "train_holdout_split",
        "test_source": "exported_test_split",
        "best_iteration": int(best_iteration),
        "metrics": {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "spearman": spearman,
            "within_5": within_5,
            "within_10": within_10,
        },
        "target_stats": {
            "train_min": float(train_df[spec.target].min()),
            "train_max": float(train_df[spec.target].max()),
            "test_min": float(test_df[spec.target].min()),
            "test_max": float(test_df[spec.target].max()),
        },
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_regression_stratify_labels(values: list[float]) -> list[int] | None:
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError:
        return None

    series = pd.Series(values)
    unique_count = int(series.nunique(dropna=True))
    if unique_count < 2:
        return None
    q = min(8, unique_count)
    try:
        bins = pd.qcut(series, q=q, duplicates="drop", labels=False)
    except ValueError:
        return None
    if bins.nunique(dropna=True) < 2:
        return None
    return bins.astype(int).tolist()


def safe_spearman(truth: list[float], prediction: list[float]) -> float:
    if not truth or len(truth) != len(prediction):
        return 0.0
    try:
        from scipy.stats import spearmanr  # type: ignore
    except ModuleNotFoundError:
        return 0.0
    corr = spearmanr(truth, prediction).correlation
    if corr is None or math.isnan(corr):
        return 0.0
    return float(corr)


if __name__ == "__main__":
    raise SystemExit(main())

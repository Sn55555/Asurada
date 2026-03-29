from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "tyre_degradation_trend_baseline"


@dataclass
class TrendTargetSpec:
    name: str
    target_column: str


TARGET_SPECS = [
    TrendTargetSpec(name="future_tyre_wear_delta", target_column="future_tyre_wear_delta"),
    TrendTargetSpec(name="future_grip_drop_score", target_column="future_grip_drop_score"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train tyre degradation trend baseline models.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to features.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for reports and model artifacts.",
    )
    parser.add_argument(
        "--horizon-s",
        type=float,
        default=15.0,
        help="Future horizon in seconds for degradation labels.",
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
    df = pd.read_csv(args.dataset, low_memory=False)
    if df.empty:
        raise SystemExit("No feature rows available for training.")

    df = df[df["timing_support_level"] == "official_preferred"].copy()
    df = df[df["session_type"].fillna("").str.contains("RaceLike")].copy()
    df["session_time_s"] = pd.to_numeric(df["session_time_s"], errors="coerce")
    df["lap_number"] = pd.to_numeric(df["lap_number"], errors="coerce")
    df["tyre_wear_pct"] = pd.to_numeric(df["tyre_wear_pct"], errors="coerce")
    df["recent_front_overload_ratio"] = pd.to_numeric(df["recent_front_overload_ratio"], errors="coerce")
    df["wheel_slip_ratio_fl"] = pd.to_numeric(df["wheel_slip_ratio_fl"], errors="coerce")
    df["wheel_slip_ratio_fr"] = pd.to_numeric(df["wheel_slip_ratio_fr"], errors="coerce")
    df["wheel_slip_ratio_rl"] = pd.to_numeric(df["wheel_slip_ratio_rl"], errors="coerce")
    df["wheel_slip_ratio_rr"] = pd.to_numeric(df["wheel_slip_ratio_rr"], errors="coerce")

    df = df.dropna(subset=["session_uid", "session_time_s", "lap_number", "tyre_wear_pct"]).copy()
    df = df.sort_values(["session_uid", "session_time_s", "frame_identifier"]).reset_index(drop=True)
    labelled = build_future_targets(df=df, horizon_s=args.horizon_s, pd_module=pd)
    labelled = labelled.dropna(subset=[spec.target_column for spec in TARGET_SPECS]).copy()
    if labelled.empty:
        raise SystemExit("No rows retained after future-horizon target generation.")

    labelled["trend_split"] = labelled.apply(assign_trend_split, axis=1)

    numeric_features = [
        "lap_number",
        "session_time_s",
        "speed_kph",
        "throttle",
        "brake",
        "steer",
        "fuel_in_tank",
        "ers_pct",
        "tyre_wear_pct",
        "tyre_age_laps",
        "recent_unstable_ratio",
        "recent_front_overload_ratio",
        "g_force_lateral",
        "g_force_longitudinal",
        "wheel_slip_ratio_fl",
        "wheel_slip_ratio_fr",
        "wheel_slip_ratio_rl",
        "wheel_slip_ratio_rr",
    ]
    categorical_features = [
        "session_type",
        "track",
        "track_zone",
        "track_segment",
        "track_usage",
        "driving_mode",
        "tyre_compound",
    ]

    for column in numeric_features:
        if column in labelled.columns:
            labelled[column] = pd.to_numeric(labelled[column], errors="coerce")
    for column in categorical_features:
        if column in labelled.columns:
            labelled[column] = labelled[column].fillna("UNKNOWN").astype("category")

    summary: dict[str, object] = {
        "dataset": str(args.dataset),
        "horizon_s": args.horizon_s,
        "rows": {
            "all": int(len(labelled)),
            "train": int((labelled["trend_split"] == "train").sum()),
            "val": int((labelled["trend_split"] == "val").sum()),
            "test": int((labelled["trend_split"] == "test").sum()),
        },
        "models": {},
    }

    feature_columns = numeric_features + categorical_features
    for spec in TARGET_SPECS:
        model_summary = train_single_model(
            df=labelled,
            feature_columns=feature_columns,
            categorical_features=categorical_features,
            spec=spec,
            output_dir=args.output_dir / spec.name,
            lgb_module=lgb,
            pd_module=pd,
            metrics_module={
                "mae": mean_absolute_error,
                "mse": mean_squared_error,
                "r2": r2_score,
            },
        )
        summary["models"][spec.name] = model_summary

    summary_path = args.output_dir / "tyre_degradation_trend_baseline_report.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_future_targets(*, df, horizon_s: float, pd_module):
    rows = []
    for _, group in df.groupby("session_uid", sort=False):
        group = group.sort_values(["session_time_s", "frame_identifier"]).reset_index(drop=True)
        future_index = 0
        session_times = group["session_time_s"].tolist()
        tyre_wear = group["tyre_wear_pct"].tolist()
        overload = group["recent_front_overload_ratio"].fillna(0.0).tolist()
        slip_avg = (
            group[["wheel_slip_ratio_fl", "wheel_slip_ratio_fr", "wheel_slip_ratio_rl", "wheel_slip_ratio_rr"]]
            .fillna(0.0)
            .mean(axis=1)
            .tolist()
        )
        for idx, row in group.iterrows():
            target_time = float(row["session_time_s"]) + horizon_s
            while future_index < len(session_times) and session_times[future_index] < target_time:
                future_index += 1
            if future_index >= len(session_times):
                break
            future_row = group.iloc[future_index]
            wear_delta = max(0.0, float(tyre_wear[future_index]) - float(row["tyre_wear_pct"]))
            overload_delta = max(0.0, float(overload[future_index]) - float(overload[idx]))
            slip_delta = max(0.0, float(slip_avg[future_index]) - float(slip_avg[idx]))
            grip_drop_score = min(100.0, wear_delta * 6.0 + overload_delta * 35.0 + slip_delta * 40.0)
            row_dict = row.to_dict()
            row_dict["future_tyre_wear_delta"] = wear_delta
            row_dict["future_grip_drop_score"] = grip_drop_score
            rows.append(row_dict)
    return pd_module.DataFrame(rows)


def assign_trend_split(row) -> str:
    session_type = str(row.get("session_type") or "")
    lap_number = int(row.get("lap_number") or 0)
    if "FeatureRaceLike" in session_type:
        return "test"
    if "SprintRaceLike" in session_type and lap_number == 2:
        return "val"
    return "train"


def train_single_model(*, df, feature_columns, categorical_features, spec, output_dir, lgb_module, pd_module, metrics_module):
    output_dir.mkdir(parents=True, exist_ok=True)
    train_df = df[df["trend_split"] == "train"].copy()
    val_df = df[df["trend_split"] == "val"].copy()
    test_df = df[df["trend_split"] == "test"].copy()
    if train_df.empty or val_df.empty or test_df.empty:
        raise SystemExit(f"Insufficient train/val/test rows for {spec.name}.")

    train_set = lgb_module.Dataset(
        train_df[feature_columns],
        label=train_df[spec.target_column],
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    val_set = lgb_module.Dataset(
        val_df[feature_columns],
        label=val_df[spec.target_column],
        categorical_feature=categorical_features,
        free_raw_data=False,
    )

    booster = lgb_module.train(
        params={
            "objective": "regression",
            "metric": ["l1", "l2"],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "min_data_in_leaf": 30,
            "verbosity": -1,
            "seed": 42,
        },
        train_set=train_set,
        num_boost_round=300,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=[lgb_module.early_stopping(30), lgb_module.log_evaluation(25)],
    )

    best_iteration = booster.best_iteration or 300
    preds = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    mae = float(metrics_module["mae"](test_df[spec.target_column], preds))
    rmse = math.sqrt(float(metrics_module["mse"](test_df[spec.target_column], preds)))
    r2 = float(metrics_module["r2"](test_df[spec.target_column], preds))
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
        "target": spec.target_column,
        "rows": {
            "train": int(len(train_df)),
            "val": int(len(val_df)),
            "test": int(len(test_df)),
        },
        "feature_columns": feature_columns,
        "categorical_features": list(categorical_features),
        "validation_source": "exported_val_split",
        "test_source": "exported_test_split",
        "best_iteration": int(best_iteration),
        "metrics": {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    raise SystemExit(main())

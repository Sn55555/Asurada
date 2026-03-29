from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "driver_style_baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train driver-style baseline models.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to features.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for reports and model artifacts.",
    )
    parser.add_argument(
        "--window-s",
        type=float,
        default=20.0,
        help="Session-time window size used to build long-horizon style samples.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import classification_report, mean_absolute_error, mean_squared_error, r2_score  # type: ignore
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
    if df.empty:
        raise SystemExit("No official race-like rows available for style training.")

    numeric_columns = [
        "session_time_s",
        "lap_number",
        "speed_kph",
        "throttle",
        "brake",
        "steer",
        "ers_pct",
        "tyre_wear_pct",
        "recent_unstable_ratio",
        "recent_front_overload_ratio",
        "g_force_lateral",
        "g_force_longitudinal",
        "wheel_slip_ratio_fl",
        "wheel_slip_ratio_fr",
        "wheel_slip_ratio_rl",
        "wheel_slip_ratio_rr",
        "front_rival_speed_delta",
        "rear_rival_speed_delta",
        "official_gap_ahead_s",
        "official_gap_behind_s",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["session_uid", "session_time_s"]).copy()
    df["window_id"] = (df["session_time_s"] // args.window_s).fillna(0).astype(int)
    df["abs_steer"] = df["steer"].abs()
    df["slip_mean"] = df[
        ["wheel_slip_ratio_fl", "wheel_slip_ratio_fr", "wheel_slip_ratio_rl", "wheel_slip_ratio_rr"]
    ].fillna(0.0).mean(axis=1)
    df["speed_norm"] = (df["speed_kph"].fillna(0.0) / 330.0).clip(lower=0.0, upper=1.0)
    df["drs_flag"] = df["drs_available"].fillna(False).astype(int)
    df["attack_gap_close"] = (
        df["official_gap_ahead_s"].fillna(9.9).clip(lower=0.0, upper=3.0).rsub(3.0) / 3.0
    ).clip(lower=0.0, upper=1.0)

    grouped = []
    agg_map = {
        "sample_name": "first",
        "session_uid": "first",
        "session_type": "first",
        "track": "first",
        "window_id": "first",
        "lap_number": "first",
        "session_time_s": "min",
        "speed_kph": ["mean", "std"],
        "throttle": ["mean", "std"],
        "brake": ["mean", "std"],
        "abs_steer": ["mean", "std"],
        "ers_pct": ["mean"],
        "tyre_wear_pct": ["mean"],
        "recent_unstable_ratio": ["mean"],
        "recent_front_overload_ratio": ["mean"],
        "g_force_lateral": ["mean", "std"],
        "g_force_longitudinal": ["mean", "std"],
        "slip_mean": ["mean", "std"],
        "front_rival_speed_delta": ["mean"],
        "rear_rival_speed_delta": ["mean"],
        "attack_gap_close": ["mean"],
        "drs_flag": ["mean"],
    }
    aggregated = df.groupby(["session_uid", "window_id"], sort=False).agg(agg_map)
    aggregated.columns = ["_".join(part for part in col if part).strip("_") for col in aggregated.columns.to_flat_index()]
    aggregated = aggregated.reset_index(drop=True)
    if aggregated.empty:
        raise SystemExit("No windowed rows available after aggregation.")

    aggregated["aggression_score"] = build_aggression_score(aggregated)
    aggregated["consistency_score"] = build_consistency_score(aggregated)
    aggregated["driver_style_tag"] = aggregated.apply(assign_style_tag, axis=1)
    aggregated["style_split"] = aggregated.apply(assign_style_split, axis=1)

    feature_columns = [
        "lap_number_first",
        "session_time_s_min",
        "speed_kph_mean",
        "speed_kph_std",
        "throttle_mean",
        "throttle_std",
        "brake_mean",
        "brake_std",
        "abs_steer_mean",
        "abs_steer_std",
        "ers_pct_mean",
        "tyre_wear_pct_mean",
        "recent_unstable_ratio_mean",
        "recent_front_overload_ratio_mean",
        "g_force_lateral_mean",
        "g_force_lateral_std",
        "g_force_longitudinal_mean",
        "g_force_longitudinal_std",
        "slip_mean_mean",
        "slip_mean_std",
        "front_rival_speed_delta_mean",
        "rear_rival_speed_delta_mean",
        "attack_gap_close_mean",
        "drs_flag_mean",
    ]
    categorical_features = [
        "session_type_first",
        "track_first",
    ]
    for column in categorical_features:
        aggregated[column] = aggregated[column].fillna("UNKNOWN").astype("category")

    train_df = aggregated[aggregated["style_split"] == "train"].copy()
    val_df = aggregated[aggregated["style_split"] == "val"].copy()
    test_df = aggregated[aggregated["style_split"] == "test"].copy()
    if train_df.empty or val_df.empty or test_df.empty:
        raise SystemExit("Insufficient train/val/test rows for driver-style baseline.")

    summary = {
        "dataset": str(args.dataset),
        "window_s": args.window_s,
        "rows": {
            "all": int(len(aggregated)),
            "train": int(len(train_df)),
            "val": int(len(val_df)),
            "test": int(len(test_df)),
        },
        "models": {},
    }

    summary["models"]["aggression_score"] = train_regressor(
        name="aggression_score",
        feature_columns=feature_columns + categorical_features,
        categorical_features=categorical_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        target_column="aggression_score",
        output_dir=args.output_dir / "aggression_score",
        lgb=lgb,
        metrics={
            "mae": mean_absolute_error,
            "mse": mean_squared_error,
            "r2": r2_score,
        },
    )
    summary["models"]["consistency_score"] = train_regressor(
        name="consistency_score",
        feature_columns=feature_columns + categorical_features,
        categorical_features=categorical_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        target_column="consistency_score",
        output_dir=args.output_dir / "consistency_score",
        lgb=lgb,
        metrics={
            "mae": mean_absolute_error,
            "mse": mean_squared_error,
            "r2": r2_score,
        },
    )
    summary["models"]["driver_style_tag"] = train_classifier(
        feature_columns=feature_columns + categorical_features,
        categorical_features=categorical_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        target_column="driver_style_tag",
        output_dir=args.output_dir / "driver_style_tag",
        lgb=lgb,
    )

    output_path = args.output_dir / "driver_style_baseline_report.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_aggression_score(df):
    score = (
        df["throttle_mean"].fillna(0.0) * 28.0
        + df["brake_mean"].fillna(0.0) * 12.0
        + df["abs_steer_mean"].fillna(0.0) * 24.0
        + df["speed_kph_mean"].fillna(0.0).clip(lower=0.0, upper=330.0) / 330.0 * 12.0
        + df["slip_mean_mean"].fillna(0.0).clip(lower=0.0, upper=0.4) / 0.4 * 10.0
        + df["recent_unstable_ratio_mean"].fillna(0.0).clip(lower=0.0, upper=1.0) * 6.0
        + df["attack_gap_close_mean"].fillna(0.0) * 5.0
        + df["drs_flag_mean"].fillna(0.0).clip(lower=0.0, upper=1.0) * 3.0
        + (50.0 - df["ers_pct_mean"].fillna(50.0)).clip(lower=0.0, upper=50.0) / 50.0 * 4.0
    )
    return score.clip(lower=0.0, upper=100.0)


def build_consistency_score(df):
    penalty = (
        df["throttle_std"].fillna(0.0).clip(lower=0.0, upper=0.6) / 0.6 * 20.0
        + df["brake_std"].fillna(0.0).clip(lower=0.0, upper=0.6) / 0.6 * 14.0
        + df["abs_steer_std"].fillna(0.0).clip(lower=0.0, upper=0.4) / 0.4 * 20.0
        + df["slip_mean_std"].fillna(0.0).clip(lower=0.0, upper=0.25) / 0.25 * 18.0
        + df["g_force_lateral_std"].fillna(0.0).clip(lower=0.0, upper=1.2) / 1.2 * 10.0
        + df["g_force_longitudinal_std"].fillna(0.0).clip(lower=0.0, upper=1.2) / 1.2 * 8.0
        + df["recent_unstable_ratio_mean"].fillna(0.0).clip(lower=0.0, upper=1.0) * 10.0
    )
    return (100.0 - penalty).clip(lower=0.0, upper=100.0)


def assign_style_tag(row) -> str:
    aggression = float(row["aggression_score"])
    consistency = float(row["consistency_score"])
    if consistency < 42.0:
        return "erratic"
    if aggression >= 66.0:
        return "aggressive"
    if aggression <= 38.0 and consistency >= 68.0:
        return "smooth"
    return "balanced"


def assign_style_split(row) -> str:
    session_type = str(row.get("session_type_first") or "")
    lap_number = int(row.get("lap_number_first") or 0)
    if "FeatureRaceLike" in session_type:
        return "test"
    if "SprintRaceLike" in session_type and lap_number == 2:
        return "val"
    return "train"


def train_regressor(*, name, feature_columns, categorical_features, train_df, val_df, test_df, target_column, output_dir, lgb, metrics):
    output_dir.mkdir(parents=True, exist_ok=True)
    train_set = lgb.Dataset(
        train_df[feature_columns],
        label=train_df[target_column],
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        val_df[feature_columns],
        label=val_df[target_column],
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    booster = lgb.train(
        params={
            "objective": "regression",
            "metric": ["l1", "l2"],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "min_data_in_leaf": 12,
            "verbosity": -1,
            "seed": 42,
        },
        train_set=train_set,
        num_boost_round=300,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(25)],
    )
    best_iteration = booster.best_iteration or 300
    preds = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    mae = float(metrics["mae"](test_df[target_column], preds))
    rmse = math.sqrt(float(metrics["mse"](test_df[target_column], preds)))
    r2 = float(metrics["r2"](test_df[target_column], preds))
    importance = sorted(
        (
            {"feature": fname, "importance": int(value)}
            for fname, value in zip(feature_columns, booster.feature_importance(importance_type="gain"))
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )
    model_path = output_dir / f"{name}_baseline.txt"
    report_path = output_dir / f"{name}_baseline_report.json"
    booster.save_model(str(model_path))
    summary = {
        "target": target_column,
        "best_iteration": int(best_iteration),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def train_classifier(*, feature_columns, categorical_features, train_df, val_df, test_df, target_column, output_dir, lgb):
    output_dir.mkdir(parents=True, exist_ok=True)
    label_map = {label: idx for idx, label in enumerate(sorted(train_df[target_column].astype(str).unique()))}
    inverse_label_map = {idx: label for label, idx in label_map.items()}
    train_y = train_df[target_column].map(label_map)
    val_y = val_df[target_column].map(label_map)
    test_y = test_df[target_column].map(label_map).fillna(-1).astype(int)

    train_set = lgb.Dataset(
        train_df[feature_columns],
        label=train_y,
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        val_df[feature_columns],
        label=val_y,
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    booster = lgb.train(
        params={
            "objective": "multiclass",
            "metric": ["multi_logloss"],
            "num_class": len(label_map),
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "min_data_in_leaf": 12,
            "verbosity": -1,
            "seed": 42,
        },
        train_set=train_set,
        num_boost_round=300,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(25)],
    )
    best_iteration = booster.best_iteration or 300
    probs = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    preds = probs.argmax(axis=1)

    from sklearn.metrics import classification_report  # type: ignore

    report = classification_report(
        test_y,
        preds,
        labels=sorted(idx for idx in inverse_label_map if idx in set(test_y.tolist()) | set(preds.tolist())),
        target_names=[inverse_label_map[idx] for idx in sorted(idx for idx in inverse_label_map if idx in set(test_y.tolist()) | set(preds.tolist()))],
        output_dict=True,
        zero_division=0,
    )
    importance = sorted(
        (
            {"feature": fname, "importance": int(value)}
            for fname, value in zip(feature_columns, booster.feature_importance(importance_type="gain"))
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )
    model_path = output_dir / "driver_style_tag_baseline.txt"
    report_path = output_dir / "driver_style_tag_baseline_report.json"
    booster.save_model(str(model_path))
    summary = {
        "target": target_column,
        "best_iteration": int(best_iteration),
        "classification_report": report,
        "label_map": label_map,
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    raise SystemExit(main())

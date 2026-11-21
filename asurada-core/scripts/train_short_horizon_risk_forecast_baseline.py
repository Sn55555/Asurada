from __future__ import annotations

import argparse
import json
import sys
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT / "src"))
from asurada.training_join import join_training_labels
from asurada.training_partition import session_partitions, exported_row_split, validate_session_frame
from asurada.training_windows import future_windows, WINDOW_VERSION, write_target_windows
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_LABELS = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "labels.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "short_horizon_risk_forecast_baseline"


@dataclass
class ForecastTargetSpec:
    name: str
    target_column: str


TARGET_SPECS = [
    ForecastTargetSpec(name="risk_forecast_3s", target_column="risk_forecast_3s"),
    ForecastTargetSpec(name="risk_forecast_next_zone", target_column="risk_forecast_next_zone"),
]


RISK_COLUMNS = [
    "fuel_risk_label",
    "tyre_risk_label",
    "ers_risk_label",
    "race_control_risk_label",
    "dynamics_risk_label",
    "attack_opportunity_label",
    "defend_risk_label",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train short-horizon risk forecast baseline models.")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="Path to features.csv.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Path to labels.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for reports and model artifacts.",
    )
    parser.add_argument(
        "--horizon-s",
        type=float,
        default=3.0,
        help="Future horizon in seconds for short-horizon risk forecast.",
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
    features = pd.read_csv(args.features, low_memory=False, dtype={"session_uid":str})
    features = validate_session_frame(features)
    labels = pd.read_csv(args.labels, low_memory=False, dtype={"session_uid":str})
    if features.empty or labels.empty:
        raise SystemExit("No exported feature/label rows available for training.")

    features,join_manifest = join_training_labels(features,labels,targets=["fuel_risk_label","tyre_risk_label","ers_risk_label","race_control_risk_label","dynamics_risk_label","attack_opportunity_label","defend_risk_label","primary_action_label"])
    features = features[features["timing_support_level"] == "official_preferred"].copy()
    features = features[features["session_type"].fillna("").str.contains("RaceLike")].copy()
    features["session_time_s"] = pd.to_numeric(features["session_time_s"], errors="coerce")
    features = features.dropna(subset=["session_uid", "session_time_s", "track_segment"]).copy()

    for column in RISK_COLUMNS:
        features[column] = pd.to_numeric(features[column], errors="coerce").fillna(0.0)
    features["current_risk_score"] = features[RISK_COLUMNS].max(axis=1)

    labelled = build_future_targets(df=features, horizon_s=args.horizon_s, pd_module=pd)
    labelled = labelled.dropna(subset=[spec.target_column for spec in TARGET_SPECS], how="all").copy()
    if labelled.empty:
        raise SystemExit("No rows retained after future risk target generation.")

    labelled["forecast_split"] = labelled.apply(assign_forecast_split, axis=1)
    train_part,val_part,test_part,_ = session_partitions(labelled,split_column="forecast_split")
    labelled = pd.concat([train_part,val_part,test_part],ignore_index=True)
    window_manifest=write_target_windows(labelled,output_dir=args.output_dir,targets=[spec.target_column for spec in TARGET_SPECS],split_column="forecast_split",sources=[args.features,args.labels])

    numeric_features = [
        "lap_number",
        "session_time_s",
        "player_position",
        "official_gap_ahead_s",
        "official_gap_behind_s",
        "gap_closing_rate_ahead",
        "gap_closing_rate_behind",
        "speed_kph",
        "throttle",
        "brake",
        "steer",
        "fuel_in_tank",
        "fuel_laps_remaining",
        "ers_pct",
        "tyre_wear_pct",
        "recent_unstable_ratio",
        "recent_front_overload_ratio",
        "front_rival_speed_delta",
        "rear_rival_speed_delta",
        "current_risk_score",
        "fuel_risk_label",
        "tyre_risk_label",
        "ers_risk_label",
        "dynamics_risk_label",
        "attack_opportunity_label",
        "defend_risk_label",
    ]
    categorical_features = [
        "session_type",
        "track",
        "track_zone",
        "track_segment",
        "track_usage",
        "next_track_segment",
        "next_track_usage",
        "driving_mode",
        "primary_action_label",
    ]

    for column in numeric_features:
        if column in labelled.columns:
            labelled[column] = pd.to_numeric(labelled[column], errors="coerce")
    for column in categorical_features:
        if column in labelled.columns:
            labelled[column] = labelled[column].fillna("UNKNOWN").astype("category")

    summary: dict[str, object] = {
        "features": str(args.features),
        "labels": str(args.labels),
        "horizon_s": args.horizon_s,
        "label_join": join_manifest,
        "target_windows": window_manifest,
        "rows": {
            "all": int(len(labelled)),
            "train": int((labelled["forecast_split"] == "train").sum()),
            "val": int((labelled["forecast_split"] == "val").sum()),
            "test": int((labelled["forecast_split"] == "test").sum()),
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
            metrics_module={
                "mae": mean_absolute_error,
                "mse": mean_squared_error,
                "r2": r2_score,
            },
        )
        summary["models"][spec.name] = model_summary

    summary_path = args.output_dir / "short_horizon_risk_forecast_baseline_report.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_future_targets(*, df, horizon_s: float, pd_module):
    rows=[]
    for row,window,evidence in future_windows(df,horizon_s=horizon_s):
        inside=window[window['session_time_s']<=float(row['session_time_s'])+horizon_s]
        scores=inside['current_risk_score']
        if inside.empty or not all(math.isfinite(float(v)) for v in scores):continue
        next_zone=inside[inside['track_segment'].astype(str)!=str(row['track_segment'])]
        result=row.to_dict()
        result.update(risk_forecast_3s=float(scores.max()),
            risk_forecast_next_zone=float(next_zone.iloc[0]['current_risk_score']) if not next_zone.empty else None,
            target_window=json.dumps(evidence,ensure_ascii=False))
        rows.append(result)
    return pd_module.DataFrame(rows,columns=[*df.columns,'risk_forecast_3s','risk_forecast_next_zone','target_window'])


def assign_forecast_split(row) -> str:
    return exported_row_split(row)


def train_single_model(*, df, feature_columns, categorical_features, spec, output_dir, lgb_module, metrics_module):
    output_dir.mkdir(parents=True, exist_ok=True)
    df = df.dropna(subset=[spec.target_column]).copy()
    train_df, val_df, test_df, partition_manifest = session_partitions(df, split_column="forecast_split")
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
        "validation_source": "whole_session_partition",
        "partition": partition_manifest,
        "target_window_policy": WINDOW_VERSION,
        "target_window_max_gap_s": 1.0,
        "test_source": "exported_session_split",
        "best_iteration": int(best_iteration),
        "metrics": {
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
        },
        "top_feature_importance": importance[:20],
        "model_path": model_path.name,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    raise SystemExit(main())

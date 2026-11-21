from __future__ import annotations

import argparse
import json
import sys
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT / "src"))
from asurada.training_partition import session_partitions, exported_row_split, validate_session_frame
from asurada.training_windows import future_windows, WINDOW_VERSION, write_target_windows
from asurada.training_provenance import training_provenance
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
    provenance = training_provenance(args.dataset)
    df = pd.read_csv(args.dataset, low_memory=False, dtype={"session_uid":str})
    df = validate_session_frame(df)
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
    labelled = build_future_targets(df=df, horizon_s=args.horizon_s, pd_module=pd)
    labelled = labelled.dropna(subset=[spec.target_column for spec in TARGET_SPECS]).copy()
    if labelled.empty:
        raise SystemExit("No rows retained after future-horizon target generation.")

    labelled["trend_split"] = labelled.apply(assign_trend_split, axis=1)
    train_part,val_part,test_part,_ = session_partitions(labelled,split_column="trend_split")
    labelled = pd.concat([train_part,val_part,test_part],ignore_index=True)
    window_manifest=write_target_windows(labelled,output_dir=args.output_dir,targets=[spec.target_column for spec in TARGET_SPECS],split_column="trend_split",sources=[args.dataset])

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
        "target_windows": window_manifest,
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
            provenance=provenance,
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
    rows=[]
    wheels=['wheel_slip_ratio_fl','wheel_slip_ratio_fr','wheel_slip_ratio_rl','wheel_slip_ratio_rr']
    for row,window,evidence in future_windows(df,horizon_s=horizon_s,
            stable_columns=('tyre_compound',),reset_columns=('tyre_age_laps','tyre_wear_pct')):
        last=window.iloc[-1]
        if not all(math.isfinite(float(v)) for point in (row,last) for v in point[['tyre_wear_pct','recent_front_overload_ratio',*wheels]]):continue
        wear_delta=max(0.,float(last['tyre_wear_pct'])-float(row['tyre_wear_pct']))
        overload_delta=max(0.,float(last['recent_front_overload_ratio'])-float(row['recent_front_overload_ratio']))
        slip_delta=max(0.,float(last[wheels].mean())-float(row[wheels].mean()))
        values=(wear_delta,overload_delta,slip_delta)
        if not all(math.isfinite(v) for v in values):continue
        result=row.to_dict()
        result.update(future_tyre_wear_delta=wear_delta,
            future_grip_drop_score=min(100.,wear_delta*6.+overload_delta*35.+slip_delta*40.),
            target_window=json.dumps(evidence,ensure_ascii=False))
        rows.append(result)
    return pd_module.DataFrame(rows,columns=[*df.columns,'future_tyre_wear_delta','future_grip_drop_score','target_window'])


def assign_trend_split(row) -> str:
    return exported_row_split(row)


def train_single_model(*, df, feature_columns, categorical_features, spec, output_dir, lgb_module, pd_module, metrics_module, provenance=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    train_df, val_df, test_df, partition_manifest = session_partitions(df, split_column="trend_split")
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
        "training_provenance": provenance or {'export_metadata_status': 'not_provided'},
        "context_window_version": (provenance or {}).get('context_window_version'),
        "label_provenance": {'kind': 'telemetry_delta' if spec.target_column == 'future_tyre_wear_delta' else 'formula_proxy', 'human_validated': False},
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

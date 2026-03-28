from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_LABELS = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "labels.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "defence_cost_baseline"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    target: str
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


MODEL_SPEC = ModelSpec(
    name="defence_cost",
    target="defence_cost_proxy",
    numeric_features=(
        "session_time_s",
        "lap_number",
        "total_laps",
        "player_position",
        "official_gap_behind_s",
        "gap_closing_rate_behind",
        "rear_rival_speed_kph",
        "rear_rival_ers_pct",
        "rear_rival_speed_delta",
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
        "wheel_slip_ratio_rl",
        "wheel_slip_ratio_rr",
    ),
    categorical_features=(
        "session_type",
        "timing_mode",
        "timing_support_level",
        "track",
        "track_zone",
        "track_segment",
        "track_usage",
        "next_track_segment",
        "next_track_usage",
        "next_two_segments",
        "weather",
        "safety_car",
        "driving_mode",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the first defence-cost baseline regressor.")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="Path to features.csv.")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Path to labels.csv.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for reports and model artifacts.")
    return parser.parse_args()


def main() -> int:
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas`, `lightgbm`, and `scikit-learn` in /Users/sn5/Asurada/asurada-core/.venv before training."
        )

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    features_df = pd.read_csv(args.features, low_memory=False)
    labels_df = pd.read_csv(args.labels, low_memory=False)
    merged = features_df.merge(
        labels_df[["record_id", "primary_action_label"]],
        on="record_id",
        how="inner",
    )

    merged = filter_tactical_rows(merged)
    if merged.empty:
        raise SystemExit("No tactical rows available for defence-cost training.")

    merged["split"] = merged.apply(derive_defence_cost_split, axis=1)
    merged[MODEL_SPEC.target] = merged.apply(compute_defence_cost_target, axis=1)

    for column in MODEL_SPEC.numeric_features:
        if column in merged.columns:
            merged[column] = merged[column].astype(float)
    for column in MODEL_SPEC.categorical_features:
        if column in merged.columns:
            merged[column] = merged[column].fillna("UNKNOWN").astype("category")

    train_df = merged[merged["split"] == "train"].copy()
    val_df = merged[merged["split"] == "val"].copy()
    test_df = merged[merged["split"] == "test"].copy()
    if train_df.empty or val_df.empty or test_df.empty:
        raise SystemExit("defence_cost baseline requires deterministic train/val/test rows.")

    feature_columns = [*MODEL_SPEC.numeric_features, *MODEL_SPEC.categorical_features]
    train_x = train_df[feature_columns]
    train_y = train_df[MODEL_SPEC.target].astype(float)
    val_x = val_df[feature_columns]
    val_y = val_df[MODEL_SPEC.target].astype(float)
    test_x = test_df[feature_columns]
    test_y = test_df[MODEL_SPEC.target].astype(float)

    model = lgb.LGBMRegressor(
        objective="regression",
        learning_rate=0.05,
        n_estimators=400,
        num_leaves=63,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
    )
    model.fit(
        train_x,
        train_y,
        eval_set=[(val_x, val_y)],
        eval_metric="l2",
        callbacks=[
            lgb.early_stopping(stopping_rounds=40, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )

    predictions = model.predict(test_x, num_iteration=model.best_iteration_)
    mae = float(mean_absolute_error(test_y, predictions))
    rmse = float(math.sqrt(mean_squared_error(test_y, predictions)))
    r2 = float(r2_score(test_y, predictions))
    spearman = float(test_y.corr(pd.Series(predictions, index=test_y.index), method="spearman"))
    if math.isnan(spearman):
        spearman = 0.0

    importance_df = (
        pd.DataFrame(
            {
                "feature": feature_columns,
                "importance": model.feature_importances_,
            }
        )
        .sort_values(["importance", "feature"], ascending=[False, True])
        .head(12)
        .reset_index(drop=True)
    )

    model_path = args.output_dir / "defence_cost_model_baseline.txt"
    report = {
        "model": MODEL_SPEC.name,
        "target": MODEL_SPEC.target,
        "label_source": "defence_cost_proxy_recomputed_from_features",
        "label_type": "proxy_distillation_baseline",
        "features_path": str(args.features),
        "labels_path": str(args.labels),
        "filter": "official_preferred race-like tactical rows",
        "validation_source": "exported_val_split",
        "test_source": "exported_test_split",
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
        "test_rows": int(len(test_df)),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "tactical_cost_correlation": round(spearman, 4),
        "best_iteration": int(model.best_iteration_ or 0),
        "top_feature_importance": importance_df.to_dict(orient="records"),
        "top_features": importance_df.to_dict(orient="records"),
        "feature_columns": feature_columns,
        "model_path": str(model_path),
    }

    model.booster_.save_model(str(model_path))
    (args.output_dir / "defence_cost_baseline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def filter_tactical_rows(df):
    race_like = df["session_type"].astype(str).str.contains("RaceLike")
    official = df["timing_support_level"] == "official_preferred"
    position_change = (df["position_lost_recently"] == 1) | (df["position_gain_recently"] == 1)
    strategy_action = df["primary_action_label"].isin(["DEFEND_WINDOW", "ATTACK_WINDOW"])
    has_official_gap_behind = df["official_gap_behind_s"].notna()
    return df[official & race_like & (has_official_gap_behind | position_change | strategy_action)].copy()


def derive_defence_cost_split(row) -> str:
    session_type = str(row.get("session_type") or "")
    lap_number = int(row.get("lap_number") or 0)
    if "FeatureRaceLike" in session_type:
        return "test"
    if "SprintRaceLike" in session_type and lap_number == 2:
        return "val"
    return "train"


def compute_defence_cost_target(row) -> float:
    ers_pct = optional_float(row.get("ers_pct")) or 0.0
    tyre_wear_pct = optional_float(row.get("tyre_wear_pct")) or 0.0
    recent_front_overload_ratio = optional_float(row.get("recent_front_overload_ratio")) or 0.0
    track_usage = str(row.get("track_usage") or "")
    speed_kph = optional_float(row.get("speed_kph")) or 0.0

    score = 0.0
    score += max(0.0, 35.0 - ers_pct) * 0.6
    score += max(0.0, tyre_wear_pct - 45.0) * 0.8
    score += recent_front_overload_ratio * 25.0
    if track_usage in {"front_tyre_protection", "maximum_brake_pressure", "lateral_load_management"}:
        score += 12.0
    if speed_kph >= 260.0:
        score += 8.0
    return round(min(score, 100.0), 2)


def optional_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())

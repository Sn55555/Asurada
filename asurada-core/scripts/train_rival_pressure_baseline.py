from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_LABELS = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "labels.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "rival_pressure_baseline"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    target: str
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


MODEL_SPECS: dict[str, ModelSpec] = {
    "front_pressure": ModelSpec(
        name="front_pressure",
        target="front_pressure_proxy",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "total_laps",
            "player_position",
            "official_gap_ahead_s",
            "front_rival_speed_kph",
            "front_rival_ers_pct",
            "front_rival_speed_delta",
            "speed_kph",
            "throttle",
            "brake",
            "steer",
            "fuel_laps_remaining",
            "ers_pct",
            "drs_available",
            "tyre_wear_pct",
            "recent_unstable_ratio",
            "recent_front_overload_ratio",
            "g_force_lateral",
            "g_force_longitudinal",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "timing_support_level",
            "track",
            "track_segment",
            "track_usage",
            "next_track_segment",
            "next_track_usage",
            "driving_mode",
        ),
    ),
    "rear_pressure": ModelSpec(
        name="rear_pressure",
        target="rear_pressure_proxy",
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
            "drs_available",
            "tyre_wear_pct",
            "recent_unstable_ratio",
            "recent_front_overload_ratio",
            "g_force_lateral",
            "g_force_longitudinal",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "timing_support_level",
            "track",
            "track_segment",
            "track_usage",
            "next_track_segment",
            "next_track_usage",
            "driving_mode",
        ),
    ),
    "rival_pressure": ModelSpec(
        name="rival_pressure",
        target="rival_pressure_proxy",
        numeric_features=(
            "session_time_s",
            "lap_number",
            "total_laps",
            "player_position",
            "official_gap_ahead_s",
            "official_gap_behind_s",
            "gap_closing_rate_behind",
            "front_rival_speed_kph",
            "front_rival_ers_pct",
            "front_rival_speed_delta",
            "rear_rival_speed_kph",
            "rear_rival_ers_pct",
            "rear_rival_speed_delta",
            "speed_kph",
            "throttle",
            "brake",
            "steer",
            "fuel_laps_remaining",
            "ers_pct",
            "drs_available",
            "tyre_wear_pct",
            "recent_unstable_ratio",
            "recent_front_overload_ratio",
            "g_force_lateral",
            "g_force_longitudinal",
        ),
        categorical_features=(
            "session_type",
            "timing_mode",
            "timing_support_level",
            "track",
            "track_segment",
            "track_usage",
            "next_track_segment",
            "next_track_usage",
            "driving_mode",
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train proxy-distillation baselines for rival-pressure models.")
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
    merged = features_df.merge(labels_df[["record_id", "primary_action_label"]], on="record_id", how="inner")
    merged = filter_race_like_rows(merged)
    if merged.empty:
        raise SystemExit("No official race-like rows available for rival-pressure training.")

    merged["split"] = merged.apply(derive_split, axis=1)
    merged["front_pressure_proxy"] = merged.apply(compute_front_pressure_target, axis=1)
    merged["rear_pressure_proxy"] = merged.apply(compute_rear_pressure_target, axis=1)
    merged["rival_pressure_proxy"] = merged.apply(compute_rival_pressure_target, axis=1)

    aggregate: dict[str, object] = {
        "features_path": str(args.features),
        "labels_path": str(args.labels),
        "filter": "official_preferred race-like rows",
        "models": {},
    }
    for spec in MODEL_SPECS.values():
        summary = train_one_model(
            merged_df=merged.copy(),
            spec=spec,
            output_dir=args.output_dir / spec.name,
            lgb=lgb,
            pd=pd,
            mean_absolute_error=mean_absolute_error,
            mean_squared_error=mean_squared_error,
            r2_score=r2_score,
        )
        aggregate["models"][spec.name] = summary

    aggregate_path = args.output_dir / "rival_pressure_baselines_report.json"
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


def train_one_model(
    *,
    merged_df,
    spec: ModelSpec,
    output_dir: Path,
    lgb,
    pd,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    df = merged_df[merged_df[spec.target].notna()].copy()
    if df.empty:
        raise SystemExit(f"No rows available for {spec.name} after target filtering.")

    for column in spec.numeric_features:
        if column in df.columns:
            df[column] = df[column].astype(float)
    for column in spec.categorical_features:
        if column in df.columns:
            df[column] = df[column].fillna("UNKNOWN").astype("category")

    train_df = df[df["split"] == "train"].copy()
    val_df = df[df["split"] == "val"].copy()
    test_df = df[df["split"] == "test"].copy()
    if train_df.empty or val_df.empty or test_df.empty:
        raise SystemExit(f"{spec.name} baseline requires deterministic train/val/test rows.")

    feature_columns = [*spec.numeric_features, *spec.categorical_features]
    train_x = train_df[feature_columns]
    train_y = train_df[spec.target].astype(float)
    val_x = val_df[feature_columns]
    val_y = val_df[spec.target].astype(float)
    test_x = test_df[feature_columns]
    test_y = test_df[spec.target].astype(float)

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
        pd.DataFrame({"feature": feature_columns, "importance": model.feature_importances_})
        .sort_values(["importance", "feature"], ascending=[False, True])
        .head(12)
        .reset_index(drop=True)
    )

    model_path = output_dir / f"{spec.name}_model_baseline.txt"
    report = {
        "model": spec.name,
        "target": spec.target,
        "label_source": f"{spec.target}_recomputed_from_features",
        "label_type": "proxy_distillation_baseline",
        "features_path": str(DEFAULT_FEATURES),
        "labels_path": str(DEFAULT_LABELS),
        "filter": "official_preferred race-like rows",
        "validation_source": "exported_val_split",
        "test_source": "exported_test_split",
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
        "test_rows": int(len(test_df)),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "threat_ranking_accuracy": round(spearman, 4),
        "best_iteration": int(model.best_iteration_ or 0),
        "top_feature_importance": importance_df.to_dict(orient="records"),
        "top_features": importance_df.to_dict(orient="records"),
        "feature_columns": feature_columns,
        "model_path": str(model_path),
    }
    model.booster_.save_model(str(model_path))
    (output_dir / f"{spec.name}_baseline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def filter_race_like_rows(df):
    race_like = df["session_type"].astype(str).str.contains("RaceLike")
    official = df["timing_support_level"] == "official_preferred"
    return df[official & race_like].copy()


def derive_split(row) -> str:
    session_type = str(row.get("session_type") or "")
    lap_number = int(row.get("lap_number") or 0)
    if "FeatureRaceLike" in session_type:
        return "test"
    if "SprintRaceLike" in session_type and lap_number == 2:
        return "val"
    return "train"


def compute_front_pressure_target(row) -> float:
    gap_ahead = optional_float(row.get("official_gap_ahead_s"))
    front_speed_delta = optional_float(row.get("front_rival_speed_delta")) or 0.0
    ers_pct = optional_float(row.get("ers_pct")) or 0.0
    drs_available = int(row.get("drs_available") or 0)
    track_usage = str(row.get("track_usage") or "")
    recent_unstable_ratio = optional_float(row.get("recent_unstable_ratio")) or 0.0
    if gap_ahead is None:
        return 0.0

    score = max(0.0, 2.4 - gap_ahead) * 20.0
    score += max(0.0, front_speed_delta) * 2.0
    score += max(0.0, ers_pct - 35.0) * 0.18
    score += drs_available * 10.0
    if track_usage in {"attack_setup", "ers_deploy", "overtake_commit"}:
        score += 10.0
    score -= recent_unstable_ratio * 15.0
    return round(max(0.0, min(score, 100.0)), 2)


def compute_rear_pressure_target(row) -> float:
    gap_behind = optional_float(row.get("official_gap_behind_s"))
    gap_closing_rate_behind = optional_float(row.get("gap_closing_rate_behind")) or 0.0
    rear_speed_delta = optional_float(row.get("rear_rival_speed_delta")) or 0.0
    rear_ers_pct = optional_float(row.get("rear_rival_ers_pct")) or 0.0
    drs_available = int(row.get("drs_available") or 0)
    if gap_behind is None:
        return 0.0

    score = max(0.0, 2.0 - gap_behind) * 24.0
    score += max(0.0, gap_closing_rate_behind) * 60.0
    score += max(0.0, rear_speed_delta) * 1.8
    score += max(0.0, rear_ers_pct - 40.0) * 0.2
    if drs_available:
        score += 4.0
    return round(max(0.0, min(score, 100.0)), 2)


def compute_rival_pressure_target(row) -> float:
    front = compute_front_pressure_target(row)
    rear = compute_rear_pressure_target(row)
    combined = max(front, rear) + min(front, rear) * 0.25
    return round(max(0.0, min(combined, 100.0)), 2)


def optional_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())

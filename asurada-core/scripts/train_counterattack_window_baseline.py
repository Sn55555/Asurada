from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "tactical_features_v1.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "counterattack_window_baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the first counterattack-window baseline model.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to tactical_features_v1.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for reports and model artifacts.",
    )
    parser.add_argument(
        "--min-train-positives",
        type=int,
        default=12,
        help="Minimum positive rows required in train split before training.",
    )
    parser.add_argument(
        "--min-eval-positives",
        type=int,
        default=4,
        help="Minimum positive rows required in val/test split before training.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import classification_report, confusion_matrix  # type: ignore
        from sklearn.model_selection import train_test_split  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas`, `lightgbm`, and `scikit-learn` in /Users/sn5/Asurada/asurada-core/.venv before training."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.dataset)
    if df.empty:
        raise SystemExit("No tactical rows available for training.")

    df = df[df["timing_support_level"] == "official_preferred"].copy()
    df = df[df["session_type"].fillna("").str.contains("RaceLike")].copy()
    target_column = "counterattack_candidate_label"
    df[target_column] = pd.to_numeric(df[target_column], errors="coerce").fillna(0).astype(int)

    numeric_features = [
        "position_lost_recently",
        "position_gain_recently",
        "official_gap_ahead_s",
        "official_gap_behind_s",
        "gap_closing_rate_ahead",
        "gap_closing_rate_behind",
        "front_rival_speed_delta",
        "rear_rival_speed_delta",
        "speed_kph",
        "drs_available",
        "fuel_laps_remaining",
        "ers_pct",
        "tyre_wear_pct",
        "recent_unstable_ratio",
        "g_force_lateral",
        "g_force_longitudinal",
        "rear_threat_binary_label",
        "counterattack_zone_flag",
        "drs_recovery_window",
    ]
    categorical_features = [
        "track_zone",
        "track_segment",
        "track_usage",
        "next_track_segment",
        "next_track_usage",
        "next_two_segments",
        "driving_mode",
        "session_type",
        "rear_threat_level_label",
        "yield_vs_fight_proxy_label",
        "primary_action_label",
    ]

    for column in numeric_features:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in categorical_features:
        df[column] = df[column].fillna("UNKNOWN").astype("category")

    train_df = df[df["split"] == "train"].copy()
    val_df = df[df["split"] == "val"].copy()
    test_df = df[df["split"] == "test"].copy()

    split_positive_counts = {
        "train": int((train_df[target_column] == 1).sum()),
        "val": int((val_df[target_column] == 1).sum()),
        "test": int((test_df[target_column] == 1).sum()),
    }
    split_counts = {
        "all": int(len(df)),
        "train": int(len(train_df)),
        "val": int(len(val_df)),
        "test": int(len(test_df)),
    }

    summary_path = args.output_dir / "counterattack_window_baseline_report.json"
    model_path = args.output_dir / "counterattack_window_model_baseline.txt"

    if (
        split_positive_counts["train"] < args.min_train_positives
        or split_positive_counts["val"] < args.min_eval_positives
        or split_positive_counts["test"] < args.min_eval_positives
    ):
        summary = {
            "dataset": str(args.dataset),
            "target": target_column,
            "status": "blocked_insufficient_positive_samples",
            "rows": split_counts,
            "positive_rows": split_positive_counts,
            "required_positive_rows": {
                "train": args.min_train_positives,
                "val": args.min_eval_positives,
                "test": args.min_eval_positives,
            },
            "blocking_reason": "Current tactical exports do not contain enough post-loss counterattack rows to train a meaningful baseline.",
            "notes": [
                "Current player-view tactical samples contain almost no `position_lost_recently` rows.",
                "FeatureRaceLike uid16 currently provides zero positive counterattack rows in exported test split.",
                "Do not connect counterattack_window_model to runtime/mainline until richer loss-and-recovery samples exist.",
            ],
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    generated_holdout_val = False
    generated_holdout_test = False
    if val_df.empty:
        generated_holdout_val = True
        train_df, val_df = train_test_split(
            train_df,
            test_size=0.2,
            random_state=42,
            stratify=train_df[target_column],
        )
    if test_df.empty:
        generated_holdout_test = True
        train_df, test_df = train_test_split(
            train_df,
            test_size=0.2,
            random_state=42,
            stratify=train_df[target_column],
        )

    feature_columns = numeric_features + categorical_features
    negative_count = max(1, int((train_df[target_column] == 0).sum()))
    positive_count = max(1, int((train_df[target_column] == 1).sum()))

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
            "objective": "binary",
            "metric": ["binary_logloss", "auc"],
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "min_data_in_leaf": 12,
            "verbosity": -1,
            "seed": 42,
            "scale_pos_weight": negative_count / positive_count,
        },
        train_set=train_set,
        num_boost_round=300,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(25)],
    )

    best_iteration = booster.best_iteration or 300
    test_scores = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    preds = (test_scores >= 0.5).astype(int)
    report = classification_report(test_df[target_column], preds, output_dict=True, zero_division=0)
    confusion = confusion_matrix(test_df[target_column], preds).tolist()
    importance = sorted(
        (
            {"feature": name, "importance": int(value)}
            for name, value in zip(feature_columns, booster.feature_importance(importance_type="gain"))
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    booster.save_model(str(model_path))
    summary = {
        "dataset": str(args.dataset),
        "target": target_column,
        "status": "trained",
        "rows": split_counts,
        "positive_rows": split_positive_counts,
        "features": feature_columns,
        "best_iteration": int(best_iteration),
        "validation_source": "train_holdout_split" if generated_holdout_val else "exported_val_split",
        "test_source": "train_holdout_split" if generated_holdout_test else "exported_test_split",
        "classification_report": report,
        "confusion_matrix": confusion,
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

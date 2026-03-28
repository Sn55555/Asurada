from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "strategy_action_features_v1.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "strategy_action_baseline"
TARGET_ACTIONS = ["NONE", "LOW_FUEL", "DEFEND_WINDOW", "DYNAMICS_UNSTABLE"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the first strategy-action baseline model.")
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES, help="Path to strategy_action_features_v1.csv.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for reports and model artifacts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import lightgbm as lgb  # type: ignore
        import pandas as pd  # type: ignore
        from sklearn.metrics import classification_report, confusion_matrix, top_k_accuracy_score  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas`, `lightgbm`, and `scikit-learn` in /Users/sn5/Asurada/asurada-core/.venv before training."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.features, low_memory=False)
    if df.empty:
        raise SystemExit("Empty strategy-action dataset.")
    df = df[df["primary_action_label"].isin(TARGET_ACTIONS)].copy()
    if df.empty:
        raise SystemExit("No supported strategy-action rows after filtering.")

    numeric_features = [
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
        "front_rival_speed_delta",
        "rear_rival_speed_delta",
        "drs_available",
    ]
    categorical_features = [
        "timing_support_level",
        "session_type",
        "track_segment",
        "track_usage",
        "driving_mode",
    ]

    for column in numeric_features:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in categorical_features:
        df[column] = df[column].fillna("UNKNOWN").astype("category")

    label_to_id = {label: idx for idx, label in enumerate(TARGET_ACTIONS)}
    id_to_label = {idx: label for label, idx in label_to_id.items()}
    df["target_id"] = df["primary_action_label"].map(label_to_id)

    train_df = df[df["split"] == "train"].copy()
    val_df = df[df["split"] == "val"].copy()
    test_df = df[df["split"] == "test"].copy()
    if train_df.empty or test_df.empty:
        raise SystemExit("Missing exported train/test rows for strategy-action baseline.")

    exported_val_ok = not val_df.empty and set(val_df["target_id"].unique()) == set(train_df["target_id"].unique())
    if not exported_val_ok:
        missing_labels = sorted(set(train_df["target_id"].unique()) - set(val_df["target_id"].unique()))
        raise SystemExit(f"Exported strategy-action val split is missing target ids: {missing_labels}")

    class_weights = balanced_class_weights(train_df["target_id"].tolist())
    train_weights = [class_weights[target_id] for target_id in train_df["target_id"].tolist()]
    val_weights = [class_weights.get(target_id, 1.0) for target_id in val_df["target_id"].tolist()]
    feature_columns = numeric_features + categorical_features
    train_set = lgb.Dataset(
        train_df[feature_columns],
        label=train_df["target_id"],
        weight=train_weights,
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        val_df[feature_columns],
        label=val_df["target_id"],
        weight=val_weights,
        categorical_feature=categorical_features,
        free_raw_data=False,
    )
    params = {
        "objective": "multiclass",
        "metric": ["multi_logloss"],
        "num_class": len(TARGET_ACTIONS),
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
    test_proba = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    test_pred = test_proba.argmax(axis=1)
    test_true = test_df["target_id"].to_numpy()
    report = classification_report(
        test_true,
        test_pred,
        labels=list(id_to_label.keys()),
        target_names=[id_to_label[idx] for idx in range(len(id_to_label))],
        output_dict=True,
        zero_division=0,
    )
    confusion = confusion_matrix(test_true, test_pred, labels=list(id_to_label.keys())).tolist()
    top1 = float((test_pred == test_true).mean())
    top2 = float(top_k_accuracy_score(test_true, test_proba, k=2, labels=list(id_to_label.keys())))
    importance = sorted(
        (
            {"feature": name, "importance": int(value)}
            for name, value in zip(feature_columns, booster.feature_importance(importance_type="gain"))
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    model_path = args.output_dir / "strategy_action_model_baseline.txt"
    summary_path = args.output_dir / "strategy_action_baseline_report.json"
    booster.save_model(str(model_path))

    summary = {
        "features": str(args.features),
        "rows": {
            "all": int(len(df)),
            "train": int(len(train_df)),
            "val": int(len(val_df)),
            "test": int(len(test_df)),
        },
        "target_actions": TARGET_ACTIONS,
        "feature_columns": feature_columns,
        "best_iteration": int(best_iteration),
        "validation_source": "exported_val_split",
        "test_source": "exported_test_split",
        "top1_accuracy": top1,
        "top2_accuracy": top2,
        "classification_report": report,
        "confusion_matrix": confusion,
        "top_feature_importance": importance[:20],
        "class_weights": class_weights,
        "model_path": str(model_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def balanced_class_weights(target_ids: list[int]) -> dict[int, float]:
    counts: dict[int, int] = {}
    for target_id in target_ids:
        counts[target_id] = counts.get(target_id, 0) + 1
    total = float(sum(counts.values()))
    num_classes = float(len(TARGET_ACTIONS))
    weights: dict[int, float] = {}
    for idx in range(len(TARGET_ACTIONS)):
        class_count = max(1, counts.get(idx, 0))
        weights[idx] = total / (num_classes * class_count)
    return weights


if __name__ == "__main__":
    raise SystemExit(main())

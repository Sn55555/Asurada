from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def default_dataset_path() -> Path:
    for dataset_name in ("phase2_dataset_v2_extended", "phase2_dataset_v1"):
        candidate = PROJECT_ROOT / "training" / "exports" / dataset_name / "attack_features_v1.csv"
        if candidate.exists():
            return candidate
    return PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "attack_features_v1.csv"


DEFAULT_DATASET = default_dataset_path()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "front_attack_commit_baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the first front-attack-commit baseline model.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to attack_features_v1.csv.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for reports and model artifacts.",
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
        raise SystemExit("No attack rows available for training.")

    numeric_features = [
        "official_gap_ahead_s",
        "gap_closing_rate_ahead",
        "front_rival_speed_kph",
        "front_rival_ers_pct",
        "front_rival_speed_delta",
        "speed_kph",
        "drs_available",
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
        "attack_zone_flag",
    ]
    categorical_features = [
        "actor_view",
        "track_segment",
        "track_usage",
        "next_track_segment",
        "next_track_usage",
        "next_two_segments",
        "driving_mode",
        "session_type",
    ]
    target_column = "attack_commit_proxy_label"

    for column in numeric_features:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in categorical_features:
        df[column] = df[column].fillna("UNKNOWN").astype("category")

    train_df = df[df["split"] == "train"].copy()
    val_df = df[df["split"] == "val"].copy()
    test_df = df[df["split"] == "test"].copy()
    if train_df.empty:
        raise SystemExit("Insufficient train rows after split filtering.")

    generated_holdout_val = False
    generated_holdout_test = False
    if test_df.empty or test_df[target_column].nunique() < 2:
        generated_holdout_test = True
        train_df, test_df = train_test_split(
            train_df,
            test_size=0.2,
            random_state=42,
            stratify=train_df[target_column],
        )
    if val_df.empty or val_df[target_column].nunique() < 2:
        generated_holdout_val = True
        train_df, val_df = train_test_split(
            train_df,
            test_size=0.2,
            random_state=42,
            stratify=train_df[target_column],
        )

    feature_columns = numeric_features + categorical_features
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

    negative_count = max(1, int((train_df[target_column] == 0).sum()))
    positive_count = max(1, int((train_df[target_column] == 1).sum()))
    scale_pos_weight = negative_count / positive_count

    params = {
        "objective": "binary",
        "metric": ["binary_logloss", "auc"],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "min_data_in_leaf": 16,
        "verbosity": -1,
        "seed": 42,
        "scale_pos_weight": scale_pos_weight,
    }

    callbacks = [lgb.log_evaluation(25)]
    num_boost_round = 120 if generated_holdout_val else 300
    if not generated_holdout_val:
        callbacks.insert(0, lgb.early_stopping(30))

    booster = lgb.train(
        params=params,
        train_set=train_set,
        num_boost_round=num_boost_round,
        valid_sets=[train_set, val_set],
        valid_names=["train", "val"],
        callbacks=callbacks,
    )

    best_iteration = booster.best_iteration or num_boost_round
    val_scores = booster.predict(val_df[feature_columns], num_iteration=best_iteration)
    threshold_scan = scan_thresholds(y_true=val_df[target_column].tolist(), scores=val_scores)
    threshold = threshold_scan["selected_threshold"]

    test_scores = booster.predict(test_df[feature_columns], num_iteration=best_iteration)
    preds = (test_scores >= threshold).astype(int)

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

    model_path = args.output_dir / "front_attack_commit_model_baseline.txt"
    summary_path = args.output_dir / "front_attack_commit_baseline_report.json"
    booster.save_model(str(model_path))

    summary = {
        "dataset": str(args.dataset),
        "rows": {
            "all": int(len(df)),
            "train": int(len(train_df)),
            "val": int(len(val_df)),
            "test": int(len(test_df)),
        },
        "target": target_column,
        "label_source": "attack_commit_proxy_label",
        "features": feature_columns,
        "best_iteration": int(best_iteration),
        "validation_source": "train_holdout_split" if generated_holdout_val else "exported_val_split",
        "test_source": "train_holdout_split" if generated_holdout_test else "exported_test_split",
        "selected_threshold": threshold,
        "validation_threshold_scan": threshold_scan,
        "scale_pos_weight": scale_pos_weight,
        "classification_report": report,
        "confusion_matrix": confusion,
        "top_feature_importance": importance[:20],
        "model_path": str(model_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def scan_thresholds(*, y_true, scores) -> dict:
    best = None
    candidates = []
    for step in range(20, 81, 2):
        threshold = step / 100.0
        preds = [1 if score >= threshold else 0 for score in scores]
        tn = fp = fn = tp = 0
        for truth, pred in zip(y_true, preds):
            if truth == 1 and pred == 1:
                tp += 1
            elif truth == 1 and pred == 0:
                fn += 1
            elif truth == 0 and pred == 1:
                fp += 1
            else:
                tn += 1
        positive_precision = tp / (tp + fp) if (tp + fp) else 0.0
        positive_recall = tp / (tp + fn) if (tp + fn) else 0.0
        negative_precision = tn / (tn + fn) if (tn + fn) else 0.0
        negative_recall = tn / (tn + fp) if (tn + fp) else 0.0
        positive_f1 = (
            2 * positive_precision * positive_recall / (positive_precision + positive_recall)
            if (positive_precision + positive_recall)
            else 0.0
        )
        negative_f1 = (
            2 * negative_precision * negative_recall / (negative_precision + negative_recall)
            if (negative_precision + negative_recall)
            else 0.0
        )
        macro_f1 = (positive_f1 + negative_f1) / 2
        accuracy = (tp + tn) / len(y_true) if y_true else 0.0
        row = {
            "threshold": threshold,
            "macro_f1": macro_f1,
            "positive_precision": positive_precision,
            "positive_recall": positive_recall,
            "accuracy": accuracy,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        }
        candidates.append(row)
        if best is None:
            best = row
            continue
        if row["macro_f1"] > best["macro_f1"]:
            best = row
            continue
        if row["macro_f1"] == best["macro_f1"] and row["positive_recall"] > best["positive_recall"]:
            best = row

    top_candidates = sorted(candidates, key=lambda item: (item["macro_f1"], item["positive_recall"]), reverse=True)[:8]
    return {
        "selected_threshold": best["threshold"] if best else 0.5,
        "selected_metrics": best,
        "top_candidates": top_candidates,
    }


if __name__ == "__main__":
    raise SystemExit(main())

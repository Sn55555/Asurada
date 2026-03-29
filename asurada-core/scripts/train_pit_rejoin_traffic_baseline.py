from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "pit_rejoin_traffic_baseline"

REQUIRED_FIELDS = [
    "pit_status",
    "pit_status_code",
    "pit_status_previous",
    "pit_status_transition",
    "pit_entry_event",
    "pit_exit_event",
    "pit_rejoin_phase",
    "player_position",
    "official_gap_ahead_s",
    "official_gap_behind_s",
    "lap_number",
    "session_time_s",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check/train pit rejoin traffic baseline.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Path to features.csv.")
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
        import pandas as pd  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise SystemExit(
            f"Missing dependency: {missing}. Install `pandas` in /Users/sn5/Asurada/asurada-core/.venv before running."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.dataset, low_memory=False)
    available_fields = df.columns.tolist()
    missing_fields = [field for field in REQUIRED_FIELDS if field not in available_fields]

    pit_status_counts = {}
    pit_transition_counts = {}
    pit_rejoin_phase_counts = {}
    candidate_rows = {}
    traffic_band_counts = {}
    split_candidate_counts = {}
    if not missing_fields:
        full_df = df.copy()
        for column in ["official_gap_ahead_s", "official_gap_behind_s", "session_time_s", "lap_number"]:
            full_df[column] = pd.to_numeric(full_df[column], errors="coerce")
        pit_status_counts = full_df["pit_status"].fillna("NONE").value_counts().to_dict()
        pit_transition_counts = (
            full_df["pit_status_transition"].fillna("stable").value_counts().head(12).to_dict()
        )
        pit_rejoin_phase_counts = (
            full_df["pit_rejoin_phase"].fillna("none").value_counts().to_dict()
        )
        full_df["traffic_band"] = full_df.apply(assign_traffic_band, axis=1)
        candidate_df = full_df[full_df["pit_rejoin_phase"].isin(["pit_exit", "rejoin_window"])].copy()
        candidate_rows = {
            "all": int(len(candidate_df)),
            "pit_exit": int((candidate_df["pit_rejoin_phase"] == "pit_exit").sum()),
            "rejoin_window": int((candidate_df["pit_rejoin_phase"] == "rejoin_window").sum()),
        }
        traffic_band_counts = candidate_df["traffic_band"].fillna("unknown").value_counts().to_dict()
        split_candidate_counts = (
            candidate_df.groupby("split")["pit_rejoin_phase"].count().to_dict() if not candidate_df.empty else {}
        )
        if candidate_df.empty:
            status = "blocked_no_rejoin_candidate_rows"
            blocking_reason = "Pit-state export exists, but current samples do not contain pit-exit or rejoin-window rows with track traffic context."
        else:
            status = "ready_for_sampling"
            blocking_reason = "Required pit-state and transition fields are present; proceed to pit-rejoin sample/label design."
    else:
        status = "blocked_missing_required_fields"
        blocking_reason = "Current exported features do not include pit entry/rejoin state transitions, so pit-rejoin traffic labels cannot be built."

    summary = {
        "dataset": str(args.dataset),
        "status": status,
        "required_fields": REQUIRED_FIELDS,
        "missing_fields": missing_fields,
        "blocking_reason": blocking_reason,
        "notes": [
            "pit_rejoin_traffic_model depends on explicit pit-state transitions and post-stop traffic bands.",
            "Pit-state export exists; next step is to identify pit-entry, pit-exit, and rejoin-window rows with usable traffic bands.",
        ],
        "pit_status_counts": pit_status_counts,
        "pit_transition_counts": pit_transition_counts,
        "pit_rejoin_phase_counts": pit_rejoin_phase_counts,
        "candidate_rows": candidate_rows,
        "traffic_band_counts": traffic_band_counts,
        "split_candidate_counts": split_candidate_counts,
    }
    output_path = args.output_dir / "pit_rejoin_traffic_baseline_report.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def assign_traffic_band(row) -> str:
    gaps = [
        value
        for value in [
            row.get("official_gap_ahead_s"),
            row.get("official_gap_behind_s"),
        ]
        if value is not None and value == value
    ]
    if not gaps:
        return "unknown"
    nearest_gap = min(abs(float(value)) for value in gaps)
    if nearest_gap <= 1.5:
        return "heavy"
    if nearest_gap <= 3.0:
        return "medium"
    return "light"


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v1" / "features.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "training" / "reports" / "pit_rejoin_traffic_baseline"

REQUIRED_FIELDS = [
    "pit_status",
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
    df = pd.read_csv(args.dataset, nrows=10)
    available_fields = df.columns.tolist()
    missing_fields = [field for field in REQUIRED_FIELDS if field not in available_fields]

    summary = {
        "dataset": str(args.dataset),
        "status": "blocked_missing_required_fields" if missing_fields else "ready_for_sampling",
        "required_fields": REQUIRED_FIELDS,
        "missing_fields": missing_fields,
        "blocking_reason": (
            "Current exported features do not include pit entry/rejoin state, so pit-rejoin traffic labels cannot be built."
            if missing_fields
            else "Required fields present; proceed to sample/label design."
        ),
        "notes": [
            "pit_rejoin_traffic_model depends on explicit pit-state transitions and post-stop traffic bands.",
            "Do not train from current features.csv until pit-state export exists.",
        ],
    }
    output_path = args.output_dir / "pit_rejoin_traffic_baseline_report.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

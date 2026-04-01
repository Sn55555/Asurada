from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_phase2_training_data import export_dataset
from scripts.extract_session_samples import SessionClassification, extract_samples, write_metadata
from scripts.validate_local_extended_dataset import validate_local_extended_dataset


LOCAL_CAPTURE_CLASSIFICATIONS: dict[str, SessionClassification] = {
    "3466132923986383695": SessionClassification(
        session_uid="3466132923986383695",
        sample_name="suzuka_sprint_race_like_uid15",
        session_type_code=15,
        session_label="SprintRaceLike(15)",
        confidence="medium",
        reason="Split from mixed capture jsonl by session_uid; official-preferred race-like Suzuka sample ready for training intake.",
    ),
    "9372756052161398147": SessionClassification(
        session_uid="9372756052161398147",
        sample_name="shanghai_feature_race_like_uid16_20lap",
        session_type_code=16,
        session_label="FeatureRaceLike(16)",
        confidence="medium",
        reason="Split from mixed capture jsonl by session_uid; official-preferred race-like Shanghai sample ready for training intake.",
    ),
}

DEFAULT_CAPTURE_PATH = PROJECT_ROOT / "data" / "capture_samples" / "f1_25_udp_capture_20260329_190623"
DEFAULT_SPLIT_OUTPUT_DIR = PROJECT_ROOT / "data" / "capture_samples" / "f1_25_udp_capture_20260329_190623"
DEFAULT_BASE_METADATA = PROJECT_ROOT / "data" / "capture_samples" / "shanghai_race_weekend" / "metadata.json"
DEFAULT_COMBINED_METADATA = PROJECT_ROOT / "data" / "capture_samples" / "phase2_metadata_combined.json"
DEFAULT_DATASET_CONFIG = PROJECT_ROOT / "training" / "configs" / "phase2_dataset_v2_extended.json"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v2_extended"
DEFAULT_VALIDATION_REPORT = REPO_ROOT / "tmp" / "local_extended_dataset_validation.json"
DEFAULT_QUICK_EXPORT_METADATA = REPO_ROOT / "tmp" / "local_extended_dataset_quick_metadata.json"

DEFAULT_SAMPLE_SPLITS = {
    "shanghai_qualifying_like_uid13": "train",
    "shanghai_sprint_race_like_uid15": "train",
    "shanghai_short_result_like_uid8": "val",
    "shanghai_feature_race_like_uid16": "test",
    "suzuka_sprint_race_like_uid15": "train",
    "shanghai_feature_race_like_uid16_20lap": "train",
}

QUICK_VALIDATION_SAMPLE_NAMES = [
    "shanghai_qualifying_like_uid13",
    "shanghai_short_result_like_uid8",
    "shanghai_feature_race_like_uid16",
    "suzuka_sprint_race_like_uid15",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the local-only phase-two extended dataset workflow.")
    parser.add_argument(
        "--capture-source",
        type=Path,
        default=DEFAULT_CAPTURE_PATH,
        help="Raw mixed capture jsonl or a directory containing it.",
    )
    parser.add_argument(
        "--split-output-dir",
        type=Path,
        default=DEFAULT_SPLIT_OUTPUT_DIR,
        help="Directory where split session jsonl files and metadata.json will be refreshed.",
    )
    parser.add_argument(
        "--base-metadata",
        type=Path,
        default=DEFAULT_BASE_METADATA,
        help="Existing base metadata json used as the starting sample set.",
    )
    parser.add_argument(
        "--combined-metadata",
        type=Path,
        default=DEFAULT_COMBINED_METADATA,
        help="Combined metadata json for the local extended dataset.",
    )
    parser.add_argument(
        "--dataset-config",
        type=Path,
        default=DEFAULT_DATASET_CONFIG,
        help="Local phase-two extended dataset config path.",
    )
    parser.add_argument(
        "--export-output-dir",
        type=Path,
        default=DEFAULT_EXPORT_DIR,
        help="Exporter output directory.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=0,
        help="Optional frame limit per sample during export. 0 means full export.",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Only refresh samples/config/metadata and skip exporter + validation export pass.",
    )
    parser.add_argument(
        "--validation-report",
        type=Path,
        default=DEFAULT_VALIDATION_REPORT,
        help="Where to write the local validation summary JSON.",
    )
    parser.add_argument(
        "--validation-profile",
        choices=("full", "quick"),
        default="full",
        help="Use full combined metadata export or a smaller representative subset for validation export.",
    )
    parser.add_argument(
        "--skip-split",
        action="store_true",
        help="Reuse existing split jsonl files and split metadata instead of re-reading the mixed raw capture.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.split_output_dir.mkdir(parents=True, exist_ok=True)
    split_metadata_path = args.split_output_dir / "metadata.json"
    capture_jsonl: Path | None = None
    if args.skip_split:
        if not split_metadata_path.exists():
            raise SystemExit(f"Cannot use --skip-split because split metadata is missing: {split_metadata_path}")
        split_records = list(json.loads(split_metadata_path.read_text(encoding="utf-8")).get("samples", []))
    else:
        capture_jsonl = resolve_capture_jsonl(args.capture_source)
        split_records = extract_samples(
            capture_path=capture_jsonl,
            output_dir=args.split_output_dir,
            classifications=LOCAL_CAPTURE_CLASSIFICATIONS,
        )
        write_metadata(split_records, split_metadata_path)

    combined_metadata = build_combined_metadata(
        base_metadata_path=args.base_metadata,
        split_records=split_records,
    )
    write_metadata(combined_metadata, args.combined_metadata)

    dataset_config = build_dataset_config(
        combined_metadata_path=args.combined_metadata,
        sample_splits=DEFAULT_SAMPLE_SPLITS,
    )
    write_json(args.dataset_config, dataset_config)

    export_report: dict[str, Any] | None = None
    export_metadata_path = args.combined_metadata
    if not args.skip_export:
        args.export_output_dir.mkdir(parents=True, exist_ok=True)
        if args.validation_profile == "quick":
            export_metadata_path = DEFAULT_QUICK_EXPORT_METADATA
            quick_metadata = select_validation_samples(
                combined_metadata=combined_metadata,
                sample_names=QUICK_VALIDATION_SAMPLE_NAMES,
            )
            write_metadata(quick_metadata, export_metadata_path)
        export_report = export_dataset(
            sample_metadata_path=export_metadata_path,
            output_dir=args.export_output_dir,
            sample_splits=dict(dataset_config["sample_splits"]),
            next_segment_offsets=[float(item) for item in dataset_config.get("next_segment_offsets_m", [120.0, 280.0])],
            max_history_frames=int(dataset_config.get("max_history_frames", 12)),
            sample_limit=args.sample_limit if args.sample_limit > 0 else None,
        )
        write_json(args.export_output_dir / "manifest.json", export_report)

    validation = validate_local_extended_dataset(
        dataset_config_path=args.dataset_config,
        export_output_dir=args.export_output_dir,
        run_export=False,
        export_metadata_path=export_metadata_path if not args.skip_export else None,
    )
    args.validation_report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.validation_report, validation)

    summary = {
        "capture_jsonl": str(capture_jsonl) if capture_jsonl else None,
        "split_metadata_path": str(split_metadata_path),
        "combined_metadata_path": str(args.combined_metadata),
        "dataset_config_path": str(args.dataset_config),
        "export_output_dir": str(args.export_output_dir),
        "validation_report_path": str(args.validation_report),
        "split_sample_names": [record["sample_name"] for record in split_records],
        "split_refreshed": not args.skip_split,
        "export_ran": not args.skip_export,
        "validation_profile": args.validation_profile,
        "validation_ok": bool(validation.get("ok")),
        "export_manifest_path": str(args.export_output_dir / "manifest.json") if export_report else None,
        "export_metadata_path": str(export_metadata_path) if export_report else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def resolve_capture_jsonl(source: Path) -> Path:
    if source.is_file():
        return source
    if not source.is_dir():
        raise SystemExit(f"Capture source does not exist: {source}")
    candidates = sorted(
        [
            item
            for item in source.glob("*.jsonl")
            if item.name != "metadata.json"
            and item.name not in {f"{classification.sample_name}.jsonl" for classification in LOCAL_CAPTURE_CLASSIFICATIONS.values()}
        ],
        key=lambda item: item.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"No mixed capture jsonl found in directory: {source}")
    return candidates[0]


def build_combined_metadata(*, base_metadata_path: Path, split_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_metadata = json.loads(base_metadata_path.read_text(encoding="utf-8"))
    base_samples = list(base_metadata.get("samples", []))
    split_names = {record["sample_name"] for record in split_records}
    merged = [sample for sample in base_samples if sample["sample_name"] not in split_names]
    merged.extend(split_records)
    return merged


def build_dataset_config(*, combined_metadata_path: Path, sample_splits: dict[str, str]) -> dict[str, Any]:
    return {
        "dataset_name": "phase2_dataset_v2_extended",
        "sample_metadata_path": str(combined_metadata_path),
        "sample_splits": dict(sample_splits),
        "next_segment_offsets_m": [120.0, 280.0],
        "max_history_frames": 12,
    }


def select_validation_samples(*, combined_metadata: list[dict[str, Any]], sample_names: list[str]) -> list[dict[str, Any]]:
    selected = [sample for sample in combined_metadata if sample["sample_name"] in set(sample_names)]
    if len(selected) != len(sample_names):
        missing = sorted(set(sample_names) - {sample["sample_name"] for sample in selected})
        raise SystemExit(f"Quick validation sample selection is missing samples: {missing}")
    return selected


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

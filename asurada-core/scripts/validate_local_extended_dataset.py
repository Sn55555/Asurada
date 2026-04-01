from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

DEFAULT_DATASET_CONFIG = PROJECT_ROOT / "training" / "configs" / "phase2_dataset_v2_extended.json"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "training" / "exports" / "phase2_dataset_v2_extended"

TRAINING_SCRIPT_PATHS = {
    "rear_threat": PROJECT_ROOT / "scripts" / "train_rear_threat_baseline.py",
    "attack_opportunity": PROJECT_ROOT / "scripts" / "train_attack_opportunity_baseline.py",
    "front_attack_commit": PROJECT_ROOT / "scripts" / "train_front_attack_commit_baseline.py",
    "strategy_action": PROJECT_ROOT / "scripts" / "train_strategy_action_baseline.py",
}

EXPECTED_EXPORT_FILES = [
    "features.csv",
    "labels.csv",
    "tactical_features_v1.csv",
    "attack_features_v1.csv",
    "strategy_action_features_v1.csv",
    "manifest.json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the local-only phase-two extended dataset workflow.")
    parser.add_argument("--dataset-config", type=Path, default=DEFAULT_DATASET_CONFIG, help="Local dataset config JSON.")
    parser.add_argument(
        "--export-output-dir",
        type=Path,
        default=DEFAULT_EXPORT_DIR,
        help="Export output directory to validate.",
    )
    parser.add_argument(
        "--run-export",
        action="store_true",
        help="Run the exporter before validating artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_local_extended_dataset(
        dataset_config_path=args.dataset_config,
        export_output_dir=args.export_output_dir,
        run_export=args.run_export,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def validate_local_extended_dataset(
    *,
    dataset_config_path: Path,
    export_output_dir: Path,
    run_export: bool,
    export_metadata_path: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    config_exists = dataset_config_path.exists()
    checks.append(_check("dataset_config_exists", config_exists, path=str(dataset_config_path)))
    if not config_exists:
        return {"ok": False, "checks": checks}

    config = json.loads(dataset_config_path.read_text(encoding="utf-8"))
    metadata_path = Path(config["sample_metadata_path"])
    metadata_exists = metadata_path.exists()
    checks.append(_check("metadata_exists", metadata_exists, path=str(metadata_path)))
    if not metadata_exists:
        return {"ok": False, "checks": checks}

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    samples = list(metadata.get("samples", []))
    sample_splits = dict(config.get("sample_splits", {}))

    missing_sample_files = [
        sample["sample_name"]
        for sample in samples
        if not Path(sample["file_path"]).exists() or Path(sample["file_path"]).stat().st_size == 0
    ]
    checks.append(
        _check(
            "metadata_sample_files_exist",
            not missing_sample_files,
            missing_samples=missing_sample_files,
        )
    )

    missing_sample_splits = [
        sample["sample_name"]
        for sample in samples
        if sample["sample_name"] not in sample_splits
    ]
    checks.append(
        _check(
            "sample_splits_complete",
            not missing_sample_splits,
            missing_samples=missing_sample_splits,
        )
    )

    effective_export_metadata_path = export_metadata_path or metadata_path

    if run_export:
        from scripts.export_phase2_training_data import export_dataset

        export_output_dir.mkdir(parents=True, exist_ok=True)
        report = export_dataset(
            sample_metadata_path=effective_export_metadata_path,
            output_dir=export_output_dir,
            sample_splits=sample_splits,
            next_segment_offsets=[float(item) for item in config.get("next_segment_offsets_m", [120.0, 280.0])],
            max_history_frames=int(config.get("max_history_frames", 12)),
            sample_limit=None,
        )
        (export_output_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    missing_exports = [name for name in EXPECTED_EXPORT_FILES if not (export_output_dir / name).exists()]
    checks.append(
        _check(
            "export_artifacts_exist",
            not missing_exports,
            export_output_dir=str(export_output_dir),
            missing_files=missing_exports,
        )
    )

    manifest_path = export_output_dir / "manifest.json"
    manifest_ok = False
    manifest_summary: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_ok = bool(manifest.get("record_count", 0)) and bool(manifest.get("attack_record_count", 0)) and bool(
            manifest.get("strategy_action_record_count", 0)
        )
        manifest_summary = {
            "dataset_name": manifest.get("dataset_name"),
            "record_count": manifest.get("record_count"),
            "attack_record_count": manifest.get("attack_record_count"),
            "strategy_action_record_count": manifest.get("strategy_action_record_count"),
        }
    checks.append(_check("export_manifest_valid", manifest_ok, **manifest_summary))

    training_resolution: dict[str, Any] = {}
    preferred_training_ok = True
    for key, script_path in TRAINING_SCRIPT_PATHS.items():
        module = load_script_module(script_path)
        resolved_path = resolve_training_input_path(module)
        training_resolution[key] = {
            "script": str(script_path),
            "resolved_path": str(resolved_path) if resolved_path else None,
        }
        if resolved_path is None or "phase2_dataset_v2_extended" not in str(resolved_path):
            preferred_training_ok = False
    checks.append(_check("training_scripts_prefer_v2_extended", preferred_training_ok, scripts=training_resolution))

    return {
        "ok": all(check["ok"] for check in checks),
        "dataset_config_path": str(dataset_config_path),
        "metadata_path": str(metadata_path),
        "export_metadata_path": str(effective_export_metadata_path),
        "export_output_dir": str(export_output_dir),
        "checks": checks,
    }


def load_script_module(script_path: Path) -> Any:
    module_name = f"_local_validation_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_training_input_path(module: Any) -> Path | None:
    for attribute in ("DEFAULT_DATASET", "DEFAULT_FEATURES"):
        value = getattr(module, attribute, None)
        if value is not None:
            return Path(value)
    return None


def _check(name: str, ok: bool, **details: Any) -> dict[str, Any]:
    payload = {"name": name, "ok": ok}
    payload.update(details)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())

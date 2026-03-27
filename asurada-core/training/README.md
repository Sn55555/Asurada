# Phase Two Training Workspace

This directory holds phase-two dataset definitions, export configs, and generated training artifacts.

## Layout

```text
training/
  README.md
  configs/
    phase2_dataset_v1.json
  exports/
    <generated at runtime, ignored by git>
```

## Purpose

- define deterministic dataset splits for stage-two work
- export flat feature tables from normalized capture replay
- export first-pass pseudo-label tables from the existing strategy/debug chain
- keep dataset generation reproducible and separate from runtime logs

## Current Dataset Entry Point

Use:

```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python3 scripts/export_phase2_training_data.py
```

Default inputs:

- sample metadata:
  - [metadata.json](/Users/sn5/Asurada/asurada-core/data/capture_samples/shanghai_race_weekend/metadata.json)
- dataset config:
  - [phase2_dataset_v1.json](/Users/sn5/Asurada/asurada-core/training/configs/phase2_dataset_v1.json)

Default outputs:

- `training/exports/phase2_dataset_v1/features.csv`
- `training/exports/phase2_dataset_v1/labels.csv`
- `training/exports/phase2_dataset_v1/tactical_features_v1.csv`
- `training/exports/phase2_dataset_v1/manifest.json`

## Tactical Feature View

`tactical_features_v1.csv` is the first focused export for:

- `rear_threat`
- `defend`
- `counterattack`

It only keeps rows and fields that are stable enough for the first stage-two tactical baselines:

- official timing / gap fields
- relative pace and closing-rate features
- tactical context and next-segment features
- first-pass pseudo labels for rear-threat and yield-vs-fight decisions

## First Baseline Training

Use:

```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python3 scripts/train_rear_threat_baseline.py
```

Outputs:

- `training/reports/rear_threat_baseline/rear_threat_model_baseline.txt`
- `training/reports/rear_threat_baseline/rear_threat_baseline_report.json`

## Notes

- `features.csv` only contains fields that already exist in normalized snapshots or can be stably derived from the current rolling window.
- `labels.csv` currently exports first-pass pseudo labels from the existing strategy pipeline and simple event/state transitions.
- `tactical_features_v1.csv` only promotes official timing fields into tactical training features. `estimated_*` timing is left in the export for debug inspection, not as a primary model signal.
- `estimated_*` timing fields are exported for debug only. They are not intended for primary model training.
- The first baseline depends on local training packages inside `.venv`:
  - `pandas`
  - `lightgbm`
  - `scikit-learn`

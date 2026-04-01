# Asurada Core

Asurada Core is the strategy-brain backend workspace that sits alongside the app project.

This workspace owns the backend-side real-time data path:
- raw input ingest
- packet decoding and frame assembly
- normalized state model
- layered strategy engine
- replay logging and debug dashboard
- lap analysis and structured report output

See also:
- [doc/README.md](doc/README.md)
- [STATUS.md](STATUS.md)
- [PHASE1_ACCEPTANCE.md](PHASE1_ACCEPTANCE.md)
- [PHASE1_CLOSEOUT.md](PHASE1_CLOSEOUT.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CORE_WORKFLOW_CN.md](CORE_WORKFLOW_CN.md)
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](STAGE2_MODEL_INPUT_SCHEMA.md)
- [PHASE2_MODEL_MATRIX_CN.md](PHASE2_MODEL_MATRIX_CN.md)
- [training/README.md](training/README.md)
- [SESSION_TYPE_CLASSIFICATION.md](SESSION_TYPE_CLASSIFICATION.md)
- [PARSED_FIELDS_AND_MODEL_USAGE_CN.md](PARSED_FIELDS_AND_MODEL_USAGE_CN.md)
- [REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md](REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md)
- [STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md](STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md)
- [STAGE3_VOICE_MODULE_PLAN_CN.md](STAGE3_VOICE_MODULE_PLAN_CN.md)
- [PROJECT_TIMELINE_AND_RISKS_CN.md](PROJECT_TIMELINE_AND_RISKS_CN.md)
- [PHASE2_DEBUG_DASHBOARD_CN.md](PHASE2_DEBUG_DASHBOARD_CN.md)

## Current Inputs

- replay JSONL input
- single-lap CSV input
- captured UDP JSONL replay input
- live UDP listener shell for future F1 25 PDU packets

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .

python3 main.py --demo
python3 main.py --csv /Users/sn5/asurada_simulator/tools/f1_recorder/data/20260319_015115_shanghai_lap.csv
python3 main.py --capture-jsonl /Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl
python3 main.py --live-udp --udp-port 20778
python3 main.py --build-dashboard
```

## Current Layout

```text
data/             sample inputs, track models, strategy config
doc/              project documents
src/asurada/      core package
runtime_logs/     replay logs, reports, dashboard output
```

## Runtime Modes

- `--demo`
  - replay the bundled normalized sample session
- `--csv`
  - run the recorder CSV single-lap prototype path
- `--capture-jsonl`
  - replay raw UDP capture JSONL through the real decode pipeline
- `--live-udp`
  - start the live UDP listener shell
- `--build-dashboard`
  - rebuild the HTML debug dashboard from `runtime_logs/session_log.jsonl`

## Core Modules

- `capture_ingest.py`
  - reads raw captured UDP packets from JSONL
- `pdu_decoder.py`
  - decodes F1 25 headers and validated packet body fields
- `packet_snapshot.py`
  - assembles multi-packet frames into one normalized snapshot
- `decode.py`
  - converts normalized snapshot dicts into internal dataclasses
- `state.py`
  - keeps the rolling in-memory state window
- `strategy.py`
  - runs the layered strategy pipeline
- `track_model.py`
  - applies Shanghai semantic segments and usage labels
- `replay.py`
  - writes append-only JSONL runtime logs
- `dashboard.py`
  - generates the local debug dashboard
- `analysis.py`
  - builds single-lap review summaries and segment analysis

## Strategy Pipeline

The strategy engine is layered into:

1. state assessment
2. risk scoring
3. strategy candidate generation
4. arbitration

The outward-facing messages stay simple, while the debug payload keeps:
- context profile
- state assessment
- risk profile
- candidates before arbitration

This is the basis for dashboard inspection, replay tuning, and future HUD integration.

## Track Semantics And Usage Hooks

Shanghai currently uses a semantic track model with:
- segment names
- zone types
- usage labels

Example usages:
- `primary_overtake_deploy`
- `front_tyre_protection`
- `maximum_brake_pressure`
- `throttle_stabilize`

Usage weights are configurable in:
- [data/strategy/usage_hooks.json](data/strategy/usage_hooks.json)

The strategy engine reads these values at startup, so tuning no longer requires editing code.

## Debug Outputs

Main runtime artifacts:
- `runtime_logs/session_log.jsonl`
  - append-only normalized replay and strategy log
- `runtime_logs/reports/*.json`
  - structured lap reports
- `runtime_logs/dashboard/debug_dashboard.html`
  - local debug dashboard with frame browser, segment heatmap, and strategy review

## Regression Check

Fixed-sample phase-one regression:
```bash
python3 scripts/phase1_regression.py --snapshot-limit 400
```

Artifact:
- `runtime_logs/regression/latest_phase1_regression.json`
  - full-capture health summary and per-session semantic assertions

## Phase Two Dataset Export

Build the first-pass phase-two feature and label tables from extracted session samples:

```bash
python3 scripts/export_phase2_training_data.py
```

Artifacts:
- `training/exports/phase2_dataset_v1/features.csv`
- `training/exports/phase2_dataset_v1/labels.csv`
- `training/exports/phase2_dataset_v1/tactical_features_v1.csv`
- `training/exports/phase2_dataset_v1/manifest.json`

Train the first rear-threat baseline:

```bash
python3 scripts/train_rear_threat_baseline.py
```

Artifacts:
- `training/reports/rear_threat_baseline/rear_threat_model_baseline.txt`
- `training/reports/rear_threat_baseline/rear_threat_baseline_report.json`

## Session Samples

Extract reusable per-session stage-two samples from the full Shanghai race-weekend capture:

```bash
python3 scripts/extract_session_samples.py
```

Artifacts:
- `data/capture_samples/shanghai_race_weekend/*.jsonl`
  - raw packet subsets split by `session_uid`
- `data/capture_samples/shanghai_race_weekend/metadata.json`
  - classification, confidence, packet counts, event counts, and final result summary

For stage-two feature work, use:
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
  - packet families, normalized fields, raw branches, and current parsing boundaries
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)
  - fields and packet families that still need protocol refinement or naming
- [STAGE2_MODEL_INPUT_SCHEMA.md](STAGE2_MODEL_INPUT_SCHEMA.md)
  - recommended model input schema, feature groups, units, ranges, and training views

## Next Step

Continue expanding the real F1 25 PDU parser, especially richer rival-state reconstruction and more validated packet bodies.

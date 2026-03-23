# Phase 1 Acceptance

## Scope

This acceptance note covers Phase 1 with one explicit boundary:
- real-time live closed-loop validation is excluded in the current environment

Everything else in Phase 1 is expected to be reviewable from the M5 Mac development workspace.

## Phase 1 Goal

Phase 1 is considered complete when the project can demonstrate:
- normalized data ingest
- real packet decode and frame assembly
- unified state flow
- layered strategy reasoning
- driver-dynamics prototype output
- replay logging
- dashboard-based debug review
- lap report generation

## Accepted Input Paths

### Normalized Replay

Command:
```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python main.py --demo
```

Expected result:
- console strategy output
- layered debug remarks
- `runtime_logs/session_log.jsonl` updated

### Single-Lap CSV

Command:
```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python main.py --csv /Users/sn5/asurada_simulator/tools/f1_recorder/data/20260319_015115_shanghai_lap.csv
```

Expected result:
- lap summary printed
- dynamics phase summary printed
- driver style tags printed
- JSON lap report written to `runtime_logs/reports/`

### Raw Capture Replay

Command:
```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python main.py --capture-jsonl /Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl
```

Expected result:
- real packet decode path exercised
- normalized snapshots created
- strategy output emitted for high-priority moments
- dashboard source log updated

## Required Artifacts

### Replay Log

File:
- `runtime_logs/session_log.jsonl`

Must contain:
- normalized player state
- rival state
- raw packet-derived fields
- strategy messages
- layered debug payload

### Debug Dashboard

Build:
```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python main.py --build-dashboard
```

File:
- `runtime_logs/dashboard/debug_dashboard.html`

Must show:
- latest state
- track usage
- frame browser
- segment heatmap
- rival overview
- message statistics

### Lap Report

Directory:
- `runtime_logs/reports/`

Must contain:
- structured JSON output
- top risk segments
- deployment segments
- dynamics phase summary
- driver style summary

## Phase 1 Functional Acceptance

### Strategy Engine

Must support:
- state assessment
- risk scoring
- candidate generation
- arbitration

Must expose debug layers for:
- context
- assessment
- risk profile
- candidates

### Track Semantics

Must support:
- Shanghai semantic segments
- zone classification
- usage labels
- usage hook configuration

### Driver Dynamics Prototype

Must provide:
- unstable detection
- front-load detection
- heavy-braking tagging
- entry / apex / exit phase summary
- driver style summary tags

## Explicit Phase 1 Boundary

The following item is not part of this acceptance in the current environment:
- live UDP end-to-end closed-loop runtime

Current status:
- live UDP listener shell exists
- full real-time runtime integration is deferred until environment constraints are removed

## Acceptance Status

Phase 1 is accepted when all commands above run successfully and all required artifacts are generated from the current workspace.

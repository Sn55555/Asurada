# Asurada Workspace

Asurada is a multi-part workspace for the racing strategy-brain project.

This repository root currently acts as the top-level container for:

- [asurada-core](/Users/sn5/Asurada/asurada-core)
  - backend strategy brain
  - packet decoding
  - normalized state model
  - layered strategy engine
  - replay logging and debug dashboard
- [ios-racetrack-analytics](/Users/sn5/Asurada/ios-racetrack-analytics)
  - app-side project workspace
- [tools](/Users/sn5/Asurada/tools)
  - capture files, utilities, and external data assets
- [doc](/Users/sn5/Asurada/doc)
  - exported project documents

## Current Tracking Scope

The repository currently commits the backend workspace in:

- [asurada-core](/Users/sn5/Asurada/asurada-core)

The other top-level directories are present locally, but are not yet part of the committed project history by default.

## Main Entry

If you are working on the strategy brain, start here:

- [asurada-core/README.md](/Users/sn5/Asurada/asurada-core/README.md)

Important backend project documents:

- [asurada-core/STATUS.md](/Users/sn5/Asurada/asurada-core/STATUS.md)
- [asurada-core/ARCHITECTURE.md](/Users/sn5/Asurada/asurada-core/ARCHITECTURE.md)
- [asurada-core/PHASE1_ACCEPTANCE.md](/Users/sn5/Asurada/asurada-core/PHASE1_ACCEPTANCE.md)
- [asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md](/Users/sn5/Asurada/asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md)
- [asurada-core/SESSION_TYPE_CLASSIFICATION.md](/Users/sn5/Asurada/asurada-core/SESSION_TYPE_CLASSIFICATION.md)

## Workspace Layout

```text
Asurada/
├── asurada-core/              backend strategy brain workspace
├── ios-racetrack-analytics/   app workspace
├── tools/                     captures and external utilities
├── doc/                       exported project documents
├── tmp/                       local temporary files
└── .derived-data/             local build artifacts
```

## Backend Quick Start

```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate

python main.py --demo
python main.py --csv /Users/sn5/asurada_simulator/tools/f1_recorder/data/20260319_015115_shanghai_lap.csv
python main.py --capture-jsonl /Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl
python main.py --build-dashboard
```

## Notes

- Root-level `.gitignore` only excludes obvious local artifacts.
- `asurada-core/.gitignore` manages backend-specific ignores such as `.venv/` and `runtime_logs/`.
- Large extracted per-session capture samples are intentionally not committed; only their metadata is tracked in `asurada-core`.

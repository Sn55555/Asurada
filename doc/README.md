# Asurada

Asurada is the project skeleton for a racing strategy brain focused on:

- real-time telemetry ingest
- unified session state
- strategy inference
- voice/HUD output adapters
- replay logging
- reliability-ready runtime boundaries

## Current Scope

This repository now contains the Phase 1 backbone:

- ingest interface with replay source
- CSV lap ingest for single-car time trial analysis
- decoder for normalized session snapshots
- unified state store
- strategy engine with core alerts
- console voice adapter
- replay logger
- runnable app loop

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
asurada --demo
python3 main.py --csv /Users/sn5/asurada_simulator/tools/f1_recorder/data/20260319_015115_shanghai_lap.csv
```

## Repository Layout

```text
doc/                    project documents
src/asurada/            application package
data/                   sample replay input
```

## Next Build Targets

1. Add F1 25 UDP packet adapters.
2. Expand strategy rules for pit, ERS, tyre and fuel.
3. Split outputs into voice, HUD and remote control channels.
4. Introduce async runtime and health monitoring.

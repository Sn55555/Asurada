# Asurada Core Architecture

## Scope

This document describes the engineering view of Asurada Core:
- input paths
- packet decoding and frame assembly
- normalized state flow
- layered strategy execution
- runtime outputs
- configuration boundaries

It is intended for maintenance and extension work inside the backend workspace.

See also:
- [doc/README.md](doc/README.md)
  - layered reading path for overview, data, strategy, models, runtime, and training
- [CORE_WORKFLOW_CN.md](CORE_WORKFLOW_CN.md)
  - end-to-end flow from data source to model, arbitration, and user-facing output
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
  - current packet families, high-value parsed fields, and stage-two raw feature branches

## System Flow

```text
raw input
  -> source adapters
  -> packet decode / row normalize
  -> normalized snapshot
  -> SessionState
  -> state store
  -> strategy engine
  -> replay log / console output / dashboard / lap report
```

## Input Paths

Asurada Core currently supports four input modes.

### 1. Normalized Replay

Files:
- `src/asurada/ingest.py`
- `src/asurada/decode.py`

Purpose:
- fastest path for replaying already-normalized snapshots
- used for demo runs and quick strategy regression

Flow:
```text
JSONL replay -> ReplaySource -> decode_snapshot() -> SessionState
```

### 2. Single-Lap CSV

Files:
- `src/asurada/csv_ingest.py`
- `src/asurada/analysis.py`

Purpose:
- prototype path for recorder CSV exports
- single-car, single-lap dynamic analysis

Flow:
```text
CSV rows -> LapCsvSource -> normalized snapshot -> SessionState
```

Boundary:
- no multi-car race context
- no official packet semantics
- tyre wear is estimated, not packet-backed

### 3. Captured UDP Replay

Files:
- `src/asurada/capture_ingest.py`
- `src/asurada/pdu_decoder.py`
- `src/asurada/packet_snapshot.py`
- `src/asurada/capture_runtime.py`

Purpose:
- closest offline approximation of the real runtime path
- main validation path for real F1 25 packet work

Flow:
```text
capture JSONL
  -> CaptureJsonlSource
  -> F125PacketDecoder
  -> CaptureSnapshotAssembler
  -> decode_snapshot()
  -> SessionState
```

### 4. Live UDP Runtime

Files:
- `src/asurada/udp_ingest.py`
- `src/asurada/live_runtime.py`
- `src/asurada/runtime_pipeline.py`

Purpose:
- ingest live UDP packets and run the full real-time decode -> state -> strategy -> output -> log loop

Boundary:
- currently closed against the live runtime loop in the development environment
- still not the final production audio / HUD / device deployment path

## Decode And Assembly

### Raw Packet Layer

File:
- `src/asurada/pdu.py`

Core types:
- `RawPacket`
- `PacketEnvelope`

Role:
- `RawPacket` keeps the raw datagram and receive metadata
- `PacketEnvelope` keeps decoded header/body fields for one packet

### Packet Decoder

File:
- `src/asurada/pdu_decoder.py`

Role:
- decode F1 25 common header
- decode validated body subsets for key packet types

Current packet coverage:
- `Session`
- `LapData`
- `Participants`
- `CarSetups`
- `CarTelemetry`
- `CarStatus`
- `CarDamage`
- `FinalClassification`
- `SessionHistory`
- `TyreSets`
- `Motion`
- `MotionEx`
- `Event`
- `TimeTrial`
- `LapPositions`

Design rule:
- reliable fields only
- avoid forwarding uncertain offsets into the strategy path

### Frame Assembler

File:
- `src/asurada/packet_snapshot.py`

Role:
- merge multi-packet data into one normalized frame

Assembly key:
- `session_uid + frame_identifier`

Required hot-path packets:
- `LapData`
- `CarTelemetry`
- `CarStatus`
- `Motion`
- `MotionEx`
- `CarDamage`

Cached cross-frame context:
- `Session`
- `Participants`
- `LobbyInfo`
- `Event`

Output:
- one normalized snapshot dict compatible with `decode_snapshot()`

Important behavior:
- validates session and lap data before snapshot emission
- injects rival metadata
- injects real tyre wear and damage
- keeps raw packet-derived fields in `raw`

## Internal State Model

Files:
- `src/asurada/models.py`
- `src/asurada/decode.py`
- `src/asurada/state.py`

### Snapshot Conversion

`decode_snapshot()` converts one normalized snapshot dict into `SessionState`.

Primary dataclasses:
- `TyreState`
- `DriverState`
- `SessionState`
- `StateAssessment`
- `RiskProfile`
- `ContextProfile`
- `StrategyCandidate`
- `StrategyDecision`

### Rolling State Store

`UnifiedStateStore` keeps:
- `latest`
- a short rolling history window

Used by:
- context building
- trend-aware risk scoring
- replay inspection

It is not the long-term storage layer.

## Track Model

Files:
- `src/asurada/track_model.py`
- `data/tracks/shanghai_segments.json`

Role:
- classify lap distance into semantic track segments
- expose:
  - `zone_type`
  - `zone_name`
  - `usage`

Example segment semantics:
- deployment straight
- braking entry
- apex rotation
- exit traction
- high load management

Example usage labels:
- `primary_overtake_deploy`
- `front_tyre_protection`
- `maximum_brake_pressure`
- `throttle_stabilize`

The track model is used by:
- strategy context building
- lap analysis
- dashboard ordering

## Strategy Pipeline

File:
- `src/asurada/strategy.py`

The engine is intentionally split into four stages.

### 1. Context Build

Input:
- current frame
- recent history window
- optional track model

Output:
- `ContextProfile`

Contains:
- recent instability ratios
- recent overload ratios
- driving mode
- track zone
- track segment
- track usage
- phase factors

### 2. State Assessment

Output:
- `StateAssessment`

Contains discrete labels for:
- fuel
- tyre
- ERS
- race control
- attack
- defend
- dynamics

### 3. Risk Scoring

Output:
- `RiskProfile`

Contains numeric scores for:
- fuel
- tyre
- ERS
- race control
- dynamics
- attack opportunity
- defend risk

Risk scoring combines:
- thresholds
- short-window context
- track zone
- track usage hooks

### 4. Candidate Generation And Arbitration

Candidate output examples:
- `LOW_FUEL`
- `BOX_WINDOW`
- `TYRE_MANAGE`
- `ERS_LOW`
- `ATTACK_WINDOW`
- `DEFEND_WINDOW`
- `DYNAMICS_UNSTABLE`

Arbitration sorts candidates by:
- priority
- code weight
- layer weight

Final output:
- ranked `StrategyMessage` list
- debug payload for maintenance and dashboard use

## Configurable Usage Hooks

Files:
- `src/asurada/config.py`
- `data/strategy/usage_hooks.json`

Role:
- map `track_usage` labels to weight offsets

Current hook dimensions:
- `attack`
- `ers`
- `defend`
- `tyre`
- `dynamics`

Purpose:
- tune strategy behavior without editing engine code

Example:
- a `primary_overtake_deploy` segment can push attack and ERS weights up
- a `front_tyre_protection` segment can push tyre and dynamics weights up

## Outputs

### Console Strategy Output

File:
- `src/asurada/output.py`

Role:
- temporary voice/HUD stand-in
- prints:
  - final ranked messages
  - layered debug view

### Replay Log

File:
- `src/asurada/replay.py`

Artifact:
- `runtime_logs/session_log.jsonl`

Contains:
- normalized state
- rival data
- raw fields
- final messages
- strategy debug payload

### Debug Dashboard

File:
- `src/asurada/dashboard.py`

Artifact:
- `runtime_logs/dashboard/debug_dashboard.html`

Current features:
- latest state
- recent trends
- frame browser
- segment heatmap
- message statistics
- track-segment ordering

### Lap Reports

Files:
- `src/asurada/analysis.py`
- `src/asurada/reports.py`

Artifacts:
- `runtime_logs/reports/*.json`

Role:
- summarize one lap
- aggregate risk by segment
- identify deployment segments

## Runtime Modes

CLI entry:
- `src/asurada/__main__.py`

Supported modes:
- `--demo`
- `--replay`
- `--csv`
- `--capture-jsonl`
- `--live-udp`
- `--build-dashboard`

Dispatch rule:
- explicit mode first
- replay fallback last

## Maintenance Rules

1. Keep the normalized snapshot shape stable.
2. Prefer adding new packet fields in the decoder and assembler before touching strategy logic.
3. Keep track semantics in track JSON, not hardcoded into the strategy engine.
4. Keep usage weights in `data/strategy/usage_hooks.json`, not in code.
5. Use replay logs and captured UDP replay as the primary regression tools.

## Current Gaps

- live UDP path is closed in the current development environment, but the device-side production path is still pending
- some packet bodies still use validated subsets instead of full protocol coverage
- rival gap semantics are still estimated in some cases
- dashboard is an engineering workbench, not the final race HUD

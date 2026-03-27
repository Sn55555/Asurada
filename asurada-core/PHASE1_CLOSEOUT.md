# Phase 1 Closeout

## 1. Closeout Scope

This file records the final closeout position for Phase 1 under the current environment.

Phase 1 is closed against:
- offline replay input
- CSV single-lap prototype input
- raw capture replay input
- protocol refinement on the currently available Shanghai race-weekend capture
- dashboard-based debug review
- fixed-sample regression

Phase 1 is not closed against:
- live UDP end-to-end runtime
- edge-device deployment
- model training and model serving
- production bidirectional voice runtime

## 2. Delivered In Phase 1

### Data Path

- real F1 25 capture JSONL ingest
- validated packet decode for the current high-value packet families
- multi-packet frame assembly
- normalized session snapshot output

### Core Strategy

- unified in-memory state flow
- layered strategy engine
- context-aware risk scoring
- track-usage hook configuration
- strategy debug payload for replay inspection

### Driving Dynamics

- unstable detection
- front-load detection
- heavy-braking tagging
- entry / apex / exit dynamics summary
- driver style summary tags

### Debug And Replay

- append-only session replay log
- HTML debug dashboard
- parse-to-model inspection chain
- structured lap report output
- fixed-sample phase-one regression

### Protocol Refinement

- `Session` trailer structured fields
- `LapPositions` naming and decode
- `LobbyInfo` decode implementation
- `session_type 8 / 13 / 15 / 16` project-level classification
- timing support split across:
  - `disabled`
  - `official_preferred`
  - `estimated_only`

## 3. Phase 1 Boundaries

### Explicitly Deferred

- live UDP closed-loop runtime
- live replay/runtime path unification
- Pi 5 / CM5 deployment work
- machine-learning model training
- model inference in the strategy chain
- production-grade duplex voice runtime

### Remaining External Validation Items

- real `LobbyInfo` packet sample validation
  - deferred out of phase-one closeout
  - only resume after a real multiplayer sample is available
- any future session code that does not exist in the current capture set
- additional rare `Event` codes not present in the current capture set

## 4. Timing And Session-Type Position

Current project position for validated session semantics:

- `Time Trial(1)`
  - timing mode: `time_trial_disabled`
  - support level: `disabled`
- `QualifyingLike(13)`
  - timing mode: `qualifying_like`
  - support level: `official_preferred`
- `ShortResultLike(8)`
  - timing mode: `session_type_estimated`
  - support level: `estimated_only`
- `SprintRaceLike(15)`
  - timing mode: `race_like`
  - support level: `official_preferred`
- `FeatureRaceLike(16)`
  - timing mode: `race_like`
  - support level: `official_preferred`

## 5. Closeout Evidence

Primary verification inputs:
- full Shanghai race-weekend capture replay
- extracted per-session Shanghai race-weekend samples
- single-lap Shanghai CSV sample

Primary verification artifacts:
- `runtime_logs/session_log.jsonl`
- `runtime_logs/dashboard/debug_dashboard.html`
- `runtime_logs/reports/*.json`
- `runtime_logs/regression/latest_phase1_regression.json`

Primary verification command:

```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate
python3 scripts/phase1_regression.py
```

## 6. Phase 1 Exit Condition

Phase 1 is considered closed in the current environment when:
- the fixed regression suite passes
- dashboard rebuild still exposes the phase-one debug chain
- extracted session samples preserve their expected session/timing semantics
- required replay artifacts can be regenerated from the workspace

## 7. Handoff To Phase 2

Phase 2 can start immediately on top of the current Phase 1 baseline because the project now has:
- real capture-backed normalized inputs
- stable replay samples split by session
- documented field coverage and unresolved edges
- model-input schema draft
- sample regression to guard against parser and dashboard regressions

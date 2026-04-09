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
- [STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md](STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md)
- [STAGE3_LLM_SIDECAR_ROUTING_CN.md](STAGE3_LLM_SIDECAR_ROUTING_CN.md)
- [PROJECT_TIMELINE_AND_RISKS_CN.md](PROJECT_TIMELINE_AND_RISKS_CN.md)
- [PHASE2_DEBUG_DASHBOARD_CN.md](PHASE2_DEBUG_DASHBOARD_CN.md)

## Current Inputs

- replay JSONL input
- single-lap CSV input
- captured UDP JSONL replay input
- live UDP real-time input wired into the runtime strategy loop

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
  - start the live UDP real-time runtime path
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
- `runtime_pipeline.py`
  - runs the shared runtime path used by live UDP and capture replay
- `interaction.py`
  - defines the shared interaction, query, task, and speech contracts
- `output.py`
  - coordinates unified voice output and lifecycle events
- `voice_input.py`
  - bridges structured voice input into the existing interaction/output path
- `track_model.py`
  - applies Shanghai semantic segments and usage labels
- `replay.py`
  - writes append-only JSONL runtime logs
- `dashboard.py`
  - generates the local debug dashboard
- `response_composer.py`
  - renders structured query responses and explanation-style spoken answers
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

For stage-three voice/LLM boundary work, use:
- [STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md](STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md)
  - explainer lane boundary, current backend switches, and local smoke setup
- [STAGE3_LLM_SIDECAR_ROUTING_CN.md](STAGE3_LLM_SIDECAR_ROUTING_CN.md)
  - routing rules for when core may hand explainer questions to the LLM sidecar

## Current Voice Status

The stage-three voice path is no longer just a design skeleton. The repo now contains a runnable sidecar-based voice stack:

- realtime ASR:
  - macOS microphone capture
  - Doubao realtime websocket ASR
  - local realtime sidecar stream bridge
- routing:
  - `control`
  - `structured`
  - `explainer`
  - `companion`
  - `reject`
- explainer / companion:
  - Doubao LLM sidecar
  - companion-mode retry path for slower non-racing chat requests
- speech output:
  - Doubao streaming TTS
  - sidecar playback path with unified persona / voice profile metadata

Current implementation status:

- done:
  - voice sidecar protocol and local server
  - Doubao LLM / TTS / ASR integration
  - realtime ASR default path in the macOS voice loop
  - wake-word preview and partial-transcript fallback
  - companion mode outside active racing state
- not done:
  - AEC / echo cancellation
  - true partial-commit execution from partial transcript
  - Pi deployment hardening
  - watchdog / recovery

## Voice Sidecar Quick Start

Start the voice sidecar:

```bash
source ~/.asurada_llm_env
source ~/.asurada_tts_env
source ~/.asurada_asr_env
export ASURADA_VOICE_SIDECAR_PROVIDER_BACKEND=doubao
export ASURADA_VOICE_SIDECAR_TTS_ENABLED=1
export ASURADA_VOICE_SIDECAR_TTS_BACKEND=doubao_tts
PYTHONPATH=src python3 scripts/phase3_voice_sidecar_server.py
```

Start the macOS duplex voice loop:

```bash
source ~/.asurada_llm_env
source ~/.asurada_tts_env
source ~/.asurada_asr_env
export ASURADA_LLM_SIDECAR_ENABLED=1
export ASURADA_LLM_SIDECAR_BACKEND=voice_sidecar
export ASURADA_VOICE_SIDECAR_BASE_URL=http://127.0.0.1:8788
export ASURADA_VOICE_SIDECAR_TTS_BACKEND=doubao_tts
export ASURADA_AUDIO_AGENT_STREAM_PREROLL_MS=120
export ASURADA_VOICE_DOWNLINK_COOLDOWN_MS=900
PYTHONPATH=src python3 scripts/phase3_macos_voice_loop.py --enable-llm-sidecar --use-sidecar-tts
```

## Next Step

Continue expanding the real F1 25 PDU parser, especially richer rival-state reconstruction and more validated packet bodies.
Voice sidecar TTS smoke:

```bash
export ASURADA_VOICE_SIDECAR_TTS_BACKEND=doubao_tts
export ASURADA_DOUBAO_TTS_APP_ID='your-app-id'
export ASURADA_DOUBAO_TTS_ACCESS_KEY='your-access-key'
# optional:
# export ASURADA_DOUBAO_TTS_RESOURCE_ID='volc.service_type.10029'
# export ASURADA_DOUBAO_TTS_SPEAKER='zh_male_ahu_conversation_wvae_bigtts'
# export ASURADA_DOUBAO_TTS_STREAM_URL='https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse'
PYTHONPATH=src python3 scripts/phase3_doubao_tts_smoke.py --text '当前整体先守住后车，再看处罚窗口。'
```

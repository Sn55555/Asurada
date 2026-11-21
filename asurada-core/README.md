# Asurada Core

批量 Doubao Flash HTTP provider 已接收 sidecar 的任务 context。客户端取消现在可沿 sidecar 传播到上游 HTTP 连接关闭；认证字段和 provider 响应日志 ID 保持原有语义，内部预算头不转发给 provider。完整链路已用真实客户端/服务端/适配器与本地假 provider 验证，没有发送真实音频或使用真实凭证。

关闭上游连接不能证明供应商内部计算已停止。批量 WebSocket 和实时 TCP ASR 服务端仍有剩余治理工作，真实 TLS/云端和音频验收继续保留。

HTTP sidecar 现限制为 16 个连接处理线程、单请求 JSON 正文最多 16 MiB；批量 ASR 只有两个实际执行名额。客户端剩余预算由服务端默认 15 秒上限截断。ASR 超时返回 504，名额满返回 503；客户端断连或服务关闭会取消任务上下文。

非协作 provider 超时后仍占名额，只有真正退出才释放。健康接口不占 ASR 执行名额。现有真实 provider 尚未全部消费 context，因此此处证明服务端执行有界，不代表云端工作已停止；实时 TCP ASR 服务端限制仍待统一。

批量 `voice_sidecar_asr` 的 live context 现在贯穿音频转换和 HTTP 请求。转换进程可取消，失败清理本次部分文件；取消后不上传音频。HTTP 请求共享剩余预算并可关闭响应头/响应体等待，响应 JSON 上限 4 MiB。带 context 的传输直接连接配置的 http/https 地址，不跟随重定向或环境代理。

客户端断开不等于服务端 provider 已取消；DNS/连接尚未返回 socket 的阶段也仍依靠有限预算和单识别工作名额约束。上述改动已用模拟转换进程及本地假 sidecar 验证，真实云端和音频验收保留。

直接 `doubao_realtime_asr` 的 live 轮次现在将 context 传入 WebSocket session，限制建连/发送/finish 的预算，取消时 abort 并在收尾时 shutdown；连接迟到返回不会再发送音频。finish 的短轮询超时会继续等待至固定截止时间。此路径新增验证使用假 WebSocket；本工作区虚拟环境尚未安装 websocket-client，真实 TLS/云端与发布依赖验收仍待完成。

实时 `voice_sidecar_realtime_asr` 客户端现在会在轮次取消或到期时 shutdown 网络连接，解除发送/接收等待，并显式关闭采集迭代器和接收文件句柄。最终结果等待使用同一轮次剩余预算。若 partial 回调本身阻塞，`receiver_shutdown_confirmed=False` 表示未完成收尾，识别名额继续占用直到回调退出，避免重复创建接收线程。

该行为已通过本地 socket 和假 sidecar 验证。直接 Doubao WebSocket 与批量 HTTP 后端的网络取消尚未全部统一，DNS 和非协作回调也不能仅凭取消标志视为已中止；真实音频验收仍保留。

live voice loop 的识别执行限制为一个后台任务。取消可以及时返回；不支持协作取消的识别后端未退出时会显示 `recognizer_cancel_or_busy`，不会再开启一个重叠采集。macOS 采集在传入轮次 context 时支持终止采集进程组；流式采集即使没有 stdout 也会检查配置超时，并排空有界 stderr。

本地采集进程的终止已有模拟子进程验证；网络 ASR connect/send/finish、接收线程及网络阻塞期间的采集收尾仍需继续完成，不能将本地取消等同于整条音频链已释放或设备验收通过。

默认 voice loop 从 `session_log.jsonl` 的 latest 入口运行时，比赛轮次会独立观察同目录 `latest_snapshot.json`。UID/epoch 改变、发布文件删除/损坏或数据超过 15 秒会取消在途轮次，提交回复前再检查一次。取消原因见 `voice_turn_cancel_reason` 日志。该观察使用核心原子发布文件，不反复扫描历史日志。

待机/陪聊轮次不要求比赛发布；显式历史 row 或非标准日志路径不启用这一 live 观察。它不会全局停止新场次的播报，也不代表服务端已拥有完整原子生命周期广播。实际麦克风中止及跨进程传播窗口仍须继续处理。

macOS voice loop 在连续和手动模式均支持 `s + Enter`：独立控制线程取消当前语音轮次，并请求共享服务停止播放；`q + Enter` 同样先取消再退出。慢解释取消后不播后备答案，迟到的识别结果不进入回答。默认整轮结果预算 60 秒，LLM 还受自己的更短预算约束。

停止可能等待已提交的输出调用收尾，再清空播放队列；失败会打印 `stop_unconfirmed`。这不保证不配合取消的麦克风 recognizer 立即返回，也不代表真实声学验收完成。`s` 始终是独立键盘入口。增加 `--spoken-interrupt` 可在播报和解释期间保持单一后台识别，使用完整“唤醒词＋停止/取消”触发停止；部分识别、裸停止词和句中提及不会触发。此模式没有提供 AEC，请使用耳机或隔离回声的输入环境，实际识别准确率与停止时延保留实机验收。未启用时保留播放期间暂停识别的默认行为。

生产 live 入口默认管理共享语音服务。在本目录运行：

```sh
PYTHONPATH=src .venv/bin/python -m asurada --live-udp
```

未配置 `ASURADA_SPEECH_SOCKET` 时，核心会启动或连接 `/tmp/asurada-speech-<用户 UID>/voice.sock`（目录权限 700）；voice loop 默认连接同一地址，服务缺失会在开始监听前报错，不创建第二个播放器。启动者只请求关闭自己创建的服务，附着既有服务不会关闭它。创建者退出会结束其拥有的共享服务；需要独立于核心持续运行时，使用下面的外部服务模式。

共享语音服务也可单独启动：

```sh
PYTHONPATH=src .venv/bin/python -m asurada.speech_service --socket /tmp/asurada-speech.sock
```

核心与 voice loop 的启动环境均设置 `ASURADA_SPEECH_SOCKET=/tmp/asurada-speech.sock`，即可连接该外部服务。需要 sidecar TTS 时，在服务命令添加 `--sidecar-tts`；后端由服务决定。开发无声验证可在服务环境设置 `ASURADA_TTS_BACKEND=null`。显式配置外部地址时服务缺失会失败，不在该地址自动启动替代进程。demo、CSV、捕获回放 CLI 使用独立本地输出，即使配置 live socket 也不会把历史提示发往共享服务。直接使用 Python API 的调用者仍应显式注入输出或设置 `shared_speech`。

配置共享服务后，live 核心使用后台提交：一个在途、一个最新待处理决定，待处理超过 500 ms 丢弃。`submission_accepted` 只表示交给提交器，不等于开始发声。IPC 失败记录 `delivery_unknown` 并继续遥测，不自动重试或另开播放器；新决定仍会尝试连接。启动时服务缺失仍报错。关闭客户端不会停止共享服务里的其他播报，在途请求也不能被视为已取消。

提交健康和回执见决定 debug 的 `speech_submission`，最终状态见 `[ASURADA][SPEECH-SUBMISSION]` 日志。回执环有上限和丢弃计数，当前还不是完整持久化语音账本。500 ms 是工程默认值，真实驾驶与语音体验仍需用户验收。

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
  - loads and classifies semantic segments for all 27 F1 25 base-game layouts
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

The F1 25 base-game catalog covers 27 layouts: 24 standard circuits and the Silverstone,
Austria, and Zandvoort reverse layouts. Every profile provides:
- segment names
- zone types
- usage labels
- braking zones
- corner apexes
- corner gear recommendations

Example usages:
- `primary_overtake_deploy`
- `front_tyre_protection`
- `maximum_brake_pressure`
- `throttle_stabilize`

Usage weights are configurable in:
- [data/strategy/usage_hooks.json](data/strategy/usage_hooks.json)

The strategy engine reads these values at startup, so tuning no longer requires editing code.

Coverage details, source provenance, and rebuild commands are documented in:
- [data/tracks/README.md](data/tracks/README.md)

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
python3 scripts/validate_f1_25_track_semantics.py
python3 scripts/phase1_all_track_semantics_regression.py
python3 scripts/phase1_track_semantics_quality_regression.py
python3 scripts/phase1_real_udp_track_semantics_regression.py
python3 scripts/phase1_all_track_udp_replay_regression.py
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

Start the macOS voice loop:

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

### Python 依赖分组（架构改造中）

基础包仅依赖 Python 标准库，模型缺失时采用现有可观测降级路径。
在源码目录安装时，可按运行职责选择固定版本的直接依赖：

```bash
python -m pip install .
python -m pip install '.[models]'
python -m pip install '.[training]'
python -m pip install '.[http-voice]'
python -m pip install '.[realtime-asr]'
python -m pip install '.[local-asr]'
```

这些分组是直接依赖声明，不是包含全部传递依赖的锁文件。
`realtime-asr` 声明 websocket-client 1.8.0（支持本项目 Python 3.9）；已核对构建 wheel 的依赖元数据，实际安装、TLS/云端仍待验收。
当前基础 wheel 已在独立 Python 3.9 虚拟环境完成离线安装、CLI 与显式样例路径回放验证。
wheel 构建会包含赛道、策略、模型报告/文件、演示数据及 macOS Swift 辅助脚本，并生成资产哈希清单。
安装后从包内 `_assets` 读取，默认 `--demo` 不依赖当前目录。源码工作区仍使用原 data/training 布局。
可用 `ASURADA_ASSET_ROOT` 指定替代资产目录；`ASURADA_RUNTIME_DIR` 指定可写状态目录。
安装包的默认状态目录为 `~/.local/state/asurada`，源码运行仍为原 `runtime_logs`。
目前已验证隔离环境中的 90 个资产及 24 份模型报告迁移；模型依赖安装/推理、WebSocket
语音依赖和平台原生库仍需完成完整发布验证，见架构执行计划 A13。

### 本地赛后训练草稿

`run_session_review.py` 的 v6 流程从同条件最近三圈的区段耗时生成一条稳定性练习草稿，存于工作流数据库旁的 `.training.sqlite3`。它不会自动启用或播放，也不会把圈速变化解释为训练因果。查看草稿：

```sh
.venv/bin/python scripts/training_plan.py --database /absolute/path/review.db --driver-id local-driver list
```

练习开始时显式提供当前已完成圈；圈号必须不早于草稿基线：

```sh
.venv/bin/python scripts/training_plan.py --database /absolute/path/review.db --driver-id local-driver activate --plan-id PLAN_ID --after-lap 5
```

下一次对包含新圈的投影执行 `run_session_review.py`，继续使用同一数据库和驾驶员、使用新的 task-id。流程将同场次/epoch/条件下大于启用圈号的第一个有效区段与基线中位数比较。缺数据或条件不符时保持等待；记录为观测结果，单圈不能证明训练效果。`cancel --plan-id PLAN_ID` 可撤销未结束任务；未启用或活跃任务七天后过期。`local-driver` 只是本地档案名称，不自动识别实际驾驶员。当前没有跨场迁移或实时圈号自动核验。

复盘命令退出码：`0` 表示完整报告已完成，`2` 表示任务取消或过期，`1` 表示本次调用失败。错误以 JSON 输出；输入冲突不会复用旧任务的成功状态。查看或取消已创建的持久复盘任务：

```sh
.venv/bin/python scripts/review_task.py --database /absolute/path/review.db --task-id TASK_ID status
.venv/bin/python scripts/review_task.py --database /absolute/path/review.db --task-id TASK_ID cancel
```

取消不会撤销此前已提交的事实或训练记录。v6 原始抓包投影已作为第一个持久步骤，共享任务取消和总 deadline；创建任务前的输入哈希准备仍先于持久记录。原始抓包命令在同一输出目录重试时核验版本及源/目标哈希，复用已发布投影；不同输入、损坏投影或旧版无版本 manifest 会失败。需要处理另一份抓包或升级投影时使用新输出目录，保留原证据。


原始抓包全流程使用 `review_raw_capture.py --timeout 300` 指定总秒数，包含投影及后续复盘；旧 `--projection-timeout` 现在是此总预算的别名。任务重试不会延长已保存的 deadline。v6 对原始抓包有七个检查点，对已有投影有六个检查点；升级工作流版本时使用新的 task-id，避免混用旧定义。

原始抓包投影现为 `review-projection-v2`，修正了 F1 25 Session 包的 marshal zones、安全车状态与联网字段位置，并按规范解析有符号赛道编号。已有 v1 投影可能包含错误管制状态；重新分析时，请使用新的 `--output` 目录和 `--task-id` 从原始抓包生成 v2。不要只修改旧 manifest 的版本号，也不要删除旧报告来伪造升级成功。旧目录复用会明确返回版本冲突，历史证据保留。

训练导出的分组现在以 metadata 完整 session UID 为单位。所有领域表继承配置的 train/val/test；圈号、帧号和伪标签不再改变分组。不同样本若复用同一 UID，必须配置为同一集合，且实际抓包 UID 必须匹配 metadata。旧版按圈/帧拆分的 CSV 可能被训练入口拒绝，应在新的输出目录重新导出。

已迁移的攻击、前车攻击承诺、后车威胁、让位防守、事件影响和反攻窗口训练入口禁止随机逐行回退，报告包含完整场次分组清单。缺少独立场次或类别覆盖表示数据不足，不能靠重分配测试集解决。驾驶风格、轮胎趋势、短期预测、对手压力、防守成本和策略动作入口也已迁移，聚合前会校验场次身份；未来标签窗口和其他泄漏来源仍需继续验证，不能将当前模型评价视为完整质量验收。导出 `--sample-limit` 限制主表保留行数，仍分析完整抓包，领域表不受该保留行数上限约束。

轮胎趋势和短期风险的未来标签要求完整连续窗口，默认相邻观测间隔不超过 1 秒；不足时长、倒带或显式 epoch 变化会截断窗口。轮胎趋势还检查胎种、胎龄和磨损重置。下一赛段未被观测到时，该目标保持缺失。每次训练保存 `target_windows.csv` 及源文件/窗口文件哈希，供审查名义时长、实际起止记录与目标值。稀疏导出可能因此没有足够标签，这表示数据不足；不能放宽到任意远处样本来伪造固定时长目标。

特征/标签合并训练现要求两侧完整记录集合相同、record_id 唯一，并验证 UID/split（及双方提供的 epoch/frame/sample_name）。旧的不含身份字段的标签文件会被拒绝。新版导出记录 ID 包含 epoch 和 overall frame；攻击表额外区分 actor_view，并保留 source_record_id。升级时在新目录重新导出，不能把旧表与新标签拼接使用。

实时状态与语音输出会拒绝明确较旧的 epoch，以及本运行实例最近已离开的 16 个 UID，避免迟到数据恢复旧场次。明确提供的 session_epoch 必须是非负整数；旧格式缺省 epoch 时仍使用计数器推断。需要从头重放已离开的历史 UID 时使用新运行实例。全局停止/取消不依赖当前遥测是否新鲜，仍可作用于当前声音队列。这些对象内检查不替代跨进程场次广播或设备实际停止验收。


批量 Doubao WebSocket ASR 的 TaskContext 与分块验证：
`output/architecture-implementation/a02-batch-ws-verified/summary.json`。
带上下文时取消会 abort 连接并在退出时 shutdown；连接阶段仍受 SDK/DNS 行为限制。
WAV 输入须为 16 kHz、单声道、16 bit，解包后按 chunk_ms 发送 PCM；裸 PCM 使用同一音频契约。
验证使用假连接和生成音频，不代表真实 provider 或麦克风验收。

实时 ASR TCP 服务现在限制八个并发连接，单帧 4 MiB、累计输入 16 MiB，默认整连接 60 秒，单次 socket I/O 2 秒。
断连、到期和服务关闭向支持 TaskContext 的 provider 传递取消；未退出的后端继续占用名额。
本地协议与生命周期证据：`output/architecture-implementation/a02-stream-server-verified/summary.json`。

共享播报停止屏障要求更新客户端和服务：非停止播报请求携带本机 `CLOCK_MONOTONIC` 产生时间。
语音轮次从 begin 起、实时候选从入队前起绑定时间；停止前的旧工作即使迟到也被拒绝，停止后的新请求仍允许。
缺少字段的旧客户端明确报错。证据：`output/architecture-implementation/a03-stop-barrier-final/summary.json`（假播放器、本地 IPC）。

live CLI 启动语音服务时固定 `--session-source <runtime>/latest_snapshot.json`；复用服务必须使用同一来源。
服务在绑定/交付前检查最新场次、epoch 与时效，独立观察发布失效并停止旧播放；停止命令不依赖文件可读。
当前是原子文件发布加周期观察，尚非跨进程原子交付保证。开发证据：`output/architecture-implementation/a04-speech-authority-final/summary.json`。

配置场次来源的共享服务还会检查同场问答适用性：原快照年龄、关键比赛上下文、固定 handler 结果或 LLM 声明证据发生变化时拒绝旧回复。
校验目前发生于提交接收阶段，尚不替代队列启动前复核，也不验证任意自然语言结论。
证据：`output/architecture-implementation/a04-query-applicability-final/summary.json`。

共享输出队列现在在每次 backend.start 前，复核该任务自己的停止屏障、权威场次和问答依据。
失效任务记录 `suppress / delivery_no_longer_applicable`，不调用播放器，调度器继续运行。
证据：`output/architecture-implementation/a03-queue-recheck/summary.json`；不代表真实音频发声时点的原子一致性。

主动策略 emit 在配置权威来源的服务中要求绑定 DecisionRecord：动作与实际播报参数必须一致，排队启动前最新决定仍需支持该建议。
证据：`output/architecture-implementation/a04-strategy-applicability/summary.json`（实际策略引擎、生成状态、假播放器）。

辅助提示在服务端开始播放前另检距离/时间窗口：制动倒数 0.35 秒、弯道挡位 0.75 秒，跨圈、位置倒退/前进过远、越过目标或缺少有效位置时不播。
这是待真实驾驶标定的工程窗口。证据：`output/architecture-implementation/a04-assist-window/summary.json`。

比赛解释支持 `numeric-claims-v1`：claims 声明规范字段、value/difference、数值、单位和精度，answer_text 使用 `{{id}}`，验证后由程序生成数字与单位。
目前仍允许旧版无 claims 响应走引用校验，尚未构成所有数值的强制保证。证据：`output/architecture-implementation/a08-numeric-claims/summary.json`。

数值声明迁移更新：比赛回答中的阿拉伯数字与常见中文数量表达现要求 claims，服务端复核声明并比较最终 persona 文本。
当前纯校验结果：`output/architecture-implementation/a08-claims-pure-validation/summary.json`；新增本地服务集成回归因自动审批额度限制尚未启动。

短期上下文使用一秒源时间加权窗口（source-time-weighted-v1），记录实际历史覆盖；单个采样最多持有 250 ms。
active 模型须声明对应窗口评估，旧窗口准入不能直接复用。证据：`output/architecture-implementation/a04-source-time-context-verified/summary.json`。

### Sidecar 播放预算

`ASURADA_VOICE_SIDECAR_TIMEOUT_MS`（默认 2500）控制普通请求及边收边播的网络连接/读取等待。
`ASURADA_VOICE_SIDECAR_PLAYBACK_TIMEOUT_MS`（默认 60000）控制边收边播总时限，覆盖音频接收与播放器结束。
`play_tts(timeout_ms=...)` 显式参数覆盖本次总时限；停止操作仍立即触发取消。服务端合成另受自己的预算上限约束。

## 运行日志归档保留

核心 CLI 支持 `--replay-log-max-archives N`，用于限制轮转后的 `session_log.<时间戳>.jsonl` 数量。省略参数维持保留全部归档；`0` 仅保留当前日志；负数在启动服务前报错。Python 调用使用 `AppConfig(replay_log_max_archives=N)`。

例如在仓库根目录运行 `PYTHONPATH=asurada-core/src asurada-core/.venv/bin/python -m asurada --live-udp --replay-log-max-archives 8`。发生下一次轮转时会删除超过数量的旧归档；当前文件与最多 8 个归档保留。单文件轮转阈值仍为 16 MiB，单条记录可能跨过阈值，因此这不是精确的字节硬上限。

该选项只管理运行时展开日志，不限制原始 UDP 抓包、报告、训练数据库或其他文件。需要长时间完整分析时应保留原始抓包；开启归档保留限制前应根据所需回溯范围选择数量。

## 云端流式 TTS 格式

Doubao SSE 适配器的上游 `ASURADA_DOUBAO_TTS_AUDIO_FORMAT`（或 `ASURADA_VOLC_TTS_AUDIO_FORMAT`）当前仅支持 `pcm`，默认值也是 `pcm`。适配器对外输出 `pcm_s16le`，缓冲合成接口将相同 PCM 包装为 WAV；没有 MP3/Opus/WAV 流的解码转换能力。配置其他上游格式会在发起请求前明确报错，避免将编码文件误标为 PCM 播放。

跨 SSE 分片拆开的 16 位采样值会拼接后输出，每帧保持两字节对齐。成功结束时若还剩半个采样值则报告截断，不返回完成。该检查验证字节格式与结束语义，不证明云端合成内容正确或实际听音通过。


## 本地复盘档案与能力扩展

`python -m asurada.review_profile` 提供显式本地驾驶员偏好的设置、查看与撤销，以及已完成复盘的展示和官方圈时观测记录。需要已有复盘数据库与明确 driver-id；详略偏好只影响该展示入口，不改变比赛事实或实时语音。完整命令、有效期与证据边界见 [本地复盘档案说明](../doc/ASURADA_REVIEW_PROFILE_CN.md)。

交互能力的路由名称、请求字段、默认问句、快速关键词别名现在与处理器共同定义于 `CapabilitySpec`。`requested_fields` 是信息投影，不代表全部字段均为必填；领域处理器继续负责缺失数据行为。关键词同分时由 `fast_alias_order` 保持原有优先级，复杂上下文推断仍由语义模块处理。


## 网页 WebSocket 依赖

网页服务器的握手与帧解析使用 `websockets==15.0.1`，在核心虚拟环境安装 `pip install -e '.[dashboard]'` 后使用该解释器运行仓库的 `live-dashboard/server.py`。协议层负责 Ping/Pong、Close、掩码与分片处理；每连接仍只保留一份待发最新状态，单条展示 payload 上限 2 MiB，发送和关闭预算为 0.5 秒。超大展示消息跳过并计入 `oversized_payloads`，不会阻止后续有效状态广播。

socketpair 协议测试覆盖连接后的线协议和慢接收方，不代替浏览器、TCP listener 或真实比赛验收。

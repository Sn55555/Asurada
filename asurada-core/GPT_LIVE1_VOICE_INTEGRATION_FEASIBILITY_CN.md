# GPT-Live-1 接入 Asurada 可行性调研

> 调研日期：2026-09-17
> 调研对象：OpenAI GPT-Live-1 全双工语音 API
> 调研范围：接入 Asurada Phase 3 实时语音链路的可行性、改造量、成本与风险
> 关联文档：`REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md`、`STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md`、`STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md`、`STAGE3_LLM_SIDECAR_ROUTING_CN.md`
> 专项展开：`GPT_LIVE1_Q1_DELEGATION_TRANSCRIPT_CN.md`（Q1 委派原话可得性深挖，含精确验收指标）
> 落地清单：`GPT_LIVE1_INTEGRATION_CHANGELIST_CN.md`（逐文件改动点、必须自建项、"不动"清单、风险与回归判定线）

---

## 0. 结论摘要

**一句话结论：技术上可行、接口上契合、但当前不建议替换主链路；建议以「可插拔第四后端 + 限场景灰度」方式接入，定位为云端高质量档而非实时主控档。**

### 0.1 判定汇总

| 维度 | 判定 | 说明 |
| --- | --- | --- |
| 传输可行性 | ✅ 可行 | 支持 `wss://api.openai.com/v1/live/sessions` 服务端 WebSocket，可跑在无头 Pi/CM5 |
| 音频兼容性 | ✅ 零改造 | 原生支持 `audio/pcm` @ 16000Hz 单声道 s16le，与 `AudioIO` 默认格式**完全一致** |
| 代码复用度 | ✅ 高 | 现有 Responses 客户端与流式会话抽象可直接套用，估计新增代码集中在 2~3 个文件 |
| 延迟达标 | ⚠️ 不达标 | 官方口径轮次延迟 0.798s，已接近甚至吃掉现有"总 <1s"预算，叠加跨境网络后必超 |
| 成本可控 | ⚠️ 中性偏好 | 语音层 ¥0.34/分钟反而低于豆包端到端实时语音（¥0.41/分钟），但**按会话时长计费**，常开即持续计费 |
| 正确性保障 | ❌ 冲突 | 官方明确"后端工作未完成时语音层可能已经开口"，与"不播报未验证策略"直接冲突 |
| 网络可达性 | ❌ 高风险 | 必须代理；实时双向音频流对抖动/断连敏感，且属产品化合规风险 |

### 0.2 推荐决策

**不做主链路替换；按"限场景 + 可插拔"接入。**

- **接入**：作为 `resolve_default_speech_backend` / `resolve_voice_sidecar_asr_backend` 之外的**新一档后端**（暂称 `live`），由 `ASURADA_VOICE_LIVE_BACKEND` 开关控制，默认关闭。
- **定位**：只服务**对延迟不敏感、对表达质量敏感**的场景 —— 赛后复盘问答、P 房讲解、车手训练问答、非比赛期伴随对话。
- **不用于**：比赛中实时策略播报（燃油窗口、进站指令、攻防提醒）。
- **保留**：现有豆包级联链路与本地 Piper/faster-whisper 作为降级档，**不得因为接入 GPT-Live 而删除**。

---

## 1. 调研对象澄清：GPT-Live-1 ≠ Realtime API

本次调研容易踩的第一个坑，是把它和已有的 Realtime 系列混淆。两者**不是同一套东西，也不互相兼容**：

| 维度 | GPT-Live-1 | Realtime API（gpt-realtime-2.1） |
| --- | --- | --- |
| 端点 | `wss://api.openai.com/v1/live/sessions`（无查询参数） | `wss://api.openai.com/v1/realtime?model=...` |
| 交互模型 | 真全双工，模型自行决定何时听/说 | 半双工轮次，需 commit + `response.create` |
| 音频格式 | `session.audio.format`，**会话内不可改** | 契约不同 |
| 计费 | **$0.05/分钟**（按秒，不向上取整） | 按 token（音频 $32/$64 每 1M） |
| 会话模型 | 语音层 + 委派后端（两层计费） | 单会话内做语音+推理+工具 |
| 迁移关系 | **不是改 model ID 就能切**，官方单独出迁移指南 | — |

> 另一个必须澄清的点：网上有资料称 GPT-Live-1「只能用 WebRTC」。**该说法不准确** —— 官方文档明确列出四类连接方式：WebRTC（浏览器）、**WebSockets（服务端音频）**、Sideband 服务端控制、Telephony/SIP（电话）。对 Asurada 这种无头服务端场景，**走 WebSocket 是官方支持路径**，不需要引入 `aiortc` 之类 WebRTC 依赖。

### 1.1 模型硬性约束（官方事实）

| 项目 | 值 |
| --- | --- |
| 模型 ID | `gpt-live-1`（API 侧**无 mini 变体**） |
| 知识截止 | 2025-07-31 |
| 输入模态 | 音频、文本 |
| 输出模态 | 音频、文本 |
| **不支持** | **图像、视频** |
| 支持特性 | streaming、function_calling |
| **不支持特性** | **structured_outputs**、fine_tuning、predicted_outputs |
| 端点白名单 | **仅** `v1/live/sessions`；Chat Completions / Responses / Realtime / Batch 等**全部不支持** |
| 配额 | 按**并发会话数**计（Tier1=25 / T2=50 / T3=200 / T4=300 / T5=500）；**Free 层不支持** |
| 语音 | 12 个预置音色（Quartz / Ripple / Vesper / Willow / Stone / Gleam / Meridian / Bossa / Tempo / Beacon / Delta / Cinder），**不支持自定义克隆**（需走销售） |
| 合规 | 生成音频带 **SynthID 水印** |

> ⚠️ `structured_outputs` 不支持 —— 这一条对 Asurada 影响很大，见 §4.3。

---

## 2. Asurada 语音链路现状（含代码证据）

> 以下路径均以 `/Users/sn5/Asurada/asurada-core/src/asurada/` 为前缀，已逐条核对。

### 2.1 当前是一条「豆包级联 + sidecar 桥接」链路

```
麦克风 → AudioIO → VAD → VoiceTurnManager → [ASR] → voice_nlu → LlmExplainer → 策略链
                                                                                    ↓
扬声器 ← [TTS Backend] ←──────────────────────────────────────────────────── 播报文本
```

**不是本地方案**，是云端 provider 级联；本地只保留 Piper / faster-whisper 作为 fallback。

| 模块 | 实现位置 | 关键事实 |
| --- | --- | --- |
| AudioIO | `audio_io.py:13`（`AudioFormat`）、`:340`（`start`） | 固定 **16kHz / 单声道 / s16le**（`audio_io.py:170-171` 读 `ASURADA_AUDIO_SAMPLE_RATE_HZ`、`ASURADA_AUDIO_CHANNELS`）；真机后端为 ALSA `arecord`/`aplay`（`:159`、`:254`），`period_ms=40` |
| VAD | `vad.py` | **纯能量 VAD**（`audioop.rms`，阈值 900，`:47-67`），`end_silence_ms=320`（`:70-82`）。**非 silero** |
| VoiceTurnManager | `voice_turn.py` | **PTT + 攒 utterance 后整体 finalize**（`:116-233`），`require_ptt=True`、`max_turn_ms=12000`（`:55-60`）。**非流式交互** |
| FastIntentASR | `asr_fast.py:27`（抽象）、`:34` | `KeywordFastIntentASR` 只是**关键词别名评分**，不跑模型、不调 ASR |
| 真实 ASR | `voice_sidecar_asr.py` | 豆包流式 WS `:344`（`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream`，`:362`；`audio_chunk_ms=200`，`:354`）；豆包 Flash HTTP `:747`；本地 faster-whisper `open_asr.py:50`；macOS Apple Speech `macos_speech.py` |
| TTS 抽象 | `tts_backends.py:18` | `SpeechBackend` 4 方法：`start(SpeechJob)->Any`、`is_active(handle)->bool`、`stop(handle)->None`、`completion_error(handle)->str|None` |
| TTS 实现 | `tts_backends.py` | `NullSpeechBackend:40`、`MacOSSayBackend:53`、`PiperBackend:90`、`VoiceSidecarSpeechBackend:183`（pcm_s16le/16kHz）；豆包 SSE 流式 TTS 在 `voice_sidecar_tts.py` |
| NLU | `voice_nlu.py:42` | `build_voice_query_bundle` 仅做 **contract 映射，本地规则，无外部调用** |
| 外部 LLM | `llm_explainer.py` | `OpenAiResponsesLlmExplainerBackend:111`（`POST {base_url}/responses`，`:175`，json_schema `:161-177`）、`DoubaoArkResponsesLlmExplainerBackend:230`、`ChatCompletions:279`、`VoiceSidecarLlmExplainerBackend:377`；选择器 `resolve_default_llm_explainer_backend:579` |
| 流式会话抽象 | `voice_sidecar_asr.py:88` | `VoiceSidecarRealtimeAsrSession`：`append_audio_chunk(chunk)` / `finish(...)`；`DoubaoRealtimeAsrStreamSession:121` 是现成 WS 流式会话实现样板 |
| sidecar 服务 | `voice_sidecar_server.py:70-72` | HTTP `127.0.0.1:8788` + 实时 ASR 独立 TCP `8789`（`:321-450`） |
| 配置方式 | 全局 `os.getenv` | **无 .env / yaml / pydantic**；后端开关：`ASURADA_TTS_BACKEND`、`ASURADA_VOICE_SIDECAR_ASR_BACKEND`、`ASURADA_LLM_SIDECAR_BACKEND`；已具备 `ASURADA_OPENAI_API_KEY` / `ASURADA_OPENAI_MODEL` / `ASURADA_OPENAI_BASE_URL`（`llm_explainer.py:133-137`） |
| 中断 | `voice_interrupt.py`、`spoken_stop.py` | 已有基础，但**无 AEC**（README 列为未完成项） |
| 延迟预算 | `REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md:325-336` | ASR partial 100–300ms + 路由 <50ms + TTS 首音 200–500ms → **总 <1s** |
| 部署 | 目前**仅 macOS 跑通** | Pi5/CM5 为规划态；真机侧有 `esp32-display/`、`live-dashboard/`、`macos-voice/main.swift` |

### 2.2 一个重要的坏消息

全仓检索 **"全双工 / GPT-Live / Realtime API" 均无命中** —— 现有架构**没有为全双工预留任何设计**。`VoiceTurnManager` 的 PTT + utterance 语义与全双工的"连续流"语义是**正面冲突**的，不是加个参数就能兼容。

---

## 3. 接口契约（接入所需事实）

### 3.1 连接与握手

```text
wss://api.openai.com/v1/live/sessions          # 无查询参数
Authorization: Bearer $OPENAI_API_KEY           # 服务端持有，绝不下发到端侧
```

时序：

1. 建 WebSocket；
2. 发首条消息 `session.start`（携带 `session` 配置对象）；
3. **等 `session.started`**（含解析后配置与会话 ID）后，才可发音频。

若走 WebRTC 路径（`POST /v1/live/sessions` + `transport.sdp`，返回 201），**HTTP 调用本身即启动会话，此时不得再发 `session.start`**；且不得在 data channel 上追加输入音频或等待输出音频 delta，`audio.format` 要留空交给 SDP。

### 3.2 会话配置

```json
{
  "model": "gpt-live-1",
  "instructions": "Be concise. Delegate requests needing current information to the backend.",
  "audio": {
    "format": { "type": "audio/pcm", "rate": 16000 },
    "output": { "voice": "marin" }
  },
  "delegation": {
    "type": "responses",
    "responses": {
      "model": "gpt-5.6-luna",
      "tools": [{ "type": "web_search" }],
      "tool_choice": "auto"
    }
  }
}
```

**音频格式（会话内不可更改，输入输出共用）：**

| 格式 | 说明 |
| --- | --- |
| `{"type":"audio/pcm","rate":24000}` | 默认；单声道 s16le 24kHz |
| `{"type":"audio/pcm","rate":16000}` | 单声道 s16le **16kHz ← 与 Asurada 完全一致** |
| `{"type":"audio/pcmu","rate":8000}` | G.711 μ-law |
| `{"type":"audio/pcma","rate":8000}` | G.711 A-law |

**约束**：原始字节需 **base64**，**不带 WAV 容器头**；PCM 分块**字节长度必须为偶数**（不足的尾字节需带入下一分块）；分块边界任意但须**连续有序**；采样率不匹配时**需自行重采样**（改配置不会自动转换）。

### 3.3 事件表

**客户端 → 服务端**

| 事件 | 用途 |
| --- | --- |
| `session.start` | 启动会话（首条） |
| `session.input_audio.append` | 追加音频（base64，**无 ACK**） |
| `session.update` | 更新会话设置（同委派模式内可换后端模型/提示词/工具） |
| `session.instructions.append` | 追加对话指令 |
| `session.input_audio.mute` / `.unmute` | 输入音频静音/取消静音 |
| `session.close` | 关闭会话 |

**服务端 → 客户端**

| 事件 | 用途 |
| --- | --- |
| `session.started` | 会话就绪（含 id） |
| `session.output_audio.delta` | 输出音频增量（base64） |
| `session.input_transcript.delta` | 用户转写增量 |
| `session.output_transcript.delta` | 助手转写增量 |
| `session.updated` | 更新成功 |
| `response.event` | 后端事件信封（内层 `event`） |
| `error` | 命令被拒/会话错误 |
| `session.closed` | 关闭，含最终 `usage` |

> ⚠️ **无 `output_audio_done` 事件** —— 必须客户端自行驱动播放队列状态。

### 3.4 Python SDK（官方提供）

```bash
pip install "openai[realtime]"
```

```python
from openai import AsyncOpenAI

async with AsyncOpenAI() as client:
    async with client.live.connect() as connection:
        await connection.session.start(session=session, event_id="event_start")
        async for event in connection:
            if event.type == "session.started": ...
            elif event.type == "session.output_audio.delta": ...
            elif event.type == "session.closed": break
```

要点：音频走 `session.input_audio.append(audio=base64...)`；**输入流 EOF 不会结束会话**，须显式 `session.close()` 并等待 `session.closed`（官方示例等待上限 15s）；音频源若一次性 pipe 整个文件**不能**模拟实时麦克风（需按录制采样率节奏供流）。

### 3.5 两种委派模式

| 模式 | 适用 | 说明 |
| --- | --- | --- |
| `responses`（托管） | 无自建后端 | GPT-Live 调你配置的 Responses 模型，OpenAI 托管推理与工具选择 |
| `client`（自建） | **有现成 agent/编排器** ← Asurada 属此类 | 连接自运行模型/agent harness；应用收到 `session.delegation.created`（**仅元数据，不含请求文本/工具参数/音频**），自行组装输入、执行、回传 |

- 模式**必须在建会话时选定**，中途切换需重开会话；同一模式内可用 `session.update` 换后端模型/提示词/工具。
- 回传链路：`response.item.create`（结果）→ `response.create`（继续后端工作）。
- 追加类接口 `session.thinking.append` / `session.commentary.append` / `session.instructions.append`，**单条上限 500 token**，需 `delegation_id`。

---

## 4. 架构差距对照

### 4.1 逐模块映射

| 现有模块 | GPT-Live 下 | 结论 |
| --- | --- | --- |
| `VoiceTurnManager`（PTT + utterance finalize） | **无对应物** —— GPT-Live 自动管理听/说时机 | ❌ **最大改造点**：现有 PTT/utterance 语义必须旁路 |
| `VoiceActivityDetector`（能量 VAD） | 服务端自带 VAD/轮次判定 | ⚠️ 从"正确性组件"降级为"成本优化组件"（静音时不送流，省带宽/降误触发） |
| `FastIntentASR`（关键词别名评分） | 被 `session.input_transcript.delta` 取代 | ⚠️ 可保留为本地快速兜底，但主路径不再需要 |
| Doubao 流式 ASR（`voice_sidecar_asr.py:344`） | 原生 ASR 转写（且支持 keyword biasing） | ✅ 整段链路可下线（若全量切换） |
| 豆包 SSE TTS / `PiperBackend` / `MacOSSayBackend` | GPT-Live 直接输出音频 | ✅ **TTS 全链路被旁路** —— 收益是简单，代价是丢掉离线能力 |
| `voice_nlu.build_voice_query_bundle` | 作为委派适配器的**输入装配点** | ✅ **可复用**，正好对接 `client` 委派 |
| `OpenAiResponsesLlmExplainerBackend`（`llm_explainer.py:111`） | `delegation.responses` 的后端 | ✅ **最高价值复用点**：Responses 客户端已具备，`base_url` 已可配 |
| `VoiceSidecarRealtimeAsrSession`（`:88`） | `LiveSessionBackend` 的形态参考 | ✅ **形态同构**，`DoubaoRealtimeAsrStreamSession`（`:121`）可直接抄结构 |
| `SpeechBackend`（`tts_backends.py:18`） | **不适配** | ❌ 4 方法是"一次性 TTS 任务"模型（start→handle→is_active→stop），全双工需要"常开会话 + 双向回调"，语义不匹配 |
| `voice_interrupt.py` / `spoken_stop.py` | `session.input_audio.mute/unmute` | ⚠️ 局部可映射，但**缺 AEC** 仍是硬伤（全双工回声问题更严重） |
| `runtime_logs/session_log.jsonl`（毫秒级时间戳） | 转写时间戳**非权威** | ❌ 官方明确 `start_ms`/`end_ms` 不是确定轮次边界，片段可能迟到或与助手语音重叠 —— **会破坏现有毫秒级审计链** |

### 4.2 核心冲突：这不是"加后端"，是"换范式"

现有架构是**离散轮次**（PTT 按下 → 攒够一句 → ASR → NLU → LLM → TTS 播报 → 结束）；
GPT-Live 是**连续流**（永远在听，自己决定何时说，随时被抢话）。

**没有一个现成的抽象能同时容纳两者。** 强行改造 `VoiceTurnManager` 会导致豆包级联链路回归风险 —— 因此建议 **新增并行抽象，而非修改现有抽象**：

```
语音会话抽象（新增）
├── LiveSessionBackend        ← GPT-Live（连续流）
└── (现有 sidecar 链路保持不变，作为轮次式实现)
```

### 4.3 `structured_outputs` 缺失的影响

`OpenAiResponsesLlmExplainerBackend` 目前依赖 json_schema 约束输出（`llm_explainer.py:161-177`）。注意：

- 该限制**只作用于 `gpt-live-1` 本身**，**不作用于被委派的后端 Responses 模型** —— 委派后端仍可用 json_schema。
- 真正的风险在于：GPT-Live 语音层是**自然语言复述**委派结果，**不保证结构化字段的忠实度**。策略数字（燃油、圈速差、窗口）经语音层"转述"后**可能失真**。

**缓解要求**：所有关键数值必须走**独立文本通道**（现有 `LlmExplainer` 结果直接回显 / 播报模板），**不得依赖语音模型的自然语言复述**。这条不能妥协。

---

## 5. 接入方案设计（若决定做）

### 5.1 新增文件与改动点

| 文件 | 改动 |
| --- | --- |
| `src/asurada/live_session.py`（新增） | `LiveSessionBackend` 抽象 + `GptLiveSessionBackend` 实现（WS 连接、`session.input_audio.append` 供流、`output_audio.delta` 回调播放、转写回调、`session.close` 优雅收尾） |
| `src/asurada/live_delegation.py`（新增） | 委派适配器：读 `session.delegation.created` → 调现有策略/LLM 链 → 回 `response.item.create` + `response.create`；含**去重认领**（防重复触发同一动作） |
| `audio_io.py` | **无需改**（16kHz/mono/s16le 已一致）；仅需确认分块字节数为偶数 |
| `voice_turn.py` | **不改**。新增 `live` 路径旁路 `VoiceTurnManager`，PTT 映射为 `input_audio.mute/unmute` |
| `tts_backends.py:241` | 新增 `live` 分支（或直接在 `live_speech.py` 层拦截，不进 TTS 抽象） |
| `voice_sidecar_asr.py:1302` | 保持豆包分支不动，新增 `live` 分支 |
| `llm_explainer.py:579` | 复用现有 Responses 后端作为委派后端，**不改** |
| 配置 | 新增 env：`ASURADA_VOICE_LIVE_BACKEND`（默认 `off`）、`ASURADA_OPENAI_LIVE_MODEL`、`ASURADA_OPENAI_DELEGATION_MODEL` |

**预估改造量（2026-09-17 修正）**：**新增约 1250–1650 行，现有文件改动 250–400 行**（AEC 另计 150–300 行）。

> ⚠️ 本节早期估计的"新增 600–900 行、改动 <100 行"**偏乐观已作废** —— 漏算了三块硬骨头：**`speech-ipc-v1` 契约扩展**（`speech_service.py:175` 方法白名单 + 幂等/送达校验/停止屏障三处既有语义）、**播放状态二态→三态改造**（`output.py:417-427`，否则 Live 说话期间系统误判 `idle`）、**转写-委派配对器**。
>
> **完整逐文件改动清单见 `GPT_LIVE1_INTEGRATION_CHANGELIST_CN.md`**（含"不动"清单、最高风险改动点与回归判定线）。
>
> "可插拔新增、不重构"这个结论**仍然成立**，但工作量约为此前估计的 **2 倍**。

### 5.2 必须自行实现的三块（官方不给）

1. **播放队列状态机** —— 没有 `output_audio_done`，需自行判定"当前是否在说话"，才能驱动 UI 指示与打断逻辑。
2. **优雅收尾与用量核对** —— 等 `session.closed`（上限 15s）取最终 `usage`；注意**语音时长是累积快照，不可累加**；若在 `session.closed` 前断连，最终用量无法确认。
3. **去重与纠错** —— 委派可能重复投递（须先"认领"）；用户改口（"改成周五"）时须作废在途结果，防止旧结果被当成当前事实播报。

### 5.3 委派模式选择建议

**选 `client` 委派**，理由：

- Asurada 已有完整的策略链与 `LlmExplainer`，属"已有 agent 编排器"的典型场景，`responses` 托管模式等于让 OpenAI 接管推理与工具选择，**丧失策略可控性**；
- `client` 模式下可在适配器里做**结果校验、权限检查、数值格式化**，这是赛车策略的刚需；
- 代价：需自行处理 `session.delegation.created` **不含请求文本**的问题 —— 官方建议从"最近的带角色标记转写片段 + 已验证的应用状态"组装输入。**这一条要重点验证**（见 §8）。

---

## 6. 成本测算

> 汇率：2026-09-17 人民币对美元中间价 **1 USD = 6.7580 CNY**
> 每分钟语音折算约定（官方口径）：用户说话 1 token/100ms ≈ **600 tokens/分**；助手输出 1 token/50ms ≈ **1200 tokens/分**

### 6.1 GPT-Live-1

| 项目 | 美元 | 人民币 |
| --- | --- | --- |
| 语音层（按秒计费，不向整分取整） | $0.05/分钟 | **¥0.34/分钟 · ¥20.27/小时** |
| 委派后端模型 + 工具 | 按所选模型正常计价 | 另计 |

**连续会话时长成本（仅语音层）**：

| 场景 | 人民币 |
| --- | --- |
| 30 分钟 | ¥10.14 |
| 2 小时（正赛） | **¥40.55** |
| 6 小时 | ¥121.64 |
| 24 小时（耐力赛） | **¥486.58** |

> ⚠️ **关键成本陷阱**：计费依据是**会话时长**，不是"说话时长"。若像现有链路那样比赛全程常开麦克风，**即使全程不出声也在持续计费**。`input_audio.mute` **不能省钱**（仍属同一会话），只有**关闭会话**才能止损。
> → **设计要求**：会话按需开合（PTT 按下才建会话，长静默超时即关），而非常驻。

### 6.2 与现有方案对照

| 方案 | 折算单价 | 折算每小时 | 含推理后端 | 延迟 |
| --- | --- | --- | --- | --- |
| **Asurada 现状**（豆包流式 ASR + TTS + LLM） | 约 **¥0.19/分钟** | ¥11.10 | 否（LLM 另计） | 总 <1s（设计预算） |
| 豆包端到端实时语音大模型 | 约 **¥0.41/分钟** | ¥24.48 | 是 | 未实测 |
| **GPT-Live-1**（语音层 + 估算后端） | **¥0.47–1.22/分钟** | ¥28–73 | 需叠加 | 0.798s（官方） |

豆包端到端口径 = 音频输入 ¥80/1M tokens × 600 + 音频输出 ¥300/1M tokens × 1200（火山引擎官方计费表）。
Asurada 现状口径 = 大模型流式语音识别 4.5 元/小时 + 大模型语音合成 5 元/万字符 × 约 220 字/分钟。

### 6.3 成本结论

- **语音层单价**：GPT-Live-1（¥0.34/分钟）**反而低于**豆包自家的端到端实时语音（¥0.41/分钟）—— 这点反直觉，但成立。
- **全链路**：叠加委派后端后，GPT-Live-1 约为现有豆包级联的 **2.5–6 倍**。
- **真实成本驱动因素是「会话常开时长」而非单价** —— 一场 2 小时正赛 ¥40.55 可以接受；但如果是 24 小时耐力赛常开，¥486.58/场，再乘测试轮次就会失控。

---

## 7. 风险清单

| ID | 风险 | 等级 | 说明 | 缓解 |
| --- | --- | --- | --- | --- |
| L-01 | **网络跨境依赖** | 🔴 高 | `api.openai.com` 需代理；实时双向音频流对抖动/断连极敏感，代理抖动会直接表现为吞字、卡顿、会话中断 | 强制走降级链；会话级重连 + 断连即回落豆包；不在比赛链路启用 |
| L-02 | **合规与产品化风险** | 🔴 高 | OpenAI 不向中国大陆提供服务；Phase 3 目标是"实时产品化 + Pi5/CM5 真机"，若随设备出货，代理依赖是产品级阻塞 | 仅限内部/自用场景；出货形态需另行评估境内合规方案 |
| L-03 | **未验证结论被播报** | 🔴 高 | 官方明确：GPT-Live 可在后端工作未完成时开口；扣住工具结果**不能保证**语音层沉默；打断语音**不会**取消后端工作 | 关键播报内容必须在应用侧缓冲 + 审批后才送播；策略数值走独立文本通道 |
| L-04 | **延迟不达标** | 🟠 中高 | 官方轮次延迟 0.798s，已接近现有"总 <1s"预算；叠加跨境 RTT 后必超 | 不用于比赛中实时播报；用于非实时场景 |
| L-05 | **成本失控（常开计费）** | 🟠 中 | 按会话时长计费，`mute` 不减费 | 会话按需开合 + 空闲超时自动关闭 + 用量护栏告警 |
| L-06 | **毫秒级审计链断裂** | 🟠 中 | 转写时间戳非权威，片段可能迟到/重叠，与现有毫秒级 `session_log.jsonl` 观测不兼容 | 审计以应用侧自记时间戳为准，转写仅作展示 |
| L-07 | **PTT 语义冲突** | 🟠 中 | 全双工无轮次边界，现有 PTT+utterance 模型失效 | 新增并行抽象，不改现有 `VoiceTurnManager` |
| L-08 | **AEC 缺失** | 🟠 中 | 全双工下回声/自激问题比轮次式严重得多，现有链路无 AEC | 接入前必须先解 AEC，否则外放场景不可用 |
| L-09 | **无结构输出保真** | 🟡 中 | 语音层自然语言复述不保证数值忠实 | 数值走文本通道/播报模板 |
| L-10 | **配额与可用性** | 🟡 低中 | 限流按**并发会话数**（Tier1=25）；Free 层不支持；无 mini 变体可降本 | 确认账号 Tier；压测并发 |
| L-11 | **供应商锁定** | 🟡 低中 | 官方明言"不是改 model ID 就能迁移"，端点/事件体系独立 | 抽象层隔离，保留豆包为对等实现 |
| L-12 | **音频水印** | 🟡 低 | API 生成音频带 SynthID 水印 | 知悉即可；若对外发布需评估 |

---

## 8. 待验证清单（动手前必须闭环）

以下问题**公开资料无法确认**，属 PoC 必须先打掉的钉子：

| # | 待验证项 | 验证方式 | 影响 |
| --- | --- | --- | --- |
| Q1 | **`client` 委派模式下，如何拿到"该委派对应的用户原话"** —— 官方明确 `session.delegation.created` 不含请求文本 | 见专项文档 `GPT_LIVE1_Q1_DELEGATION_TRANSCRIPT_CN.md`；核心指标 **Δ_P95 ≤ 300ms**、碎片化率 ≤ 5%、时间轴同基准 | **决定 `client` 模式是否可用** —— 详见专项文档 §5（修正："可控性归零"→"路由权/取证权/时序权三移交"） |
| Q2 | **跨境代理下 WebSocket 长连接的稳定性与 RTT** 实测 | 在目标网络（含 FlClash）下跑 30min/2h 连续会话，统计断连率、抖动、首音延迟 | 决定 L-01/L-04 是否致命 |
| Q3 | **16kHz 实测音质**（官方默认 24kHz，16kHz 为可选档） | 用 16kHz 与 24kHz 各跑一轮，对比识别准确率 | 若 16kHz 明显劣化，需在 AudioIO 层加 16k→24k 重采样 |
| Q4 | **账号 Tier 与配额** | 查 OpenAI 后台 Tier 与并发上限 | 决定能否支撑多路并发 |
| Q5 | **数值播报失真率** | 构造 20 组策略数值问答，比对语音输出与源数据 | 验证 L-03/L-09，决定是否需要独立文本播报通道 |
| Q6 | **`session.close` 收尾可靠性** | 统计 15s 内 `session.closed` 到达率 | 影响用量确认与成本核算准确性 |
| Q7 | **无 `output_audio_done` 下的"正在说话"判定准确性** | 观察播放队列与实际音频的吻合度 | 影响打断体验 |
| Q8 | **AEC 方案选型**（WebRTC AEC / speexdsp / 硬件回采） | 外放场景实测自激情况 | **阻塞项**，未解则外放不可用 |
| Q9 | **`session.update` 中途切换后端模型的时延影响** | 实测切换瞬时是否出现静默或抢话 | 影响多轮策略切换体验 |
| Q11 | **`commentary.append` 能否触发语音层自我打断** | 高优先级 append 到达时，观察当前语句是否被打断及延迟 | 决定"客户端播放抢占"缓解方案的形态（详见 §8.5） |

---

## 8.5 场景推演：后车逼近、进攻姿态明显（防守窗口触发）

这是比赛中**时效性最强、容错最低**的语音场景，单独推演一次，检验两种范式在真实压力下的行为差异。

### 8.5.1 现有链路的行为（已核对代码）

1. 遥测 `gap_behind_s` 收缩 → 仲裁器置 `tactical_state = defence_active`
2. `arbiter.py:326-331`：`defence_active` / `counterattack_active` **无条件 `interrupt=True`**（DEFEND_WINDOW / ATTACK_WINDOW / SAFETY_CAR 同级）
3. `output.py:276-288`：新消息优先级更高且当前播报可取消 → `cancel_requested` → 等 TTS 后端**停播确认** → 当前语音被拦腰截断（`preempted_by_higher_priority`）→ 防守播报立即起播
4. 文本是遥测直渲染（`rivals.py:169`：`后车差距只有 {gap_behind:.3f} 秒`），数值精确到千分位；TTS 首音 200~500ms，总延迟 <1s
5. **触发与车手是否在说话无关** —— 系统主动推、可抢占、可审计

### 8.5.2 换成 GPT-Live-1 语音层后的行为

| 环节 | GPT-Live-1 实际行为 | 后果 |
| --- | --- | --- |
| 应用想推防守警报 | 只能 `session.commentary.append`（`delegation_id=null`，≤500 token）。**没有 priority 字段、没有 interrupt 字段、没有冷却语义**；官方明确 "acceptance does not mean spoken or played" | 送达 ≠ 播报，何时说、说不说，由语音层自行决定 |
| 语音层正在说话（如正在答车手上一个燃油问题） | **没有任何 API 能让它闭嘴**。打断只能来自车手本人的 barge-in；"A corrective instruction cannot retract audio already heard" | 现有链路最核心的「防守警报拦腰截断当前播报」能力（`arbiter.py:329`）**无法表达** |
| 语音层复述警报 | 用自己的话措辞 —— 可能加铺垫、加对冲（"看起来后方可能……"） | 千分位时差变成模糊口语（L-09）；`claims`/Decimal 重建机制管不到语音层的嘴 |
| 延迟 | 官方轮次延迟 0.798s + 跨境 RTT + 语音层自行组织语言的时间 | 防守窗口通常只有 2~4 秒，警报可能落在刹车点之后 |
| 持续监听的副作用 | 重刹、连续降挡、车队无线电通话都可能被前端当成"车手在说话" → 误委派或模型在防守时刻自己开口抢话 | 现有链路有 `WakeWordGate` 门控，GPT-Live 无此概念（能否用 instructions 压制未知，需实测） |

**但有一个方向 Live-1 反而更强**：如果**车手主动喊**（"他压上来了！怎么防？"）—— 全双工能听到半截的喊话、不需要按 PTT、车手可以随时打断它的回答、它能自然接话。这些是现有轮次式链路做不到的（PTT + utterance 边界 + 串行 ASR→路由→LLM→TTS）。

### 8.5.3 结论与缓解

- **推（系统主动警报）**：GPT-Live 结构性不适任 —— 三大支柱（priority / interrupt / cancelable）在其事件 schema 里**没有对应物**。警报必须留在本地/豆包链路。
- **拉（车手主动问）**：GPT-Live 体验优于现有链路。
- **唯一可行缓解（若坚持全走 Live-1）**：**客户端播放抢占** —— 播放队列在应用自己手里（反正也没有 `output_audio_done`，播放本就靠客户端自跟踪），DEFEND_WINDOW 触发时应用自己 flush 播放队列、插播本地警报、再恢复。代价：模型不知道自己的话被丢了，后续轮次可能引用车手没听过的内容，产生对话状态分裂；且模型仍在持续生成被丢弃的音频。
- **建议补验证项 Q11**：`commentary.append` 到达时，语音层是否会**自我打断**当前语句？若会，延迟多少？（若可靠 <500ms，客户端抢占可降级为"纯提示式"，状态分裂问题大幅减轻）

---

## 9. 分阶段落地路径

### 阶段 A：可行性 PoC（建议 3–5 天，独立目录，不碰主链）

- 用官方 Python 示例起一个最小客户端，接本地麦克风/文件，打通"16kHz PCM ↔ GPT-Live"闭环。
- **只验证 Q1 / Q2 / Q3 / Q7** —— 这四项决定方案生死。
- 产出：PoC 结论 + 实测延迟/断连/识别数据。
- **退出条件**：Q1 无法解决（拿不到委派对应原话）或 Q2 断连率过高 → **立即终止，不做后续**。

### 阶段 B：并行抽象接入（建议 1–2 周）

- 新增 `live_session.py` / `live_delegation.py`，env 开关默认 `off`。
- 复用 `OpenAiResponsesLlmExplainerBackend` 作委派后端；旁路 `VoiceTurnManager`。
- 补齐播放队列状态机、优雅收尾、去重认领。
- **不修改**豆包链路任何代码。

### 阶段 C：限场景灰度（建议 1 周）

- 只放开**赛后复盘问答 / P 房讲解**两个场景。
- 建立延迟、断连、成本三项指标看板；设用量护栏。
- 与豆包链路做同一批录制场景的 A/B（对比完整会话结果，不比单轮演示）。

### 阶段 D：决策点

按灰度数据决定三选一：
1. **保留为 L0 高质量档**（推荐，与豆包 L1、本地 L2 组成降级链）；
2. 扩大到更多场景；
3. 回退下线（若 L-01/L-02 无法缓解）。

---

## 10. Go / No-Go 建议

| 用途 | 建议 | 理由 |
| --- | --- | --- |
| **比赛中实时策略播报** | ❌ **No-Go** | 延迟超预算 + 未验证结论可能被播报 + 网络不可依赖 |
| **赛后复盘 / P 房讲解 / 训练问答** | ✅ **Go（灰度）** | 延迟不敏感、表达质量要求高、成本可控、可随时回落豆包 |
| **替代现有豆包级联主链** | ❌ **No-Go** | 成本 2.5–6 倍、丢失离线能力、合规风险、需重写 PTT 范式 |
| **作为可插拔高质量档（L0）** | ✅ **Go** | 新增式改造 <100 行侵入、复用度高、风险隔离好 |

**最终建议**：**先做阶段 A 的 PoC，把 Q1（委派原话可得性）和 Q2（跨境长连接稳定性）这两个死穴验证掉。** 这两项都过关，再投阶段 B/C；任一项不过关，直接放弃，继续打磨现有豆包 + 本地降级链 —— 那是更稳的路线。

---

## 附录 A：官方事实来源

| 事实 | 来源 |
| --- | --- |
| 端点、事件表、音频格式、Python SDK | `developers.openai.com/api/docs/guides/voice-websockets` |
| 四类连接方式（WebRTC / WebSockets / Sideband / Telephony·SIP） | `developers.openai.com/api/docs/guides/live` |
| 会话配置、委派两种模式、500 token 上限、`delegation.created` 仅元数据 | `developers.openai.com/api/docs/guides/live`、`live-migration` |
| 迁移差异（无轮次结束事件、函数调用→委派、提示词拆分、12 条 caveat） | `developers.openai.com/api/docs/guides/live-migration` |
| 定价 $0.05/分钟、并发配额、模态与特性矩阵、无 mini 变体 | `developers.openai.com/api/docs/models/gpt-live-1` |
| 12 个预置音色、0.798s 轮次延迟、基准数据、SynthID 水印 | OpenAI 开发者社区发布帖（2026-09-10）、`openai.com/index/introducing-gpt-live` |
| 豆包计费（流式 ASR 4.5 元/小时、TTS 5 元/万字符、端到端实时语音输入 80 / 输出 300 元每百万 token） | `volcengine.com/docs/6561/1359370` |

## 附录 B：Asurada 侧代码证据索引

| 结论 | 证据位置 |
| --- | --- |
| 音频格式 16kHz/mono/s16le | `audio_io.py:13`、`:170-171` |
| TTS 抽象 4 方法（不适配流式会话） | `tts_backends.py:18`、`:21-35` |
| 流式会话抽象样板 | `voice_sidecar_asr.py:88`、`:121` |
| 豆包流式 ASR WS 端点 | `voice_sidecar_asr.py:344`、`:362` |
| 现有 OpenAI Responses 客户端（可复用为委派后端） | `llm_explainer.py:111`、`:175` |
| 现有 OpenAI env 键 | `llm_explainer.py:133-137` |
| PTT + utterance 范式（冲突点） | `voice_turn.py:55-60`、`:116-233` |
| 能量 VAD | `vad.py:47-67`、`:70-82` |
| 延迟预算"总 <1s" | `REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md:325-336` |
| 后端切换入口 | `tts_backends.py:241`、`voice_sidecar_asr.py:1302`、`llm_explainer.py:579` |

---

*本调研基于 2026-09-17 公开资料与 Asurada 当前代码快照。GPT-Live-1 为新产品，定价、音色列表、后端模型命名（Terra/Luna 等）与配额均可能变动，动手前请复核官方页面。*

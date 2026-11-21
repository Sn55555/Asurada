# GPT-Live-1 全双工适配改动清单

> 日期：2026-09-17
> 归属：`GPT_LIVE1_VOICE_INTEGRATION_FEASIBILITY_CN.md` §5 的落地细化
> 关联：`GPT_LIVE1_Q1_DELEGATION_TRANSCRIPT_CN.md`、`REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md`
> 说明：本文档只回答"**改哪里、改成什么、为什么必须改**"，不含排期承诺

---

## 0. 先做一个不可回避的决策：Live 音频走谁的手

这是所有改动的**前提**，定错了后面全白做。

现有链路的播放权是**集中式**的：`SpeechService`（`speech_service.py:83`，per-user Unix socket `/tmp/asurada-speech-<uid>/voice.sock`）是唯一播放拥有者，通过 `speech-ipc-v1` 协议对外提供 `emit*` 方法，并由 `_validate_delivery`（`speech_service.py:149`）校验"产出是否真的送达"，靠 `_stop_barrier`（`speech_service.py:229`）实现停止屏障。

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| **A（推荐）统权** | Live 音频也由 `SpeechService` 播放，新增 streaming 方法族 | 需动播放权核心，但**抢占语义统一在一处** |
| B（分权） | Live 由新进程自播，`SpeechService` 只管本地警报 | 改动小，但**两个播放者会抢音频**，DEFEND_WINDOW 拦不住 Live 音频（见 §3.3） |

**选 A。** 原因很直接：§8.5 推演里唯一能让防守警报压住当前播报的机制是 `arbiter.py:329` → `output.py:276-288` 的优先级抢占。如果 Live 音频游离在这套机制之外，这个能力就永久丢失 —— 那不是"少个功能"，是**把比赛链路最关键的一秒让出去**。

---

## 1. 服务层：新增一个独立进程

| 文件 | 类型 | 改动内容 |
| --- | --- | --- |
| `src/asurada/live_server.py` | **新增** | Live 会话宿主进程：WS 长连接、抖动缓冲、断连重连、与 `SpeechService` 的 IPC 桥 |
| `src/asurada/__main__.py` | 改 | 新增子命令入口（对标现有 sidecar 启动方式） |

**为什么必须是独立进程**：`SpeechService.dispatch` 全程持有 `_dispatch_lock`（`speech_service.py:185`），它是**短请求串行**模型。WS 长连接 + 跨境抖动绝不能被塞进这把锁里，否则本地警报会被网络卡住 —— 这正好会毁掉最需要它的那一秒。

**为什么不复用 `voice_sidecar_server.py`（8788）**：该文件已承载 `/v1/explainer`、`/v1/asr/transcribe`、`/v1/tts/render|stream` 与一个 raw TCP ASR 流服务（`voice_sidecar_server.py:321`、`:454`）。把跨境 WS 会话挂进同一个进程，一旦 Live 侧异常会连带豆包链路 —— 违背"豆包链路零回归"这条底线。**独立端口、独立进程、独立启停。**

---

## 2. 契约层：新增两个核心模块

### 2.1 `src/asurada/live_session.py`（新增）

`LiveSessionBackend` 协议，方法签名对齐 A 方案：

| 方法 | 职责 | 可复用样板 |
| --- | --- | --- |
| `connect()` | 握手 + `session.update`（instructions / 音色 / `session.audio.format`） | — |
| `append_audio(pcm: bytes)` | 发 `session.input_audio.append` | `audio_io.py` 的分块循环 |
| `on_output_audio(delta)` | 收 `session.output_audio.delta` → 交 `SpeechService` 播放 | `_VoiceSidecarSpeechHandle`（`tts_backends.py:177-236`） |
| `on_input_transcript(delta)` | 收 `session.input_transcript.delta`（仅作**旁路参考**，不作权威源，见 Q1 文档） | — |
| `on_delegation(event)` | 收 `session.delegation.created` → 转 `live_delegation` | — |
| `close()` | `session.close` → 等 `session.closed`（上限 15s）取最终 `usage` | — |

**关键复用**：`_VoiceSidecarSpeechHandle` 的 `thread + state + PlaybackControl` 三元组（`tts_backends.py:177-181`）就是 live 播放句柄的现成模板；`PlaybackControl.cancel()`（`playback_control.py:44`）是把 live 音频纳入抢占体系的**现成原语**。

### 2.2 `src/asurada/live_delegation.py`（新增）

委派适配器，调用序列必须在**应用侧**完成，不得交给 Live：

```
delegation.created
  → ① 认领（去重，防重复执行）
  → ② 组装原话（来自 §4 的本地权威 ASR，不是 Live 的转写）
  → ③ TranscriptRouter.route()            ← 路由权不能丢
  → ④ lane == explainer ? LlmExplainer.run() : companion 分支
  → ⑤ validate_evidence + render_claims   ← 取证权不能丢
  → ⑥ 压缩到 ≤500 token
  → ⑦ session.commentary.append（带 delegation_id）
```

第 ③⑤ 步是**资产保护的关键**：少任何一步，就是在`responses` 托管模式的下场（路由权/取证权移交，见可行性报告 §5）。

**必须新增的子组件**：
- **委派认领存储**（去重）—— 官方硬性要求；可复用 `delivery_context.py` / `task_runtime.py` 的认领与取消思路
- **文本压缩层** —— `commentary.append` 上限 500 token，装不下整个 `state_summary`。需把校验后的最终答句压到上限内，而非把上下文塞给语音层

---

## 3. 播放权与抢占：最硬的改动（原报告低估了这里）

### 3.1 `speech_service.py:175` `dispatch` —— 方法白名单扩容

现有白名单是**封闭**的（`health` / `is_playing` / `playback_status` / `events` / `bind_session` / `emit*`），未知方法直接 `unsupported_speech_operation`。需要新增 streaming 方法族（如 `live_open` / `live_audio` / `live_close`）。

**三个必须处理的既有语义**：

| 机制 | 位置 | 冲突 |
| --- | --- | --- |
| 幂等（`request_id` + 内容指纹） | `speech_service.py:180-184` | Live 音频**没有请求**可指 —— 需要为流式音频设计新的幂等键（按 `session_id + 序号`） |
| 送达校验 `_validate_delivery` | `speech_service.py:149` | 现语义是"请求 → 产出 → 送达"。流式音频是**非请求驱动**的，无法套用 |
| 停止屏障 `_stop_barrier` | `speech_service.py:229` | **必须保留并覆盖 live 音频**，否则本地警报压不住它 |

### 3.2 `output.py:417-427` `playback_status` —— 必须从二态扩为三态

现状：

```python
def playback_status(self) -> dict:
    if self._active_envelope is None:
        return {'version': 'playback-status-v1', 'status': 'idle', ...}
    active = self.backend.is_active(self._active_handle)
    return {..., 'status': 'playing' if active else 'idle', ...}
```

而 `is_playing()`（`output.py:416`）就建立在它之上。**问题**：Live 音频不经过 envelope，所以 Live 正在说话时 `_active_envelope is None` → 系统认为 `idle` → **"正在说话"判定失真**，直接打中已验证的 **Q7 / L-03**。

必须新增第三种状态（如 `live_streaming`），并让 `is_playing()` 覆盖它。

### 3.3 抢占路径：`arbiter.py` 不动，但 output 侧要扩

`arbiter.py:326-331` 的抢占规则本身是对的，**不改**：

```python
def _should_interrupt(self, *, primary_code, tactical_context) -> bool:
    if tactical_context.state_lock: return True
    if tactical_context.tactical_state in {"defence_active", "counterattack_active"}: return True
    return primary_code in {"SAFETY_CAR", "DEFEND_WINDOW", "ATTACK_WINDOW"}
```

要改的是它的**下游**：`output.py:276-288` 的抢占实现目前只认 `_active_envelope`。需要让 Live 音频也纳入同一抢占入口 —— 停播确认后 `PlaybackControl.cancel()` 掉 live 播放句柄，再起播本地警报。

⚠️ **这一处是本项目最高风险改动点**：它同时触碰播放权核心与比赛关键路径，必须做回归测试（见 §9）。

---

## 4. 输入链路：旁路并行，不动现有

| 文件 | 类型 | 改动内容 |
| --- | --- | --- |
| `audio_io.py` | **不改** | 16kHz/mono/s16le 与 Live 原生格式一致（`audio_io.py:170-171`） |
| 新增 PCM 分流 | **新增（小）** | 同一路 PCM 双写：一份进 Live WS，一份进现有豆包流式 ASR |
| `voice_sidecar_asr.py:675` | **复用不改** | `open_realtime_session` 直接当**本地权威原话源**（S1，详见 Q1 文档 §6） |
| `voice_turn.py` | **不改** | Live 路径旁路 `VoiceTurnManager`；PTT 映射为 `session.input_audio.mute/unmute` |
| `src/asurada/live_align.py` | **新增** | 转写-委派配对器：算 Δ 指标、处理"一次委派跨多片段"与"一片段触发多次委派" |

**原话为什么要自己造**：Live 的 `session.input_transcript.delta` 是片段、可能迟到、时间戳官方声明**非权威轮次边界**；而 Asurada 全链是 utterance-level 原子契约。用现有豆包流式 ASR 做**权威源本地化**，才能保住 `validate_evidence` / `render_claims` 两道闸门。

---

## 5. 配置与开关

**三处 `resolve_*` 函数加分支（现有分支全部保持不动）**：

| 位置 | 现状 | 改动 |
| --- | --- | --- |
| `tts_backends.py:241` `resolve_default_speech_backend` | null / voice_sidecar / piper / say | 新增 `live` 分支 |
| `voice_sidecar_asr.py:1302` `resolve_voice_sidecar_asr_backend` | 豆包系列 | 新增 `live` 分支 |
| `llm_explainer.py:579` `resolve_default_llm_explainer_backend` | null / command / openai / voice_sidecar / doubao* | **不改** —— 复用现有 `OpenAiResponsesLlmExplainerBackend`（`llm_explainer.py:111`）作委派后端 |

**新增环境变量**（全部默认 **off**，保证不启即零影响）：

```
ASURADA_VOICE_LIVE_BACKEND=off          # off | on
ASURADA_LIVE_WS_URL=wss://api.openai.com/v1/live/sessions
ASURADA_OPENAI_LIVE_MODEL=
ASURADA_LIVE_DELEGATION_MODE=client     # client（推荐）| responses
ASURADA_LIVE_VOICE=
ASURADA_LIVE_BIND_HOST=127.0.0.1
ASURADA_LIVE_BIND_PORT=
ASURADA_LIVE_IDLE_TIMEOUT_S=            # 空闲自动关会话（成本护栏，防常开计费）
ASURADA_LIVE_AEC=                        # off | speexdsp | webrtc
```

---

## 6. 必须自建的五块（官方一律不给）

| # | 能力 | 为什么官方不给 / 影响 |
| --- | --- | --- |
| 1 | **播放队列状态机 + "正在说话"判定** | 无 `output_audio_done` 事件，官方原文要求客户端自行跟踪播放；影响 Q7 / §3.2 三态改造 |
| 2 | **优雅收尾与用量核对** | 等 `session.closed`（上限 15s）；**语音时长是累积快照，不可累加**；断连时最终用量不可确认 → 影响成本护栏 |
| 3 | **委派认领去重** | 官方硬性要求"先 claim，防重复投递导致同一操作执行两次" |
| 4 | **转写-委派配对** | 委派事件无关联 ID，只能靠时间窗；Δ_P95 ≤ 300ms 是 Q1 的验收线 |
| 5 | **AEC / 自激抑制** | 全双工下回声问题远重于轮次式；**外放场景的阻塞项**（Q8） |

---

## 7. 明确"不动"清单（资产保护）

以下文件**本次适配一行不改**，任何改动提案需单独评审：

- `voice_turn.py` —— PTT + utterance 原子模型
- `arbiter.py:326-331` —— 抢占规则本身
- `voice_nlu.py` / `transcript_router.py` —— 路由与查询契约
- `llm_evidence.py` / `llm_claims.py` / `answer_policy.py` —— 三道回程闸门
- `audio_io.py` —— 音频格式与分块
- 豆包链路全部（`voice_sidecar_asr.py` 现有分支 / `voice_sidecar_server.py` 现有路由 / `tts_backends.py` 现有后端）

---

## 8. 改动量汇总（含对原报告的修正）

| 模块 | 类型 | 估行 |
| --- | --- | --- |
| `live_session.py` | 新增 | 400–500 |
| `live_delegation.py` | 新增 | 250–350 |
| `live_server.py` | 新增 | 200–300 |
| `live_align.py`（配对器） | 新增 | 150–250 |
| speech-ipc 扩展（服务端 + 客户端） | 改 | 200–300 |
| 播放状态三态 + 抢占接入 | 改 | 100–150 |
| PCM 分流 + 用量/收尾/审计 | 新增 | 250–350 |
| 配置与三处 resolve 分支 | 改 | 50–100 |
| **小计（不含 AEC）** | | **新增 1250–1650 / 现有改动 250–400** |
| AEC 集成（选型后另计） | 新增 | 150–300 |

> ⚠️ **修正原报告 §5.1**：原先估"新增 600–900 行、现有改动 <100 行"**偏乐观**。漏算了三块：**speech-ipc 契约扩展**、**播放状态三态改造**、**转写-委派配对器**。修正后为**新增 1250–1650 行 / 现有文件改动 250–400 行**（AEC 另计）。"可插拔新增、不重构"这个结论仍然成立，但工作量约为此前估计的 **2 倍**。

---

## 9. 最高风险改动点与回归清单

| 风险点 | 位置 | 必须做的验证 |
| --- | --- | --- |
| 播放权核心被动 | `speech_service.py:175` dispatch | 现有 `emit*` 全部路径回归；`_stop_barrier` 行为不变 |
| 抢占链路被动 | `output.py:276-288` | 防守/反击/安全车抢占仍在 <1s 内生效；Live 音频可被截断 |
| 播报状态失真 | `output.py:417-427` | Live 说话期间 `is_playing()` 必须为 true |
| 豆包链路回归 | 全部现有分支 | env `off` 时**行为逐字节一致** |

**回归判定线**：`ASURADA_VOICE_LIVE_BACKEND=off` 时，现有链路行为与改动前**完全一致** —— 这是整个适配能否被接受的前提。

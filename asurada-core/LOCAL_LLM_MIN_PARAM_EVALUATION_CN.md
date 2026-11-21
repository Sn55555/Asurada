# Asurada 全链路本地大模型承载量评估报告

日期：2026-06-25

## 结论摘要

这份报告修正一个关键口径：这里评估的不是“解释旁路需要多大 LLM”，而是：

> 如果把当前 Asurada 的全部实时数据输入、内置规则/小模型计算量、再加双向流式语音负载，都交给本地大模型承载，多少参数量能实时处理？

结论分三层：

1. **原始 packet / 全量状态 / 全量 debug 直接交给 LLM：不可行。**
   - 这不是 4B、8B、12B 的差别，而是 LLM 的 token 吞吐模型不适合 150 packet/s 和 10Hz 状态循环。
   - 参数越大越慢；参数越小越不可靠。没有一个“合适参数量”能同时吃全量输入、替代内置模型、保持双流语音实时。

2. **如果 LLM 替代 10Hz 策略主循环：理论上只能压到 1B - 2B 级，仍不建议。**
   - 10Hz 意味着每帧决策预算约 `100ms`。
   - 即使每帧只喂 800 tokens，prefill 也需要 `>= 8,000 tokens/s` 才刚够，不含输出和调度。
   - 1B - 2B 可能接近速度要求，但赛车策略、拒答、结构化输出和中文解释可靠性不足。

3. **可落地方案是“主链不交给 LLM，LLM 只吃压缩事件/摘要”。**
   - 10Hz 主链继续由现有规则 + LightGBM + deterministic scorer 承担。
   - LLM 只在语音 turn 或低频事件上读取 compact state / sidecar scores。
   - 在这个架构下，双流语音实时可用的本地 LLM 建议为：
     - `2B - 3B`：低风险摘要 / companion / fallback。
     - `3.8B - 4.5B`：正式 explainer 下限。
     - `7B / 8B`：桌面增强，不是实时最小方案。

最终判断：

```text
全量直接交给本地大模型：不可行。
硬要 LLM 承担实时主循环：最多只能考虑 1B - 2B，但质量不达标。
工程可用的实时双流语音方案：保留当前主链 + 4B 级 on-demand LLM。
```

## 当前项目真实负载

### 输入吞吐

从仓库抓包和 runtime log 抽样统计：

| 输入面 | 实测/抽样结果 |
| --- | ---: |
| live UDP 抓包 | `542,201` packets / `3,702.335s` |
| live UDP packet rate | `146.45 packet/s` |
| F1 25 抓包 | `666,921` packets / `4,380.805s` |
| F1 25 packet rate | `152.24 packet/s` |
| 平均 packet 大小 | `~1,040 bytes` |
| packet p95 大小 | `1,460 bytes` |
| 组帧后 session log 样本 | `~10.1 frame/s` |
| 组帧 timestamp gap | median `97ms`，p95 `118ms` |

所以当前输入不是“每秒一句话”级别，而是：

```text
raw packet:   ~150 packet/s
raw bytes:    ~150 KB/s binary payload
state frame:  ~10 Hz
```

如果把 raw packet 转成可给 LLM 的文本，至少会经过 JSON/base64/字段名展开。保守按 `4 bytes/token` 估算：

```text
150 packet/s * 1,040 bytes = 156,000 bytes/s
156,000 / 4 ~= 39,000 tokens/s
```

这还是非常乐观的下界。真实 JSON/base64 展开后会更高。也就是说，直接把 packet 流交给 LLM，单是输入 prefill 就需要数万 tokens/s，且上下文会在数秒内填满。

### 全量状态输出

当前 `session_log` 每帧包含 normalized state、raw、debug、arbiter、voice pipeline、output lifecycle 等信息。抽样文件约 `16.8MB / ~197 rows`，约 `85KB/row`。

按 10Hz 计算：

```text
85 KB/frame * 10 frame/s = 850 KB/s
850 KB/s / 4 bytes/token ~= 212,500 tokens/s
```

这说明：**全量状态/debug 日志绝对不能作为 LLM 输入流。**

### 当前内置模型计算量

当前 runtime 里的“模型”主要是 LightGBM / deterministic scorer / 规则仲裁，不是神经大模型。

从训练报告中的 `model_path` 汇总：

| 项 | 数值 |
| --- | ---: |
| 可发现模型文件 | `24` 个 |
| 唯一模型总大小 | `13.54 MB` |
| 最大单模型 | `2.2 MB` |
| 常见单模型 | `几十 KB - 1.1 MB` |

当前 runtime 采样延迟：

| 阶段 | avg | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| decode | `0.054ms` | `0.047ms` | `0.095ms` | `0.107ms` | `1.375ms` |
| assemble | `0.307ms` | `0.273ms` | `0.537ms` | `0.943ms` | `12.638ms` |
| strategy | `2.084ms` | `2.024ms` | `3.475ms` | `4.163ms` | `18.178ms` |
| output | `0.524ms` | `0.533ms` | `0.775ms` | `0.975ms` | `8.917ms` |
| pipeline | `3.103ms` | `3.080ms` | `4.953ms` | `5.775ms` | `20.824ms` |

结论：

```text
当前内置模型/规则链是毫秒级。
LLM 不是在替代一个“慢模型”，而是在替代一个 10Hz、p95 < 5ms 的实时控制链。
```

这就是为什么“把全部交给本地 LLM”在工程上不成立。

## 双流语音约束

项目文档给出的双向语音目标：

- ASR partial：`100ms - 300ms`
- 指令路由：`< 50ms`
- 状态查询 / 策略判断：`< 50ms`
- TTS 首音：`200ms - 500ms`
- 说完到开始回答：尽量 `< 1s`

当前代码中：

- LLM explainer 默认超时：`1800ms`
- voice sidecar 默认超时：`2500ms`
- companion 超时可放宽到 `3200ms`

双流语音意味着系统至少同时承载：

```text
上行：Mic -> VAD / ASR / transcript routing
下行：LLM or structured response -> TTS stream -> playback
背景：UDP decode -> state -> strategy -> output arbitration
```

因此 LLM 不能长期占满 CPU/GPU/NPU。否则 ASR partial、TTS 首音和下行播放都会抖。

## 直接交给 LLM 的数学约束

### 10Hz 主循环约束

组帧后约 `10 frame/s`，所以单帧预算：

```text
B_frame = 1 / 10 = 100ms
```

LLM 单帧处理时间：

```text
T_frame = C_in / S_prefill + C_out / S_decode + T_overhead
```

其中：

- `C_in`：每帧输入 tokens
- `S_prefill`：prompt 处理 tokens/s
- `C_out`：输出 tokens
- `S_decode`：生成 tokens/s

如果喂 compact state，每帧仍按 `800 tokens` 算，且先不输出：

```text
800 / S_prefill <= 0.1
S_prefill >= 8,000 tokens/s
```

如果喂 `2,000 tokens`：

```text
2,000 / S_prefill <= 0.1
S_prefill >= 20,000 tokens/s
```

这还没算模型生成、Python/HTTP 调度、schema 校验、ASR/TTS 抢占。对本地 3B/4B/8B 模型来说，这不是正常可持续工作区间。

### 原始 packet 流约束

raw packet 文本化下界约 `39,000 tokens/s`。LLM 若要持续阅读：

```text
S_prefill >= 39,000 tokens/s
```

而且它还要保留状态、生成动作、处理语音。这个量级已经超出“选多少参数”能解决的范围。

### 当前内置模型替换约束

当前策略链 p95 约 `4.953ms`，p99 约 `5.775ms`，max `20.824ms`。如果 LLM 替代这条链，哪怕放宽到 `50ms`，每帧也只有：

```text
T_llm_decision <= 50ms
```

在 50ms 内完成 prompt、推理、schema 输出和仲裁，本地 LLM 基本只能是极小模型或专用小网络。此时它已经不是“能理解赛车全局态势的大模型”，而更像一个小分类器。那就不如保留现有 LightGBM/规则链。

## 参数量分层

| 参数级别 | 能否吃全量 packet/state | 能否替代 10Hz 主策略链 | 能否做双流语音 on-demand explainer | 结论 |
| --- | --- | --- | --- | --- |
| `< 1B` | 否 | 速度可能接近，但能力不足 | 只适合极短模板/分类 | 不建议作为 LLM 大脑 |
| `1B - 2B` | 否 | 理论速度上限区间，策略可靠性不足 | 可做低风险 fallback | 只能做辅助 |
| `2B - 3B` | 否 | 仍不适合 10Hz 主链 | 可做摘要/companion | 降级档 |
| `3.8B - 4.5B` | 否 | 不适合持续 10Hz 主链 | 正式 explainer 下限 | 推荐 on-demand |
| `7B - 8B` | 否 | 不适合 | 质量更稳但时延/内存压力大 | 桌面增强 |
| `12B+` | 否 | 不适合 | 不适合实时双流 | 赛后/工作站 |

## 公开模型报告对应关系

### Qwen

Qwen3.5-4B 模型卡给出：

- 上下文 `262,144` tokens，可扩展到 `1,010,000`。
- Qwen3.5-4B 在 MMLU-Pro、IFEval、MMMLU、多语言等指标上已进入可用区间。
- 支持 SGLang / vLLM / Ollama / LM Studio / MLX-LM / llama.cpp 等本地路径。

Qwen3-4B-Instruct-2507：

- non-thinking mode，不生成 `<think>`，更适合低延迟直答。
- IFEval、Creative Writing、WritingBench、BFCL 等指标说明 4B instruct 已能承担结构化指令跟随和短解释。

这支持 `4B` 作为 on-demand explainer 的下限，但不支持它替代 10Hz 主循环。

### Gemma 4

Gemma 4 模型卡给出：

- E2B：`2.3B effective / 5.1B with embeddings`
- E4B：`4.5B effective / 8B with embeddings`
- E2B / E4B 面向 edge / mobile，支持 text、image、audio，128K context。
- Google AI Edge 当前只支持 E2B / E4B，并给出 Edge 侧性能表：E2B 模型大小 `2.58GB`，E4B 模型大小 `3.65GB`。
- 该表中 macOS 参考设备上，E2B GPU prefill `7,835 tok/s`、decode `160 tok/s`；E4B 在 MacBook Pro M4 Max 上 GPU prefill `2,560 tok/s`、decode `101 tok/s`，peak CPU memory `3,217MB`。
- Multi-Token Prediction 可提升 decode speed；Google 对 E4B CPU 和 GPU 任务均建议开启 MTP。

这支持 `2B - 4B` 作为边缘语音和摘要模型区间。E4B 更适合正式 explainer；E2B 更适合低风险 fallback。

### Phi-4-Mini / Llama 3.2

Phi-4-Mini 报告显示 `3.8B` 小模型可以在部分推理和代码任务上匹配更大模型，说明 3.8B 是“小模型可认真做任务”的临界点。

Llama 3.2 的 1B / 3B 定位是 on-device agentic / summarization / tool-use。它说明 1B-3B 能做设备端助手，但不等于能接管赛车 10Hz 策略主链。

## 推荐架构

### 不推荐

```text
UDP/raw state + ASR + TTS + strategy -> single local LLM -> output
```

原因：

- raw packet 输入约 `150 packet/s`。
- state frame 约 `10Hz`。
- 当前主链 p95 约 `5ms`，LLM 替代会把毫秒级链路拉到百毫秒或秒级。
- 双流语音还要争用 ASR/TTS 音频资源。

### 推荐

```text
10Hz UDP/state/strategy:
  decode + rules + LightGBM + deterministic scorer + arbiter

低频事件摘要:
  sidecar scores + compact state + recent trend

双流语音:
  ASR/VAD/route 本地快路径
  structured query 直接查 state
  explainer 才调用 4B LLM
  TTS streaming 独立抢占/降级
```

### 参数配置建议

| 模块 | 推荐参数量 | 频率 | 说明 |
| --- | ---: | ---: | --- |
| 10Hz 主策略链 | 不用 LLM | `10Hz` | 保留现有规则 + LightGBM |
| 背景状态摘要 | `1B - 2B` 或规则摘要 | `0.5 - 1Hz` | 可选，不影响主链 |
| 双流语音 structured | 不用 LLM | 按语音 turn | 直接查 state / response_composer |
| 双流语音 explainer | `3.8B - 4.5B` | 按语音 turn | 正式下限 |
| 赛后长分析 | `7B+` | 离线 | 不进实时链 |

## 最终回答

如果你的意思是“**把现在项目所有实时输入和内置模型计算都交给一个本地大模型**”，答案是：

> **没有合适参数量。不是模型不够大，而是 LLM 不适合吃 150 packet/s + 10Hz 状态循环 + 双流语音。**

如果硬要压成一个 LLM 来跑实时主循环：

> **只能考虑 1B - 2B 级，才可能接近实时预算，但策略质量、中文解释、schema 稳定和安全边界都不够，不建议。**

如果按正确工程切分：

> **现有主链继续跑，LLM 只吃 compact state / sidecar scores / voice query，那么 4B 级是正式本地 explainer 下限；2B - 3B 是降级档；7B / 8B 是桌面增强档。**

## 下一步验收建议

要科学验证，不要直接测闲聊。建议做三组 benchmark：

1. **主链替代实验**
   - 输入：compact frame，800 / 1600 / 3200 tokens 三档。
   - 频率：10Hz。
   - 判定：P95 是否 `< 100ms`，动作是否与现有 arbiter 一致。
   - 预期：3B+ 基本失败；1B-2B 速度可能接近但质量不足。

2. **语音 explainer 实验**
   - 输入：当前 `state_summary_for_llm`。
   - 输出：40 / 80 / 120 tokens。
   - 判定：P50 `< 900ms`，P95 `< 1800ms`，schema pass `>= 99%`。
   - 候选：Qwen3.5-4B、Qwen3-4B-Instruct、Gemma 4 E4B、Phi-4-Mini。

3. **双流稳定实验**
   - 同时跑 UDP replay、ASR partial、TTS streaming、LLM explainer。
   - 判定：ASR partial 抖动、TTS 首音、LLM 超时 fallback、系统内存压缩/交换。

只有第二、第三组通过，4B LLM 才能进入 Asurada 实时语音系统。第一组不应作为产品方向。

## 参考来源

- Asurada 仓库：[REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md](REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md)
- Asurada 仓库：[STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md](STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md)
- Asurada 仓库：[STAGE3_LLM_SIDECAR_ROUTING_CN.md](STAGE3_LLM_SIDECAR_ROUTING_CN.md)
- Asurada 代码：[src/asurada/runtime_pipeline.py](src/asurada/runtime_pipeline.py)
- Asurada 代码：[src/asurada/model_runtime.py](src/asurada/model_runtime.py)
- Asurada 代码：[src/asurada/voice_input.py](src/asurada/voice_input.py)
- Qwen3.5-4B model card: <https://huggingface.co/Qwen/Qwen3.5-4B>
- Qwen3-4B-Instruct-2507 model card: <https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507>
- Qwen speed benchmark: <https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html>
- Gemma 4 model card: <https://ai.google.dev/gemma/docs/core/model_card_4>
- Gemma 4 Google AI Edge: <https://developers.google.com/edge/litert-lm/models/gemma-4>
- Phi-4-Mini technical report: <https://arxiv.org/html/2503.01743v1>
- Llama 3.2 release note: <https://ai.meta.com/blog/llama-3-2-connect-2024-vision-edge-mobile-devices/>

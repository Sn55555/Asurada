# Q1 专项深挖：`client` 委派模式下，Asurada 能不能拿到「该委派对应的用户原话」

> 日期：2026-09-17
> 归属：`GPT_LIVE1_VOICE_INTEGRATION_FEASIBILITY_CN.md` §8 待验证项 Q1 的展开
> 关联：`REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md`、`STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md`、`STAGE3_LLM_SIDECAR_ROUTING_CN.md`、`STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md`

---

## 0. 一句话结论

**原话本身拿得到，但拿到的形态、时机、权威性三样都不符合 Asurada 现有链路的输入契约。**

官方设计里，`client` 委派模式下「委派通知」和「用户原话」是**两条互不携带、各自独立、时间轴还可能错开**的流：`session.delegation.created` 只有元数据，`session.input_transcript.delta` 才有文本。而 Asurada 的策略链要求的是「**在委派发生的那一刻，手上已有一份完整的、权威的整段原话**」（`VoiceTurn.metadata["transcript_text"]` 一次性注入，批式消费）。

所以 Q1 的正确提法不是"能不能拿到文本"，而是：**能不能在委派决策所需的时间窗内，把两条流重新对齐成 Asurada 要的那一份原子化原话。** 结论是：**可以，但必须由 Asurada 自己造（旁路自建 ASR），不能等 OpenAI 给。**

---

## 1. Q1 在问什么：三种常见误解先排除

| 误解 | 实情 |
| --- | --- |
| "GPT-Live 不给转写" | ❌ 错。GPT-Live 明确有 `session.input_transcript.delta`（用户字幕）/ `session.output_transcript.delta`（助手字幕），官方指引就是"把 delta 追加到字幕" |
| "委派事件里带着请求文本，拆一下就有" | ❌ 错。官方原文：`session.delegation.created` **"carries metadata and timing, without raw audio, task text, or parsed tool arguments"** |
| "有转写就等于有原话，Q1 自动通过" | ❌ 错。转写是**流式片段**、**可能迟到**、**时间戳非权威**；Asurada 要的是**整段**、**当刻可用**、**权威**。三者不可互推 |

---

## 2. Asurada 侧：原话到底被谁消费（这是判断"够不够用"的唯一标准）

### 2.1 原话的载体与注入方式

原话不是从 ASR 服务在线流式拉取的，而是**挂在 `VoiceTurn.metadata` 上一次性注入**的：

- `VoiceTurn` 本体只装 PCM：`pcm_s16le`、`audio_format`、`started_at_ms/ended_at_ms`（`voice_turn.py:11-22`）
- 转写文本经 `metadata["transcript_text"]` / `metadata["transcript_hint"]` 携带，由唤醒词层统一读取（`wake_word.py:56-58`）
- 唤醒词处理后会**覆写并保留原值**：`metadata["original_transcript_text"] = 旧值`、`metadata["transcript_text"] = 唤醒词剥离后的剩余文本`（`voice_input.py:382-383`）

**这一点是 Q1 的根**：整条链是 **utterance-level（整段批式）**契约，`VoiceTurn` 不复存在就进不了下一步。**没有"半句可以先用着"这种中间态。**

### 2.2 原话的五个消费点（缺一即断链）

| # | 消费点 | 位置 | 消耗原话做什么 | 缺原话的后果 |
| --- | --- | --- | --- | --- |
| 1 | 快速意图 | `asr_fast.py:43-46`（读 `turn.metadata["transcript_text"]`） | 关键词匹配出 `query_kind` | 无法产出 `FastIntentResult` |
| 2 | 语义归一 | `semantic_normalizer.py:29-36`、`16` | 结合 `conversation_context` + `primary_message` 归一为 `normalized_query_text` | 无 `query_kind`，直接 `raise ValueError`（`voice_nlu.py:55-56`） |
| 3 | **分流路由** | `transcript_router.py:28`、`45`、`50`、`131` | 决定 `lane ∈ {control, companion, explainer, reject}`；承载 `racing_active` 门控与 **capability 校验** | 不知道走哪条链 —— 这是**最硬的一环** |
| 4 | 查询契约构造 | `voice_nlu.py:42-89`、`125-128` | 生成 `structured_query` / `confirmation_policy` / `task_handle` | 无确认策略，控制类指令无法安全提交 |
| 5 | 解释器请求 | `llm_explainer.py:719-755`、`31`、`202` | `normalized_query_text` 进 `LlmExplainerRequest`，最终写进送给 LLM 的 `_input_text` | LLM 无题可解 |

### 2.3 回程上还有三道闸门，全部依赖"本地就是权威源"

| 闸门 | 位置 | 规则 |
| --- | --- | --- |
| 证据边界 | `llm_evidence.py:39-52` | `reason_fields` 必须是 `evidence_fields(state_summary)` 的子集；`answerable` 无 refs → `missing_evidence`；引用白名单外字段 → `unavailable_evidence`；`request_id` 不匹配 → `request_binding_mismatch` |
| 数值重建 | `llm_claims.py:19-74` | LLM **只准输出 `{{id}}` 占位符 + claims(refs/value/unit/precision)**；数值由本地 `Decimal` 重算，`claim_value_mismatch` 直接拒；正文残留裸数字 → `unbound_numeric_text` 拒 |
| 澄清白名单 | `answer_policy.py:5-9`、`12-22` | `needs_clarification` 分支**只能**返回 5 个预置中文串，禁止夹带模型自由文本 |

任一步失败 → `LlmExplainerResult(status="fallback")`，**不抛异常**（`llm_explainer.py:484-521`）。

> **架构原则一句话**：原话是路由与取证的**唯一锚点**；LLM 只许措辞、不许产数。
> 因此判据是：**原话必须在"应用侧、委派之前"就已完整可用**，不是"事后能查到就行"。

---

## 3. GPT-Live 侧：原话在哪、委派事件里有什么

### 3.1 委派通知的完整载荷（官方原文示例）

```json
{
  "type": "session.delegation.created",
  "offset_ms": 1000,
  "delegation": {
    "id": "item_appointment_1",
    "type": "delegation",
    "target": "client"
  }
}
```

官方明确：**"The notification contains metadata, not request text, tool arguments, or a complete transcript."**
client 模式下更直白：**"carries metadata and timing, without raw audio, task text, or parsed tool arguments."**

→ **四个字段，没有一个是原话。** 唯一能用于配对的线索是 `offset_ms` 和 `delegation.id`。

### 3.2 原话在另一条流上

| 事件 | 内容 |
| --- | --- |
| `session.input_transcript.delta` | 用户语音转写片段，带 `start_ms` / `end_ms` |
| `session.output_transcript.delta` | 助手语音转写片段 |

官方对 client 委派的处理指引就是让应用自己拼：
> **"Assemble the agent's input from recent role-labeled transcript fragments and verified application state, including the active task and latest correction."**

### 3.3 三个官方 caveat，每一条都正好打中 Asurada

| 官方原话 | 打中什么 |
| --- | --- |
| **"A delegation can arrive before a complete sentence appears in the transcript."** | 委派早于句子完整 → 与 Asurada「整段原子请求」**时机错配** |
| **"These timestamps are not definitive turn boundaries or word-level playback timestamps."** | 转写时间戳非权威 → 打中已有风险 **L-06（毫秒级审计链）** |
| **"If the available context does not establish the request, gather more context or ask for clarification before acting."** | 官方让你"请求澄清"，但 Asurada 的澄清是**有状态机的本地能力**（`answer_policy.py:5-9` 五个字段），GPT-Live 的语音层不认识这个状态机 |

### 3.4 回传通道（顺带确认：正文仍然是应用写的）

`session.commentary.append`（已核验结果）/ `session.thinking.append`（进度）/ `session.instructions.append`，三者都：纯字符串 `content`、**≤500 token**、**必须带 `delegation_id`**，用 `client_event_id` 匹配确认，且**"acceptance does not mean spoken or played"**。

---

## 4. 三重错配：Q1 的准确表述

| 维度 | Asurada 要的 | GPT-Live 给的 | 是否可解 |
| --- | --- | --- | --- |
| **时机** | 委派发生的**那一刻**原话已完整 | 委派**可能早于**句子完整 | ✅ 可解（自己造原话，见 §6 S1） |
| **形态** | **整段**（一个 `VoiceTurn` = 一次请求） | **流式片段**，一次委派可能跨多片，一片也可能触发多次委派 | ⚠️ 需自建"凑句 + 配对"逻辑 |
| **权威** | 毫秒级、可入 `session_log.jsonl` 审计 | 官方声明时间戳**非权威轮次边界** | ❌ 不可解（只能靠应用侧自记，代价见 L-06） |

**最容易低估的是第二条的"碎片化委派"**：如果用户在句中被连续委派，可能出现「委派 A 对应句子前半、委派 B 对应后半」。这与 `VoiceTurnManager`「一次 PTT/一段 VAD = 一个原子 turn」（`voice_turn.py:52-233`）的模型**根本冲突**，会直接冲击 **L-07（PTT 语义冲突）**。

---

## 5. 严重性校准：为什么这不是"小问题"

原报告一处判断需要**修正**。之前写的是"拿不到就必须退到 `responses` 托管模式，等于把策略推理交给 OpenAI —— 可控性归零"。**这个说法过重了**，精确的说法是：

`responses` 委派模式下，应用**仍然保留**工具执行权（官方："Your app still executes custom functions, enforces permissions, and returns results"）和 `session.commentary.append` 这个只允许应用写入的"已核验结果"通道 —— **用户最终听到的策略正文依然由 Asurada 写**。

真正移交出去的是**三项指挥权**：

| 移交项 | 从 → 到 | 与现有闸门的冲突 |
| --- | --- | --- |
| **路由权** | `TranscriptRouter` → GPT-Live 内部的委派决策 | `racing_active` 门控（`transcript_router.py:50`）与 capability 校验（`transcript_router.py:131`）被架空 |
| **取证权** | 本地 `state_summary` 白名单 → Live 自己"supplies conversation context" | 后端可能基于 Live 的压缩上下文作答，其引用字段不在本地 `evidence_fields` 白名单内 → `unavailable_evidence` 结构性拒答 |
| **时序权** | 应用决定何时开口 → GPT-Live 决定 | 已知 **L-03**：后端与策略检查运行时语音层可能继续说话，纠错无法撤回已听音频 |

**准确的说法是：应用还剩否决权，但没有了指挥权。** 而否决（不 append commentary / 丢弃结果）的代价是——**用户已经听到了前一轮 filler，且这一次请求白花钱**。取证权冲突的后果不是"失控"，而是**高概率确定性 fallback，等于白付每分钟 $0.05**。

---

## 6. 三条解法（按推荐度排序）

### S1 · 旁路自建 ASR ——「原话权威源本地化」【推荐】

**核心洞察**：GPT-Live 的音频入口是 `session.input_audio.append`（`audio` 字段为 base64 原始音频），而 **Asurada 本来就持有同一份 16kHz PCM**（`audio_io.py`）。所以原话完全不必依赖 OpenAI 的转写。

做法：同一路 PCM **双写** —— 一路进 GPT-Live，另一路喂给**现有的**豆包流式 ASR：

- 复用现成实现，**零新增 provider**：`DoubaoBigmodelStreamingWsSidecarAsrBackend`（`voice_sidecar_asr.py:344`）
- 现成的实时会话抽象完全对得上：`open_realtime_session`（`voice_sidecar_asr.py:675`）、`append_audio_chunk` / `finish` / `close`（协议 `voice_sidecar_asr.py:88-105`）
- 现成的增量回调可直接产出"带序号的 partial"：`partial_callback` + `last_sequence`（`voice_sidecar_asr.py:332-333`）
- 该实现已在解析 `conversation.item.input_audio_transcription.completed`（`voice_sidecar_asr.py:545`）—— 说明这套协议族本来就带权威转写完成事件

**收益**：原话与委派事件**完全解耦**。OpenAI 那边给不给文本都无所谓，Q1 从"依赖外部"变成"内部可控"。转写形态也能自己决定（流式 partial → 自建整段）。

**代价**：需要自己实现"配对"（见 §7）。且豆包 ASR 与 GPT-Live 的会话生命周期要一起管理。

---

### S2 · 直接用 `session.input_transcript.delta`

**收益**：最省事，官方路线，零额外成本。
**代价**：转写是旁路流，需自行处理"半句"、重叠（"听"与"说"可能重叠）、迟到；时间戳非权威。
**适用**：**只适合 `companion` lane**（闲聊无需证据绑定）。**不适合 `explainer` lane** —— 那里每一次回答都要过 `validate_evidence` + `render_claims`。

---

### S3 · 双写落盘 + 事后审计对账

delegation 只记 `delegation_id + offset_ms + 应用侧时间戳`；PCM 走现有 capture 管线落盘；事后用录音重跑 ASR 做审计对账。
**作用**：保住 L-06 的毫秒级审计链 —— 审计以**应用侧自记时间戳**为准，转写仅作展示。
**定位**：**必做的配套**，不是替代方案。建议 S1 时就一并做掉。

---

## 7. 配对机制设计（S1 的关键细节）

**不能靠 ID 配对**（委派事件没有 item↔transcript 的关联 ID），只能靠时间窗：

1. 统一时间轴：把 `delegation.created.offset_ms` 与本地 ASR 的片段时间戳对齐到同一基准
   ⚠️ **待验证**：`offset_ms` 与 `input_transcript` 的 `start_ms/end_ms` **是否同一时间基准**，官方未明确说明，必须实测标定。
2. 定义风险量 **Δ**：
   ```
   Δ = 委派时刻(offset_ms) − 覆盖该委派的转写片段 end_ms
   ```
   - `Δ > 0` → 转写**滞后**于委派，原话未齐，**必须等**
   - `Δ < 0` → 转写先到（理想态）
3. 容差与边界：建议 ±500ms 配对容差；显式处理两种退化情形 ——「一次委派跨多片段」与「一片段触发多次委派」。
4. **认领（claim）防重复**：官方硬性要求 —— *"claim the delegation in your application so duplicate delivery cannot start the same operation twice."* 可复用现有 `delivery_context` / `task_runtime` 的认领思路。

---

## 8. PoC 验证设计（把 Q1 变成可测指标）

### 8.1 主指标

| 指标 | 定义 | 验收阈值 | 依据 |
| --- | --- | --- | --- |
| **Δ_P95** | 委派相对其转写片段的滞后分布 | **≤ 300ms** | 现有总预算 <1s − 路由/取证 <50ms − TTS 首音 200~500ms ⇒ 剩下约 300~700ms 的等待窗口，取保守值 |
| **Δ_max** | 最坏滞后 | ≤ 800ms | 超出即用户可感知停顿 |
| **碎片化率** | 一次委派跨多片段 / 一次请求触发多次委派的比例 | ≤ 5% | 超出则 `VoiceTurn` 原子模型需重做 |
| **时间轴一致性** | `offset_ms` 与 `start_ms/end_ms` 是否同基准 | 必须为同一基准 | 未标定则 §7 全部失效 |

> ⚠️ 300ms / 800ms 是**按现有预算反推的建议阈值**，需与团队实际延迟预算复核后确认。

### 8.2 判读规则

- `Δ_P95 ≤ 300ms` **且** 碎片化率 ≤ 5% → **Q1 通过**，`client` 委派可用
- `Δ_P95 > 300ms` → 必须引入"凑句缓冲"，而缓冲直接吃掉 **L-04** 的延迟预算 → 触发 no-go 复核
- 时间轴不同基准 → 需要自己做时钟域映射，工作量上升一档
- 任一项不达标 → **退回 `responses` 托管模式，并接受 §5 的三项指挥权移交**

### 8.3 样本要求

- 不少于 30 次真实提问，覆盖三类长度：**短问句（<2s）/ 中文长句（5~10s）/ 句中被追问**
- 必须包含**选手在句中改口**的场景（官方专门提示的 correction 场景）
- 网络条件：在实际代理环境下测（与 **Q2** 合并跑，同一批会话出两组数据）

---

## 9. 对原报告的修正清单

| 位置 | 原文 | 修正为 |
| --- | --- | --- |
| §8 Q1 结论列 | "拿不到原话就必须退到 `responses` 托管模式，等于把策略推理交给 OpenAI —— 可控性归零" | "拿不到**当刻可用的整段原话**；解法是应用侧自建权威原话源（S1）。若退回托管模式，移交的是**路由权 / 取证权 / 时序权**三项指挥权，应用仅剩否决权" |
| §8 Q1 验证方式列 | "实机跑通，观察 `input_transcript.delta` 与 `delegation.created` 的时序与配对关系" | 细化为 §8 的 Δ_P95 / Δ_max / 碎片化率 / 时间轴一致性四项可测指标 |
| §8 新增 | — | 建议补 **Q10：单个 session 能否在同一会话内混用 `client` 与 `responses` 两种委派模式**（因为 `explainer` lane 需要 client、`companion` lane 用 responses 更省事） |

---

## 10. 附录：证据索引

### 10.1 Asurada 侧（文件:行号）

| 结论 | 证据 |
| --- | --- |
| 原话挂在 `VoiceTurn.metadata`，批式消费 | `voice_turn.py:11-22`；`wake_word.py:56-58`；`voice_input.py:382-383` |
| 原话消费点 1：快速意图 | `asr_fast.py:43-46` |
| 原话消费点 2：语义归一 | `semantic_normalizer.py:16`、`29-36` |
| 原话消费点 3：分流路由（含 racing 门控 / capability） | `transcript_router.py:28`、`45`、`50`、`131` |
| 原话消费点 4：查询契约 | `voice_nlu.py:42-89`、`125-128` |
| 原话消费点 5：解释器请求 | `llm_explainer.py:31`、`202`、`719-755` |
| 闸门 A：证据边界 | `llm_evidence.py:39-52` |
| 闸门 B：数值重建 | `llm_claims.py:19-74` |
| 闸门 C：澄清白名单 | `answer_policy.py:5-9`、`12-22` |
| 失败即 fallback、不抛异常 | `llm_explainer.py:484-521` |
| S1 可复用的实时 ASR 实现 | `voice_sidecar_asr.py:88-105`、`332-333`、`344`、`545`、`675` |
| 原子 turn 模型 | `voice_turn.py:52-233` |

### 10.2 官方侧

| 事实 | 来源 |
| --- | --- |
| `session.delegation.created` 完整示例载荷（`offset_ms` / `delegation.id` / `.type` / `.target`） | `developers.openai.com/api/docs/guides/live-migration` |
| "contains metadata, not request text, tool arguments, or a complete transcript" | `live-migration` |
| "carries metadata and timing, without raw audio, task text, or parsed tool arguments" | `live-migration` |
| "Assemble the agent's input from recent role-labeled transcript fragments and verified application state" | `live-migration` |
| "A delegation can arrive before a complete sentence appears in the transcript." | `live-migration` |
| `session.input_transcript.delta` / `session.output_transcript.delta`，含 `start_ms`/`end_ms` | `live-migration` |
| "These timestamps are not definitive turn boundaries or word-level playback timestamps." | `live-migration` |
| `session.input_audio.append`（`audio` = base64） | `live-migration` |
| `commentary/thinking/instructions.append`：纯字符串、≤500 token、必须带 `delegation_id`、"acceptance does not mean spoken or played" | `live-migration` |
| 认领防重复："claim the delegation in your application so duplicate delivery cannot start the same operation twice." | `live-migration` |
| 应用仍执行工具与权限；Live 向委派后端提供会话上下文 | `live-migration`、`developers.openai.com/api/docs/guides/live` |

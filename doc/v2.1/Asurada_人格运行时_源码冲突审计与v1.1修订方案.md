# Asurada 人格运行时：源码冲突审计与 v1.1 修订方案

> 日期：2026-10-28｜状态：静态源码审计（非运行时验证）｜设计方向：C 型成长人格，初始理性克制。
>
> 本文是 v1.0 的增量修订，不修改策略算法。审计范围仅为本文列出的公开 `main` 分支源码及仓库架构文档；**未运行测试、未完成整个仓库的线程/入口审计**。因此“已证实”仅表示源码路径已确认，不等于实测故障。

## 0. 执行摘要

1. **已证实：人格化不能只挂 `open_fallback`**。正常结构化查询和主动策略播报有各自的文本生成路径。
2. **已证实：`ConsoleVoiceOutput` 是目前可复用的汇合点，但它不是完整的可抢占语音调度器**：它持有 active/pending，优先级替换只作用于 pending；`_process_submission()` 中没有针对新高优先级消息中断 active 的逻辑。此前将其概括为“已有高优先级抢占”过于乐观，应修正。
3. **已证实：重复抑制只按 `action_code` 比较 active/pending**，新加的可选人格台词不能随意复用业务 action code，否则可能被误抑制，反之也可能过量发声。
4. **已证实：`VoiceInputCoordinator` 的对话记忆仅在完成语音回合时更新**，不能承担全局比赛情绪更新。
5. **已证实：`ConversationContext` 是最多 6 条的内存短期上下文**，不适合作为跨比赛关系存储。
6. **尚待验证：事件来源、音频后端取消语义、并发线程边界、真实 fallback 占比、实际 TTS 延迟**。在验证前不能断言它们已经存在问题。

**v1.1 决策：** 将人格拆为 `EventAdapter → PersonalityRuntime（状态） → DialoguePolicy（表达机会） → SpeechPersonalizer（文本视图）`；先接入规则版，不将 LLM 放进热路径；在输出层实现可选语音丢弃、过期校验和真实中断能力之前，不启用自由生成的主动闲聊。

## 1. 源码证据表：确定事实与集成含义

| 源码 | 已确认行为 | 与 v1.0 的冲突 / 机会 | 结论等级 |
|---|---|---|---|
| `semantic_normalizer.py:37-85` | 快速意图优先，未知文本才成为 `open_fallback` | 仅挂 fallback 会遗漏大多数已识别类型（实际占比待测） | 已证实路径 |
| `voice_input.py:42-110` | 语音完成后才走 normalize、bundle、emit；`stop/cancel/repeat` 单独分支 | 情绪事件不能依赖该入口；控制命令不应被人格化 | 已证实 |
| `output.py:63-79,310-367` | 主动策略和查询分别构造 `_SpeechEnvelope/SpeechJob` | 在两个 envelope 构造处共享同一纯函数人格策略；不要改策略数据 | 已证实 |
| `output.py:248-275` | 查询先调用 `render_structured_query_response()` 再入输出队列 | `ResponseComposer` 不是全路径唯一入口 | 已证实 |
| `output.py:368-471` | 只有一个 active 和一个 pending；新高优先级消息只能替换 pending | **没有看到 active 被优先级抢占**；紧急播报被长句占用风险需测 | 已证实代码行为，风险待测 |
| `output.py:409-419,676-681` | active/pending 与新消息 `action_code` 相同则 suppress | 人格播报要有独立去重键和 TTL，不可滥用 `action_code` | 已证实 |
| `output.py:472-489` | 通过 `backend.is_active` 轮询完成，`backend.start(job)` 开始播放 | LLM 必须在 start 前完成或放弃；启动后的替换需要后端能力 | 已证实 |
| `output.py:349-359` | 查询响应 `priority=95` 固定值 | 优先级需要统一语义和边界；不能假设查询永远比紧急事件低 | 已证实 |
| `interaction.py:64-80` | `SpeechJob` 有 request、snapshot、source、priority、metadata | 可扩展 personality metadata，但要保留原始文本及可追踪性 | 已证实 |
| `conversation_context.py:22-43,84-91` | 6 条短历史，内存维护，无持久化接口 | 独立 `RelationshipStore` | 已证实 |
| `ARCHITECTURE.md:68-102,197-208` | 有 capture replay、live UDP、短历史 StateStore | 应利用 replay 验证事件；不应把 StateStore 当长期记忆 | 已证实文档声明 |

### 1.1 需要修正之前分析中的表述

- **“高优先级消息抢占当前播放”不是当前 `_process_submission()` 的已实现能力。** 代码优先级比较针对 `_pending_envelope`，而非 `_active_envelope`。`stop/cancel` 控制命令另有路径，需要单独审计，不等于任意紧急策略播报可抢占。
- **“SpeechJob 生成前接入”是合理的同步扩展点，不等于异步 LLM 可直接替换尚未播报的 job。** 目前只看到了 `_pending_envelope` 私有状态，尚无公共、线程安全的 `replace_if_pending(output_event_id, revision)` API。
- **“fallback 发生得少”仍是待量化假设。** 需要统计各 `query_kind`、`source_kind` 和 `output_lifecycle.event_type` 的真实分布。

## 2. 12 项风险：源码归因与处理优先级

| # | 风险 | 当前证据 | 分类 | 修订动作 | 优先级 |
|---|---|---|---|---|---|
| R01 | fallback 覆盖不足 | normalizer 路由及双输出路径 | 已有接入冲突 | 所有 speech opportunity 统一人格决策 | P0 |
| R02 | 高优先级消息不能中断 active | output `_process_submission` | **已确认能力缺口** | 先设计可中断能力和后端接口；关键警告优先 | P0 |
| R03 | 异步 LLM 过期文本 | 无公共 job revision/TTL API | 新增风险 | `deadline + session + request + snapshot` 四重校验 | P0 |
| R04 | 重复事件驱动情绪暴涨 | 实时多帧数据；事件接口待查 | 新增风险 | 边沿检测、幂等 event_id、冷却 | P0 |
| R05 | 人格影响策略结果 | 策略和输出已分层 | 新增风险 | 只读输入、保留原始事实、禁止回写 `StrategyDecision` | P0 |
| R06 | 主动/查询人格不一致 | 双 envelope 构造路径 | 已有接入冲突 | 共用 `SpeechPersonalizer` | P0 |
| R07 | 长期记忆错误/丢失 | ConversationContext 只存短历史 | 已有能力缺口 + 新增风险 | 独立版本化存储、证据校验 | P0 |
| R08 | 人格缺乏主动发言机会 | 现有两类输出入口 | 新增需求缺口 | `SpeechOpportunityDetector` + 节流 | P1 |
| R09 | 可选吐槽占用语音资源 | active/pending 容量 1+1 | 新增风险 | optional 仅空闲发、TTL 到期丢弃 | P0 |
| R10 | 成长阶段来回跳变 | 尚无成长机制 | 新增风险 | 阶段滞回、最低经历数、单向正常晋升 | P1 |
| R11 | LLM 语义漂移/事实编造 | 现有模板是确定性文本 | 新增风险 | 关键语句锁定、结构化前后缀、验证失败回退 | P0 |
| R12 | 性能、测试、配置迁移 | capture replay 存在；推理未集成 | 待验证 + 新增风险 | 事件回放、延迟预算、schema_version | P0 |

## 3. 推荐 v1.1 架构

```text
F1 25 / Replay
    │
    ▼
SessionState ───────────────────────────────► StrategyEngine（不修改）
    │                                              │
    ▼                                              ▼
RaceEventAdapter                            StrategyDecision
    │                                              │
    ▼                                              ▼
PersonalityEvent（幂等）                     原始策略文本
    │                                              │
    ▼                                              │
PersonalityRuntime                                │
├── EmotionEngine                                 │
├── RelationshipStore（持久化）                    │
├── GrowthStageManager                            │
└── PersonalitySnapshot（不可变）                  │
    │                                              │
    └───────────────┬──────────────────────────────┘
                    ▼
             DialoguePolicy
              ├── NO_SPEECH
              ├── RULE_STYLE
              └── OPTIONAL_HUMOR（低优先级）
                    │
                    ▼
          SpeechPersonalizer（同步、纯函数）
              ├── 原文保留
              ├── 模板增强
              └── 异步 LLM 候选（未来）
                    │
                    ▼
            SpeechJob / OutputLifecycle
                    │
                    ▼
                 TTS Backend
```

### 3.1 不变量

1. `StrategyDecision`、`StrategyMessage`、`final_voice_action` 的业务语义不可被人格层修改。
2. 安全/关键策略内容不得等待 LLM；超时必须回退确定性原文。
3. 情绪更新与语音机会分离：每个有效事件至多更新一次，**不要求每个事件都发声**。
4. 人格输出只作用于呈现层；保留 `original_text`、`rendered_text`、`personality_version` 和 `reason_code`。
5. 可选幽默不能进入长队列；高风险、正在听取用户语音、语音控制命令时禁止。
6. 跨会话持久化只写已验证证据；比赛阶段临时情绪不应被误当成长期信任。

## 4. 最小接口契约（建议代码，非仓库现状）

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass(frozen=True)
class PersonalityEvent:
    event_id: str
    session_uid: str
    frame_identifier: int | None
    kind: str
    observed_at_ms: int
    evidence: dict = field(default_factory=dict)

@dataclass(frozen=True)
class PersonalitySnapshot:
    session_uid: str
    version: int
    growth_stage: Literal['H0','H1','H2','H3']
    emotion: dict
    relationship: dict

@dataclass(frozen=True)
class SpeechOpportunity:
    source_kind: Literal['strategy_broadcast','query_response','optional_personality']
    original_text: str
    action_code: str
    priority: int
    snapshot_binding_id: str
    expires_at_ms: int | None
    can_drop: bool

@dataclass(frozen=True)
class PersonalitySpeechResult:
    original_text: str
    rendered_text: str
    style: str
    generation_source: Literal['original','template','llm']
    personality_version: int
    reason_code: str
```

**注意：** `event_id` 必须基于稳定的事件源键生成，而不是每帧生成 UUID；不同事件的去重窗口应独立配置。跨会话重置情绪时要考虑 session_uid 切换、重播、暂停、重连。

## 5. 具体改造文件与接口位置

| 阶段 | 文件 | 最小改动 | 避免的破坏 |
|---|---|---|---|
| 0 | `output.py` | 先加只读统计与事件追踪；为 `start/enqueue/suppress` 记录来源、时延 | 不改变调度行为 |
| 0 | `live_runtime.py`、`runtime_pipeline.py`、`capture_runtime.py` | 核实主循环、策略调用频率和 replay 注入点 | 不盲目新增线程 |
| 1 | `personality/events.py`（新增） | 标准事件 + 去重器 + session 边界 | 避免重复情绪变化 |
| 1 | `personality/runtime.py`（新增） | 同步事件更新、不可变快照 | 不依赖语音输入 |
| 1 | `personality/policy.py`（新增） | 是否发言、风险抑制、成长/幽默门槛 | 不让 LLM 控制时机 |
| 1 | `personality/speech.py`（新增） | 规则文本增强纯函数 | 不修改策略对象 |
| 2 | `output.py` 两处 `_build_*_envelope` | 共享人格渲染入口，先只支持规则 | 覆盖主动与查询 |
| 2 | `personality/store.py`（新增） | 原子写入、版本迁移、可重置 | 不污染 ConversationContext |
| 3 | `output.py` 调度器 | optional TTL、空闲才播、独立去重键、关键警告抢占接口 | 解决主动幽默与安全竞争 |
| 4 | `personality/llm_sidecar.py`（新增） | 独立执行器、deadline、校验、丢弃过期结果 | 不阻塞策略热路径 |

**重要：** 阶段 3 的“真正抢占”需先审计 `tts_backends.py` 的 `stop/cancel` 支持及线程安全，再决定是增强现有 `ConsoleVoiceOutput`，还是抽出 `SpeechScheduler`；不能直接假设现有 `cancelable` 字段已经实现任意任务的主动抢占。

## 6. 最值得先测的源码行为

### 6.1 输出调度基线

- active 正在播放时，提交更高优先级策略：记录是否立即播报、排队或抑制。
- active + pending 已满时，提交更高优先级：验证 pending 替换与 cancel 日志。
- 两条不同 `request_id`、同 `action_code` 的查询：验证是否被 suppress。
- 后端播放结束但无新输入：验证谁负责触发 `_poll_completed_active()` 与 pending 自动开始；如果需要新一次 `emit()` 才轮询，检查长时间无输入时的队列推进。
- `stop/cancel/repeat` 与策略高优先级播报分别测试，不能混为同一语义。

### 6.2 人格事件基线

- 同一碰撞持续 100 帧：只触发一次事件。
- 换胎成功：只恢复与轮胎有关的 concern。
- 赛道暂停、重连、回放倒退：不产生虚假的超车/失误。
- 车手全程不说话：Emotion/Relationship 仍能由真实比赛事件更新。
- 关键时刻主动幽默：必须 suppress/drop，且不会稍后补播。

### 6.3 LLM 基线（后续）

- LLM 500ms、2s、超时、异常、生成矛盾建议分别验证。
- LLM 生成期间 session/snapshot 切换：结果必须失效。
- 取消后不得继续 TTS；如果已经 start，则遵循音频后端可中断能力。
- 不允许修改原始策略结论、轮胎/圈数/时间等事实字段。

## 7. 量化指标与验收门槛（建议目标，非实测）

| 指标 | 初始目标 |
|---|---|
| `source_kind` 覆盖 | strategy_broadcast、query_response 均经过 policy 评估，覆盖率 100% |
| fallback 占比 | 实测统计，不预设低或高 |
| 事件幂等 | 相同 event_id 重放，状态增量为 0 |
| 安全/关键策略等待 LLM | 0 ms（完全不等待） |
| optional 语音过期播放 | 0 |
| 高风险场景幽默违规 | 0 |
| 跨会话记忆可恢复 | 通过重启/迁移/损坏文件测试 |
| 关闭人格开关 | 语音业务行为与原基线一致 |
| 性能 | 实测 p50/p95/p99；上线前根据机器预算设阈值 |

## 8. 待进一步核查清单（不得当作已解决）

1. `tts_backends.py`：各 backend 是否支持 cancel、start 的线程语义、is_active 轮询副作用。
2. `live_runtime.py`、`runtime_pipeline.py`、`capture_runtime.py`：事件注入点、主循环 tick、是否存在阻塞 IO。
3. `strategy_arbiter_v2` 相关代码：`final_voice_action` 的去重、节流、优先级是否已有上游保障。
4. `tests/`：是否覆盖 active/pending、stop/cancel/repeat、query 同码不同请求、session 切换。
5. `voice_turn` 与 AudioIO：车手讲话时 TTS 的抑制/回声问题。
6. 真实回放数据：不同 `query_kind` 和 `source_kind` 的发生率及人格候选事件分布。

## 9. 推荐实施顺序与 v1.1 决策

**第一步：仅观测（无行为变化）。** 统计语音路由、调度事件、重复码、语音时长，使用 capture replay 生成基线。

**第二步：纯规则人格 MVP。** 事件驱动 Emotion、成长阶段与模板风格；统一覆盖主动策略和结构化查询；可通过 feature flag 完全关闭。

**第三步：调度器补强。** 明确关键播报抢占、optional 丢弃、TTL、去重键和 backend cancel 能力。此步是主动吐槽上线前的硬门槛。

**第四步：长期关系存储。** 证据校验、版本迁移、重启恢复、隐私和重置接口。

**第五步：旁路 LLM。** 只对非关键文本生成可选风格，不接管策略，不阻塞关键语音，失败使用原文。

### 与 v1.0 的关系

- 保留 v1.0 的七维人格、H0～H3 成长、幽默类型、关系记忆、LLM 语言层原则。
- **覆盖 v1.0 中以 `open_fallback` 为主要接入点的实施建议**；不再将它视为人格主路径。
- **新增优先事项：输出调度实际能力审计和 active 抢占缺口**。这是本次源码核对的重要新发现。
- 本文作为 v1.1 架构修订文档；后续进一步读取 runtime/tts/tests 后再发布 v1.2，不应把未验证内容写成既有事实。

## 10. 源码索引

- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/output.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/interaction.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/voice_input.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/semantic_normalizer.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/response_composer.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/src/asurada/conversation_context.py`
- `https://github.com/Sn55555/Asurada/blob/main/asurada-core/ARCHITECTURE.md`

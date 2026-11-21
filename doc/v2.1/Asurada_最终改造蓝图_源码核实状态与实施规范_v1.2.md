# Asurada 人格运行时：源码核实状态与最终改造蓝图（v1.2，待全仓验收）

> 2026-10-28。此文档是可执行的改造蓝图，不是“已完成全仓审计”证明。当前可直接访问并逐行核实的文件有限；无法下载完整 Git 仓库或运行其现有测试。所有未经运行验证的结论均标注为待验证。

## 0. 结论与目标

目标：把成长型阿斯拉达（理性、关怀、固执、自信、好胜、信任、幽默）做成持续接收比赛事件的独立运行时；其自然语言表达覆盖正常策略播报、结构化语音查询及受控主动对话，绝不依赖 `open_fallback` 的触发频率。策略结论由确定性策略引擎负责；LLM 只做非关键表达增强。实时 UDP 路径不等待 TTS/LLM。

**架构硬约束**：不改写 StrategyDecision 事实；高优先级警告可抢占低优先级可取消语音；可选幽默可丢弃不可积压；输出任务必须可取消、可追踪、可过期；关系记忆只接受经过证据校验的事件；任何后端异常均降级到确定性语音或静默，不反向阻塞遥测。

## 1. 本轮可直接核实的源码证据

| 文件与位置 | 观察 | 判定 | 改造影响 |
|---|---|---|---|
| `src/asurada/output.py:55-62` | active/pending/last_completed 三个槽 | 已确认 | 现为有限容量调度，不应无脑改成无界队列 |
| `output.py:63-79, 155-185, 248-279` | 主动策略与语音查询从不同入口构建，均调用 `_process_submission` | 已确认 | 统一人格表达应在构建语音任务后、提交调度前 |
| `output.py:310-366` | Strategy speech 优先级来自 arbiter，query 固定 95；两者不同 source_kind | 已确认 | 优先级与消息类型必须有统一映射；query 95 不应天然压过紧急警告 |
| `output.py:368-471` | 每次提交先轮询 active，再处理 pending；无 active 抢占分支 | 已确认 | 独立 scheduler tick 和抢占策略 |
| `output.py:409-419, 676-681` | 仅凭 action_code 去重，未纳入 source_kind、request_id、状态变化 | 已确认 | 改为按语义/来源/时间窗去重 |
| `output.py:472-489` | `is_active=False` 就记完成；先设置 active 再调用 backend.start | 已确认 | 后端错误状态与启动事务保护 |
| `output.py:490-590` | 生命周期事件主要在提交调用中写入 debug | 已确认 | 改为异步事件订阅/事件日志，不能只靠当次返回值 |
| `voice_input.py:80-120` | 控制与普通查询均在 emit 返回后立即 `_record_response`；普通查询状态返回 `spoken` | 已确认 | 区分 submitted/queued/started/completed；spoken 不等于播放完成 |
| `tts_backends.py:14-23` | 后端只有 start/is_active/stop | 已确认 | 引入 poll_status 和明确退出码/失败原因 |
| `tts_backends.py:26-36` | Null backend 立即 inactive | 已确认 | 需要区分静默降级与真实音频播放完成 |
| `tts_backends.py:112-129, 176-209` | Piper 以进程组启动，runner 先合成再播放，异常以退出码退出 | 已确认 | 取消要覆盖合成和播放两个阶段，记录真实退出码 |
| `runtime_pipeline.py:37-77` | ingest_packet 同步执行 decode、assemble、strategy、voice_output.emit、logger.append | 已确认 | 必须让语音提交 O(1) 或有界；不能内联模型推理 |

源码依据：
- https://raw.githubusercontent.com/Sn55555/Asurada/main/asurada-core/src/asurada/output.py
- https://raw.githubusercontent.com/Sn55555/Asurada/main/asurada-core/src/asurada/voice_input.py
- https://raw.githubusercontent.com/Sn55555/Asurada/main/asurada-core/src/asurada/tts_backends.py
- https://raw.githubusercontent.com/Sn55555/Asurada/main/asurada-core/src/asurada/runtime_pipeline.py

## 2. 尚未完成的全仓核实（不可冒充已验证）

待逐文件盘点：`main.py` CLI 入口与进程生命周期、`live_runtime.py` 并发模型、`interaction.py` 数据契约、`semantic_normalizer.py`、`response_composer.py`、`conversation_context.py`、`voice_turn.py`、`voice_nlu.py`、`asr_fast.py`、音频/VAD、`models.py`、`state.py`、`packet_snapshot.py`、`pdu_decoder.py`、`strategy.py`、arbiter/fallback_policy/tactical_state_machine、sidecar 模型、logger/dashboard、配置/部署/CI、全部 tests。上述部分在此前讨论中有局部静态分析，但尚未完成同一 commit 的全仓可重复审计。

全仓审计需固定 commit SHA，生成 `git ls-files` 清单，逐项标记 READ/TESTED/BLOCKED；使用 `rg` 搜索 `ConsoleVoiceOutput|emit_voice_query_bundle|process_completed_turn|SpeechBackend|ConversationContext|StrategyRuntimePipeline` 的所有调用者；执行测试并保留失败日志。**在此之前，不声称所有代码核实完毕。**

## 3. 目标组件与数据流

```text
F1 UDP -> Decoder -> SnapshotAssembler -> UnifiedStateStore -> StrategyEngine -> StrategyDecision
                          |                    |                                  |
                          |                    +-> RaceEventAdapter -> EventReducer -> PersonalityRuntime
                          |                                                | EmotionEngine
                          |                                                | RelationshipStore
                          |                                                | GrowthStageManager
Voice -> VAD/ASR -> Intent/StructuredQuery -> deterministic ResponseComposer  |
                  \                         /                                 |
                   +-- SpeechCandidate <---+----------------------------------+
                               |
                         DialoguePolicy [whether/when]
                               |
                         SpeechPersonalizer [how; optional async LLM]
                               |
                         SpeechScheduler [priority/TTL/cancel/preempt]
                               |
                         SpeechBackend [status + stop]
                               |
                         SpeechLifecycleEvent -> ConversationContext / Relationship evidence
```

**职责边界**：EventAdapter 只提取事实；EmotionEngine 只更新短期情绪；RelationshipStore 只持久化可验证的共同经历；DialoguePolicy 决定说不说、何时说；SpeechPersonalizer 不改写事实；Scheduler 是公共基础设施，不能放进人格包。

## 4. 接口草案

```python
@dataclass(frozen=True)
class PersonalityEvent:
    event_id: str
    session_id: str
    source: str  # telemetry / strategy / interaction / speech
    kind: str
    monotonic_ns: int
    snapshot_id: str | None
    payload: dict

@dataclass(frozen=True)
class SpeechCandidate:
    candidate_id: str
    source_kind: str
    action_code: str
    base_text: str
    priority_class: str  # critical / tactical / query / routine / optional
    deadline_monotonic_ns: int
    snapshot_id: str | None
    cancelable: bool
    facts: dict
    optional_personality: bool

@dataclass(frozen=True)
class SpeechLifecycleEvent:
    output_event_id: str
    status: str  # created/queued/started/completed/cancelled/failed/expired/suppressed
    timestamp_ns: int
    reason: str | None
    backend_exit_code: int | None
```

统一使用 monotonic clock 计算 TTL、超时与冷却；UTC wall-clock 仅用于持久日志。`event_id` 必须幂等；`snapshot_id` 需可追溯到原始状态。`schema_version` 用于磁盘迁移。

## 5. SpeechScheduler 状态机

- 单消费者事件循环，外部入口通过有界队列提交；所有 active/pending 读写由同一所有者处理，避免竞态。
- 初始保留 **1 active + 1 tactical pending + 1 optional pending（可直接丢弃）**，不要无界积压。
- 状态：CREATED → QUEUED → STARTING → STARTED → COMPLETED；分支 FAILED/CANCELLED/EXPIRED/SUPPRESSED。
- `backend.start` 成功返回后再提交 active；异常转 FAILED 并清理资源；`backend.poll_status` 区分成功退出与非零退出。
- 调度器自行 `tick`，不依赖新的策略提交来推进 pending。
- 抢占仅当 incoming 优先级更高、active 可取消且后端确认停止/超时；不可取消紧急消息不得被幽默覆盖。
- query 不应固定绝对优先级 95；改为可配置类别映射，明确紧急事件优先。
- `repeat_last` 默认重复最近**已成功完成**的可重复播报；不能默认重复 pending。
- 去重键为 `(source_kind, action_code, semantic_subject, session_id)` 加时间窗/状态版本；用户主动查询按 request_id 保留独立响应。
- 关闭进程时取消待执行任务、终止子进程组、落盘最终生命周期；不要遗留孤儿播放器。

## 6. 人格运行时与幽默策略

- 情绪更新与语言输出分离：比赛中每个可信事件更新状态，**并不意味着每个事件调用 LLM**。
- 角色常量：理性、自信、好胜、固执、关怀；可变情绪：担忧、兴奋、不满；长期关系：熟悉度、信任证据、共同事件。
- 成长 H0-H3，升级需要足够共同经历、稳定窗口和可信证据；阶段通常不回退，短期态度可变化。
- HumorPolicy 确定性判定：紧急事件、密集攻防、过期上下文、正在处理用户请求时禁止可选幽默；按赛段、时间、最近台词做冷却去重。
- LLM 只生成风格前后缀或非关键独立闲聊；策略事实原文不可删除；关键播报使用固定模板。
- LLM 超时、异常、资源超限、模型输出不合规时立刻使用原文，不阻塞主循环。
- 主动闲聊必须来自 SpeechOpportunityDetector，非策略性消息默认最低优先级且可丢弃。

## 7. 长期记忆与证据

- 不从 `emit` 返回或 `ConversationContext.observe_response` 推断“车手听到了”。
- 事件分层：recommendation_created / speech_started / speech_completed / driver_acknowledged / action_observed / outcome_verified。
- 信任更新必须有可归因证据；无法区分车手故意忽略与技术失败时，不扣信任。
- SQLite WAL（单进程）或轻量持久层；原始事件 append-only，物化关系状态可重建；事务提交后才视为写入成功。
- 最小化存储：仅保留必要事件和可解释摘要；提供查看、导出、清除与重建入口；支持 schema 迁移。

## 8. 文件改造映射（建议，不代表文件已存在）

| 位置 | 操作 | 兼容策略 |
|---|---|---|
| `output.py` | 让 ConsoleVoiceOutput 变为 facade，内部委托 SpeechScheduler | 保留 emit/emit_voice_query_bundle/emit_control_query_bundle 返回格式过渡 |
| `tts_backends.py` | 新增 `poll_status(handle)`、停止确认和失败状态 | 先适配旧 `is_active`，逐步迁移 |
| `runtime_pipeline.py` | 将 emit 改为有界提交，新增事件适配调用 | 不能让 ingest_packet 等待 LLM/TTS |
| `voice_input.py` | 区分 submitted 与 spoken，生命周期订阅更新历史 | 保留原查询意图处理逻辑 |
| `interaction.py` | 扩展 speech metadata、事件状态、TTL | 版本化 schema，旧调用兼容 |
| `conversation_context.py` | 记录语音状态及最近真实完成语音 | 不承担跨比赛持久记忆 |
| `personality/events.py` | 新增事件结构与幂等处理 | 纯数据层 |
| `personality/runtime.py` | 新增事件 reducer 与状态快照 | 不直接调用策略引擎 |
| `personality/emotion.py` | 情绪衰减、原因跟踪、状态校正 | 可离线回放 |
| `personality/relationship.py` | 证据与 SQLite 存储、迁移 | 持久状态可重建 |
| `personality/growth.py` | H0-H3 阶段规则 | 阈值配置化 |
| `personality/dialogue_policy.py` | 是否说话/时机/优先级 | 规则优先 |
| `personality/humor.py` | 触发、禁区、冷却、重复控制 | 无 LLM 也可运行 |
| `personality/speech_personalizer.py` | 确定性模板 + 可选异步 LLM | 不修改原始 StrategyDecision |
| `llm/provider.py` | 本地/远端模型接口、deadline、cancel | 默认关闭 |
| `llm/validator.py` | 结构校验、事实约束、禁用改写关键指令 | 失败原文回退 |

## 9. 测试与验收矩阵

### A. 调度器 FakeSpeechBackend（优先写）
1. active A 完成后无新提交，pending B 自动启动。
2. 可取消的低优先级 active 被紧急任务抢占；取消延迟有界。
3. 不可取消 critical 不被幽默抢占。
4. start 抛异常 → FAILED，无悬挂 active，后续任务正常运行。
5. 后端异常退出 → FAILED，不记 completed。
6. `stop` 超时 → 记录故障并执行保守恢复。
7. 不同 request_id 的相同 action_code 查询不误抑制。
8. 旧 snapshot 的 LLM 结果被丢弃。
9. optional 排队过期后不会延迟播报。
10. repeat_last 只取真实完成的内容。
11. 并发提交下 event_id 唯一且状态转移合法。
12. Null backend 不被当作真实播放成功。

### B. 人格事件回放
1. 相同 event_id 重放两次只生效一次。
2. 高 UDP 频率下单次碰撞只触发一次情绪变化。
3. 进站换胎后对应轮胎担忧恢复，其他担忧不被误清除。
4. 程序重启后长期关系恢复；不同 session 不串台。
5. TTS 失败、建议未确认时不计入“忽略建议”。
6. H1/H2 边界信任波动不造成成长阶段振荡。
7. 严重风险下幽默触发次数为 0。
8. 100 场景评估角色一致性、重复率、误报和延迟。

### C. 实时性能
- 对比改造前后 p50/p95/p99 的 decode、strategy、pipeline 延迟；不得因 LLM 推理产生持续性积压。
- 紧急播报抢占延迟需真机测量，阈值按设备和音频后端实测制定。
- 在无 GPU、TTS 失败、LLM 断连和高频事件场景做故障注入。

## 10. 分阶段交付与回滚

- **S0 冻结基线**：固定 commit SHA、列文件清单、运行现有测试、建立 FakeSpeechBackend 测试。
- **S1 修调度**：独立 tick、抢占、取消、失败与真实完成事件；保留 facade。
- **S2 解耦实时主链**：有界消息投递、单消费者输出线程、统一指标。
- **S3 人格事件层**：EventAdapter、幂等 reducer、可回放日志。
- **S4 人格状态层**：情绪、关系证据、成长阶段、SQLite 迁移。
- **S5 统一表达层**：策略/查询/主动机会共用 DialoguePolicy 与 SpeechPersonalizer；先模板后 LLM。
- **S6 幽默与 LLM**：低优先级、超时回退、100 场景测试、真人比赛评估。
- **S7 设备端验收**：Pi 5/CM5、真实音频、麦克风并发、故障注入和长时回放。

每阶段独立 feature flag：`speech_scheduler_v2`、`personality_events`、`personality_runtime`、`optional_speech`、`llm_personalization`；默认逐项开启。回滚只关闭新路径，不删除历史证据日志。

## 11. 全仓审计交付标准（未达成）

只有以下条件同时满足，才可以标记“所有代码核实完成”：
1. 已获取完整仓库及确切 commit SHA；
2. `git ls-files` 中每个源码、测试、配置、入口、部署脚本都有分类记录；
3. 所有语音调度调用者、线程/进程入口、状态写入者均有调用图；
4. 所有现有测试已运行并附通过/失败报告；
5. 上述调度和人格关键测试至少以 FakeBackend 执行，真实设备部分明确标记待真机；
6. 发现的冲突都标注源码位置、复现步骤、修复 PR 与回归结果。

**目前状态：已形成详尽实施蓝图；未达到全仓审计完成标准。** 若要完成剩余工作，需要可在执行环境读取的完整仓库 ZIP/工作树，或可用的 GitHub 仓库连接。此前本环境直接 `git clone` 失败（无法解析 github.com），网页源码访问不能代替全仓测试。

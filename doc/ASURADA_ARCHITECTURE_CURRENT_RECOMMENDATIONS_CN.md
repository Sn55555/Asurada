# Asurada 当前架构建议

以当前未提交工作区为依据。旧版 `ASURADA_ARCHITECTURE_REVIEW_2026-09-15_CN.md` 中部分缺陷已经修复，不能直接作为当前缺陷清单。本次只新增审查材料，不修改业务实现。

## 结论

保留确定性赛车内核，将产品组织为实时决策、交互解释、赛后训练三条执行链，统一事实契约、场次身份、任务取消和输出所有权。当前已经实现不少基础设施，下一阶段应以生产调用链收口和行为验收为主。

## 已有基础

- `assessment.py`、`models.py`、`snapshot_contract.py` 已有共享评估、决定记录和快照绑定，燃油查询不应再按旧报告描述为独立阈值冲突。
- `task_runtime.py` 已有单调 deadline、取消和有界工作线程；`workflow_store.py` 已有 SQLite 检查点、任务锁和恢复。
- `app.py` 的 live 入口已接入有界接收、异步日志、后台观察模型和低频规划。
- `speech_service.py` 已提供跨进程播报所有者；客户端退出不关闭共享播放，服务拒绝第二所有者，并保留未确认停止时的锁。
- `session_lifecycle.py` 已拒绝显式旧 epoch 和退休场次，不能再把状态仓描述成完全不隔离场次。
- `training_partition.py`、`training_join.py`、`training_windows.py` 已对整场分割、标签身份和连续未来窗口设置检查。
- `session_review_workflow.py`、`corner_review.py`、`training_plans.py` 已实现可恢复复盘与有证据的训练草稿。

## 1. P0：隔离语音服务故障，完成唯一输出所有权

后续实施更新：live 共享服务路径已接入有界后台提交，`--live-udp` 也已默认管理共享服务，voice loop 默认附着，离线 CLI 与 live socket 隔离。下面的同步 IPC 和默认配置风险保留为改造前依据。结果见执行计划 A03/A06 最新进展；在途取消、场次权威广播等仍未完成。

`make_voice_output()` 只有在配置 `ASURADA_SPEECH_SOCKET` 时使用共享服务，否则每个进程仍可创建本地播放器。生产启动器需要统一管理服务与客户端配置，并区分离线回放和在线播报范围。

更紧迫的是 `runtime_pipeline.py:63` 同步调用 `emit()`；共享客户端同步连接、写入和等待响应，默认预算 1 秒。`LiveRuntime` 此处只捕获 PacketDecodeError，语音 IPC 异常可能退出遥测运行。异步日志和模型隔离并不能覆盖这个阻塞点。

建议增加有界的播报提交适配器：实时链仅投递候选，输出服务独立接收；记录 accepted、started、completed、cancelled、expired、delivery_unknown。失败时核心继续记录决定和刷新仪表，不偷偷创建另一个播放器。停止应走独立高优先级控制通道。

验收：暂停或杀掉语音服务、制造慢响应时，遥测仍处理；队列有上限；恢复后不补播过期内容；取消确认前不启动替代播放。

## 2. P0：统一场次权威与整轮取消

目前生命周期保护仍分散在组帧器、状态仓、语音输出中；退休场次清单有界且在内存内，客户端自己提交场次绑定。需要一个接入侧权威发布 SessionStarted、EpochChanged、TelemetryStale、SessionEnded。

统一传播 session_uid、epoch、snapshot_id、decision_id、task_id。切场/倒带取消旧 ASR/LLM/TTS 任务；发送前重新校验 scope、年龄和决定适用性。同场回复也可能因状态变化而失效，不能只核验 epoch。

`phase3_macos_voice_loop.py:250–259` 播放期间跳过监听，因此播报取消能力尚不等于用户能随时通过声音打断。先把按钮/PTT/停止通道接通，再根据真实回声测试决定 AEC 与同时监听方案。

验收：慢 LLM 跨切场返回、播放期间停止、断流后提问、同 epoch 旧回复均有端到端用例。

## 3. P0/P1：让数据质量真正约束领域判断

组帧器已有缓存 TTL 和质量信息，但仍有多个 `get(field, 0)`；领域模型部分字段强制 float，质量还未成为所有规则/特征/回答共同消费的契约。需逐字段确认合法包必填值与缺包默认值，避免把所有零都判作异常。

建议在关键字段引入 value、source、observed_at、quality，统一 valid/estimated/stale/unavailable 语义。从燃油、ERS、轮胎、前后车差和赛事控制开始；缺失要抑制依赖该字段的判断，不能自动解释成低风险。短窗口改为时间范围查询，避免 recent(12) 随输入频率改变实际含义。

验收：同一输入的规则、查询、解释、HUD 结论一致；缺失和真实零可区分；不同输入频率下同时间窗口结果可比较。

## 4. P1：将能力注册表升级成可组合的领域工具

`CapabilitySpec.tool_schema()` 输入统一为空对象，输出主要为 speak_text/action_code。`CapabilityExecutor` 已有次数、权限、超时和快照检查，但这些工具更多是语音回答函数的封装。

先增加少量真实可组合工具：get_current_assessment、get_decision_evidence、compare_laps、compare_segment、get_pit_projection、create_training_draft。输入显式指定场次、圈、区段和比较条件；输出返回数值、单位、证据引用、质量、假设和版本，播报文本由表达层生成。

同一能力定义应驱动路由、schema、权限和测试清单。保留固定快速查询；开放式分析才使用有限工具循环，设置时间、次数和模型调用预算。

验收：一次跨圈问题可组合工具完成，数值不需要从自然语言重新解析；添加能力无需重复维护多个允许列表。

## 5. P1：从“引用存在”推进到“结论可核验”

`llm_evidence.py` 已拒绝比赛场景纯文本兜底，检查 reason_fields 存在，但 request_id 仍可省略，未逐条检查回答数字与单位。存在正确引用不保证自然语言结论正确。

建议结构化 claims：fact_ref、value、unit、comparison/derivation，以及强制请求/决定绑定。机器核验事实和推导关系，模板渲染关键赛况数字；LLM 负责组织解释。无法核验的因果说明应明确为假设。

验收：伪造数值、单位错误、旧决定、正确引用配错误结论都被拒绝或降级。

## 6. P1：把已有复盘流程做成训练闭环

当前 `session-review-v6` 已有固定 6 步，原始捕获增加投影共 7 步。训练重点基于三圈同条件区段的最大耗时波动，后续圈只记观测变化。这是合理的第一版，不能说它已经诊断制动、走线或油门原因。

下一步增加距离对齐的制动开始、最低速度、入/出弯速度、油门恢复、挡位等指标，并控制轮胎、天气、燃油、交通和黄旗条件。区分观测差异、解释假设、训练建议。产品支持查看证据、激活一条计划、记录执行、比较多次结果、撤销错误长期记忆。

保留已有 WorkflowStore，先验证该真实闭环。只有当动态分支、人工暂停和复杂恢复的维护成本上升时，再比较 LangGraph 等工作流运行时；不要同时维护两套任务状态真相。

## 7. P1：统一多端领域契约

iOS AppState 仍混合网络、JSON/CSV、圈记录、车损判断与 Live Activity，独立 bridge 仍维护协议解释。网页已有慢客户端隔离，不应照旧报告重复建议“从零增加队列”。

由核心提供 TelemetrySnapshot、DecisionRecord、SessionEvent、SpeechEvent 的版本化投影。iOS 按接入、会话、圈仓库、车损展示拆职责；离线模式也复用同一份规范和 golden fixtures。ESP32 的显示协议与当前 UI 可继续保留。

验收：相同录制输入下各端字段、圈边界与车损等级一致；慢客户端不拖住核心。

## 8. P1/P2：模型准入绑定真实评估，补齐发布基线

整场分割和训练记录身份已改善，但伪标签拟合仍主要证明复现旧规则。模型资产 hash 和特征清单已有检查，active 的评估证据仍主要是非空引用。

准入应绑定模型 hash、特征实现版本、数据集 manifest、标签类型、适用范围、校准结果和行为差分报告。观察模式先证明跨完整场次/赛道/驾驶员的价值，再进入 active。

建立同一源码版本的组合验证：完整捕获回放、故障注入、安装包与模型资产、平台启动。单独列出真实 UDP、麦克风/扬声器、iOS/ESP 和训练收益验收，不把离线通过合并成产品完成。

## 推进顺序

1. 实时链语音隔离、唯一输出配置、场次权威和取消。
2. 字段质量、统一决定、结构化工具与解释核验。
3. 一个三圈比较到后续训练观测的完整用户流程。
4. 多端投影、模型准入证据和发布/实机验收。

## 阅读及验证边界

当前对五个代码目录扫描得到：core/src 106 文件/26081 行，core/scripts 139/21423，网页 5/2258，ESP 8/442，iOS 25/6088，共 283 文件/56292 行。统计按源码和配置扩展名筛选，排除依赖、构建、资源与数据目录；目录范围不等于整个仓库所有文件。扫描中的 Python AST 均解析成功。

结合已有代码审查上下文，本次复核了运行入口、同步 IPC、取消、状态生命周期、评估/解释、工具执行、持久复盘、训练和多端接口。结构扫描不等于 56292 行逐行审计，不声称穷尽每条路径。当前轮次选定回归结果位于 `output/architecture-review-current/contracts/summary.json`；现存共享语音 17 项检查位于 `output/architecture-implementation/a03-shared-speech-final/summary.json`，后者为此前运行记录。本轮没有进行真实音频或设备测试。

外部设计参考：[Anthropic workflows 与 agents](https://www.anthropic.com/engineering/building-effective-agents)、[工具设计](https://www.anthropic.com/engineering/writing-tools-for-agents)、[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。以上选型建议是结合代码现状的判断。

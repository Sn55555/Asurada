# Asurada 架构复核与改进建议

依据当前未提交工作区；不修改业务代码。旧报告与执行计划有不同阶段的记录，本文件中的判断以本次复核的实现为准。

## 结论与边界

保留确定性赛车内核，明确实时决策、交互解释、赛后训练三条链。下一阶段重点是统一事实、任务生命周期和输出所有权，再开放可组合工具与训练闭环。

本次源码清单扫描：core/src 114 文件 / 26764 行；core/scripts 150 / 22387；live-dashboard 5 / 2258；iOS app 19 / 5202；ESP 7 / 399。合计 295 文件 / 57010 行。按源码扩展名筛选，排除依赖、构建和生成资源。Python AST 均解析成功。清单扫描不等于所有文件逐行审计；结合此前审查上下文，本次重新阅读了关键运行链、边界实现和相关测试，不声称穷尽全部分支。

8 组针对性回归通过、0 失败、0 跳过：domain_assessment、capability_executor、llm_evidence、session_lifecycle、workflow_store、training_plans、doubao_session_cancellation、http_asr_cancellation。证据：`output/architecture-review-refresh/contracts/summary.json`。未执行全量回放、真实云端 ASR、麦克风、iOS 或 ESP 实机验收。

## 已具备的基础

- `app.py` live 入口已使用有界收包、异步日志和最新状态投影；观察模型和低频规划已有独立执行通道。
- `assessment.py` 与 DecisionRecord 已提供共享评估和快照绑定；燃油判断已有统一入口。
- `task_runtime.py` 已限制后台并发并拒绝取消后交付；不合作线程会保留占用，避免超时后无限增生。
- `live_speech.py`、`speech_service.py`、`speech_submission.py` 已提供默认共享播报服务与异步提交。旧报告中实时链同步等待共享服务的问题已有改进。
- `session_lifecycle.py` 已拒绝显式旧 epoch、退休场次与部分乱序数据。
- `workflow_store.py`、`session_review_workflow.py`、`training_plans.py` 已支持持久复盘、恢复、训练草稿和后续观测。
- 网页已有每连接一个最新待发帧的队列；ESP 保持像素投影，适合继续作为显示适配器。

## P0：取消、场次与播报交付形成统一协议

`voice_sidecar_asr.py` 中 HTTP batch 和直接实时 WS session 已支持上下文；但 Doubao batch WS 的 `transcribe_audio` 仍未接受 TaskContext。服务端只对声明 supports_task_context 的后端传递上下文。外层超时返回不等于上游识别停止，连续超时可能持续占用有限工作槽。

`voice_sidecar_server.py:286` 的实时 TCP 接入仍使用 ThreadingTCPServer、无长度上限的 readline；打开 session 没有传递上下文。应补连接数、帧长、总字节数、空闲与整轮时限，并在断连时取消上游。重复 start 必须明确拒绝或先关闭旧 session，防止覆盖 session 引用后遗留资源。

场次保护目前分散于接入、状态仓、语音输出与客户端文件观察。`speech_service.py:128` 仍允许客户端绑定场次。建议接入侧拥有唯一 SessionScope 权威，发布场次、epoch、断流和结束事件。所有请求带 scope、snapshot_id、decision_id、task_id，交付前核验；同 epoch 还需按问题检查相关事实是否改变。

停止应在输出所有者处形成跨客户端顺序屏障：停止之前产生的候选不能在停止之后再次启动；后续新告警是否允许播报是显式产品策略。现有客户端内部锁不能提供整个系统的这一保证。

验收：慢识别跨切场、停止后迟到回复、断流、重复 start、超长帧、慢客户端、语音服务故障时，核心持续处理数据，资源数量有界且旧结果不会交付。

## P0/P1：把数据质量变成领域输入契约

PacketFreshness 目前主要描述包级缓存；assess_domain 对轮胎、ERS、车距等仍主要检查数值合法性。合法数字不保证来源仍有效。逐项追踪组帧默认值，区分真实零、缺包、估计和过期。

关键字段采用 value / unit / source / observed_at / quality，规则、模型特征、工具与展示共同消费。未知时抑制依赖该事实的判断或使用明确降级路径。优先燃油、ERS、轮胎、车距和赛道控制，不一次性改造所有字段。

`runtime_pipeline.py` 与离线入口仍用 recent(12)，实际窗口会随输入频率变化。改为按时间范围取历史，并定义最低覆盖率、最大间隔与采样要求。

验收：缺失与真实零产生不同结果；规则、语音和 HUD 的事实一致；相同时间范围在不同输入频率下可比较。

## P1：领域工具返回事实，表达层负责说话

`CapabilitySpec.tool_schema()` 的输入都是空对象，输出主要是 speak_text/action_code；执行器明确拒绝非空参数。因此现有注册表适合固定问答，尚不足以支撑跨圈、跨区段组合分析。

增加少量参数化工具：get_current_assessment、get_decision_evidence、compare_laps、compare_segment、get_pit_projection、create_training_draft。按工具返回结构化数值、单位、比较条件、证据、质量和版本；展示文案独立渲染。只读分析与创建训练草稿分开授权，并为写入定义幂等键。

保留固定快速查询；开放式分析才启用有限工具循环，具有总时限、工具次数、模型调用与费用预算。不要把每个领域工具都包装成独立 Agent。

验收：“最近三圈在哪个区段波动最大”可用结构化工具完成，数值无需从自然语言重新解析；新增能力不需要重复维护多个允许列表。

## P1：解释验证从引用存在推进到结论正确

`llm_evidence.py` 会拒绝未知引用和比赛场景纯文本兜底，但 request_id 可省略，未验证回答中的数值、单位和推导。引用真实字段仍可能说错结论。

增加结构化 claims：fact_ref、value、unit、operation、operands；强制绑定请求和决定。程序验证计算，关键数值由模板渲染；模型负责解释组织，因果描述单独标记假设。

验收：正确引用配错误数字、单位错误、旧决定和错误比较方向均被拒绝或降级。

## P1：围绕一个用户流程完成训练产品

当前复盘固定六步，原始捕获增加投影共七步。TrainingPlanStore 选取三圈同条件区段中最大耗时波动，至少 50 ms；后续记录一圈变化。它支持稳定性练习，不等于已定位驾驶动作原因，也不能证明训练收益。

下一步增加距离对齐的制动开始、最低速度、入弯/出弯速度、油门恢复与挡位，并检查燃油、轮胎、天气、交通和旗号可比性。形成“查看证据 → 选择一条练习 → 激活 → 执行 → 多次比较 → 保留或撤销”的完整流程。事实、解释假设与长期驾驶员画像分层保存。

## P1：统一各端事实投影

iOS AppState 同时承担网络接入、JSON/CSV 解码、回放、车损判断和 Live Activity。建议逐步拆成接入适配器、会话仓库、回放控制和展示模型。领域等级尽量由核心投影；需要离线计算时共享规范与 golden fixtures。

统一版本化 TelemetrySnapshot、DecisionRecord、SessionEvent、SpeechEvent。保留网页布局和 ESP 像素协议；以相同录制输入验证字段、圈边界与等级一致。

## P1/P2：模型和发布验收绑定同一版本

ModelAdmissionPolicy 默认观察或禁用，方向正确；active 当前要求非空证据引用，还不足以证明引用对应真实有效的评估。绑定模型 hash、特征实现版本、数据集 manifest、标签来源、适用范围、校准与行为差分报告。用跨完整场次的独立证据证明价值后再放开决策权限。

依赖配置中尚无 websocket-client 的显式可选安装项，而生产 WS 后端直接 import websocket。应补能力依赖和干净环境启动验收，并将源码、配置、模型资产与测试证据绑定同一发布清单。

最后跑同一版本的全量合同、完整捕获回放、故障注入与安装包验收。真实 UDP、音频/AEC、iOS/ESP、训练价值单独记录，不用离线测试数量替代。

## 目标结构与实施顺序

实时链：遥测接入 → 统一事实与场次 → 确定性评估/仲裁 → 候选提交。

交互链：用户输入 → 任务上下文 → 固定查询或有限工具循环 → 结论验证 → 候选提交。

复盘链：不可变录制证据 → 持久工作流 → 圈/区段分析 → 训练草稿 → 后续观测。

三条链共用事实与版本契约；输出服务负责最后的 scope、时效、优先级和停止校验。

先完成 P0 边界，再升级事实/工具/解释；随后用一条训练流程验证价值，最后收口多端和发布。保留模块化本地架构，仅隔离需要独立生命周期的语音及阻塞推理进程。

目前不建议整体迁移 Agent 框架。只有动态分支、人工暂停和恢复复杂度确实超过现有 WorkflowStore 时，再用赛后复盘做受控选型；避免两套任务状态共同控制同一流程。

外部参考：[Anthropic workflows 与 agents](https://www.anthropic.com/engineering/building-effective-agents)；[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。前者也提示工具生态已变化，因此这里仅用其工作流/自主循环的概念区分；选型取舍以本仓库需求为依据。

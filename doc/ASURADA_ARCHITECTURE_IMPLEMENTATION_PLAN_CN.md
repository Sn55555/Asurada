# Asurada 架构改进执行计划

目标：完成 2026-09-15 架构评估提出的改进，完成开发侧验证，保留真实比赛、语音、网页和训练价值测试供隼人最终验收。按隼人最新要求，iOS 暂缓，ESP 适配不做，均不纳入本轮开发完成与验收条件。

本计划以当前工作区为基线，保留已有改动。不得把新增契约、单元测试通过或模拟后端通过视作完整产品验收。每项实现须接入真实入口；新旧路径并存期间明确权威路径。暂不推送、部署、烧录或操作真实比赛。

状态：未开始 / 进行中 / 开发验证通过 / 待用户验收。最后更新时间：2026-09-15。

| ID | 工作包及具体交付 | 依赖 | 开发侧完成条件 | 状态 |
| --- | --- | --- | --- | --- |
| A01 | 统一领域评估：燃油、轮胎、资源、攻防事实；AssessmentResult/DecisionRecord；核心、查询、LLM 共用事实与理由 | 无 | 相同快照的数值/结论一致；业务不依赖另一套回答阈值；记录关联规则与快照版本 | 开发验证通过 |
| A02 | TaskContext、单调 deadline、取消信号、有界执行器；贯穿 LLM 与后备请求；晚到结果丢弃 | 无 | 超时及时返回、重试不扩大预算、并发有界、取消后结果不交付 | 开发验证通过 |
| A03 | 唯一声音调度者；抢占、TTL、独立推进、真实取消；核心与 voice loop 使用同一服务；ASR 打断入口 | A02 | 所有生产路径通过调度者；假播放器验证停止确认与断流收尾；无绕行直接播放 | 开发验证通过 |
| A04 | SessionLifecycle/epoch；新场次、倒带、断流清理；时钟注入、时间窗口；字段来源/年龄/缺失语义 | 无 | 跨场次、倒带、乱序和缺包用例覆盖；旧场任务/提示不会进入新场 | 开发验证通过 |
| A05 | DecisionContributor 准入、缺失分数不参与评分、长期规划独立权限、资产与特征版本绑定 | A01/A04 | contributor 差分回放；关闭/观察无影响；有效证据与资产关联；相对路径可迁移 | 开发验证通过 |
| A06 | 实时链与慢任务隔离：异步日志、观察模型有界后台、规划事件触发、最新状态接口 | A02/A04/A05 | 故障/慢任务注入不阻塞实时链；记录队列积压、丢弃、端到端阶段时间 | 开发验证通过 |
| A07 | 单一能力定义入口、领域 handler、输入输出 schema、权限、时效与播报策略；替代多处能力分支 | A01/A02 | 已有全部能力可用；新增能力不需修改多处路由表；注册清单与测试一致 | 开发验证通过 |
| A08 | LLM 依据校验：证据引用、有限数值、快照/决定匹配、比赛格式错误回退；历史/陪聊上下文隔离 | A01/A04/A07 | 编造引用、非有限数值、过期决定、任意文本回退均有明确行为；结构化回答一致 | 开发验证通过 |
| A09 | 版本化 TelemetrySnapshot/DecisionRecord/VoiceEvent/SessionEvent；网页传输与慢消费者隔离；iOS 暂缓，ESP 适配不做 | A01/A04/A06 | 核心与网页的同一回放契约及断流状态一致；既有仪表结构保留；本轮排除 iOS 与 ESP 适配 | 开发验证通过 |
| A10 | 持久任务执行与受限工具：状态、决定、圈/弯摘要、比较、规划依据、训练报告；恢复、次数和预算限制 | A02/A07/A08 | 一个真实赛后流程从数据到报告完整执行；中断恢复不重复副作用；失败可追溯 | 开发验证通过 |
| A11 | 会话索引与训练记忆：本场事实、验证过的驾驶表现、用户偏好分离；报告结果与后续圈对比 | A04/A10 | 记忆有来源、有效期和作用域；无数据不造结论；训练建议与后续表现可关联 | 开发验证通过 |
| A12 | 训练/评估治理：伪标签标识、按完整场次分割与预测窗口间隔、统一特征契约、规则基线与真实标签区分 | A01/A05 | 导出和训练实际使用分割策略；无交叉泄漏；缺真实标签明确报告，不伪称模型质量通过 | 开发验证通过 |
| A13 | 发布配置、依赖、资产可迁移、健康与恢复；统一可观测轨迹；开发侧综合回放/故障验证 | A03/A06/A09/A10/A12 | 干净环境可启动；版本可追溯；失败恢复和完整回放报告齐全 | 开发验证通过 |
| U01 | 隼人真实 F1 比赛验收：开局/结束/重开/倒带/掉包/关键提醒；核对事实一致与提示负担 | A13 | 由隼人记录通过/问题 | 待用户验收，实施完成后执行 |
| U02 | 隼人真实语音验收：唤醒、问答、取消、抢占、断网、回声；测实际停止与响应体验 | A13 | 由隼人记录通过/问题 | 待用户验收，实施完成后执行 |
| U03 | 隼人网页验收：字段一致、断流、重连、性能与现有视觉；iOS 与 ESP 不纳入本轮 | A13 | 由隼人记录通过/问题 | 待用户验收，实施完成后执行 |
| U04 | 隼人训练价值验收：最近三圈弯道分析、训练重点、后续圈效果与记忆连续性 | A13 | 由隼人记录通过/问题 | 待用户验收，实施完成后执行 |

执行顺序：先交付 A01/A02/A04/A05 的正确性基础，再 A03/A06，随后 A07/A08/A09，完成 A10/A11/A12，最后 A13 综合审核。工作包可交错推进，但不能仅有孤立接口而未接入口就标记完成。

验证纪律：每个变更运行有意义的新增行为用例及相关既有回归；阶段末做综合回放。记录当前证据路径、失败与修复。最终逐项审核 A01–A13 的生产接入、测试和文档后，才将开发目标标记完成；U01–U04 原样保留给用户。

## 当前进展

### 最终交付：A01–A13 开发验证完成，U01–U04 保留待验收

修复后最终回放正常退出 0，耗时 1312.74 秒，源码与输入哈希不变。主抓包 31,726 个快照全部完成决定记录、场次事件恢复、网页身份绑定及源时间校验，拒绝 0；四个重叠场次子集的 5,163 / 4,879 / 3,166 / 5,071 个快照也全部通过。子集来自主抓包，不能当作额外独立样本。

当前 182 个契约回归全部通过、无失败和跳过；当前 wheel 的 11 项干净构建/隔离安装检查通过。A01–A13 均有逐项完成审计，最终索引为 `output/architecture-implementation/final-completion-audit.json`。所有本轮验证进程均已结束，未部署、推送、烧录、启用模型或代做真实比赛验收。

开发完成不等于真实产品体验验收通过。U01–U04 全部保留，由隼人按 `doc/ASURADA_FINAL_USER_ACCEPTANCE_CN.md` 执行。iOS 暂缓，ESP 不做；口头停止需耳机/回声隔离，当前没有 AEC；模型的派生标签指标不构成驾驶收益结论。最新交付入口为 `doc/ASURADA_ARCHITECTURE_DELIVERY_CN.md`。下方历史进度（包括中断和旧失败）为过程记录，当前状态以本节及表格为准。


### A13 修复后 182 个契约回归与干净安装通过

`a13-missing-fixed-contracts` 已退出 0，182 通过、0 失败、0 跳过；对照当前脚本清单无遗漏，源码哈希一致。`a13-missing-fixed-wheel` 11 项干净构建/隔离安装检查通过，wheel SHA-256 为 `599a596684da0d8f683a571dd012792c45ea018756e0e0b51f4704b00c8e1ffd`。这些是缺失值修复后的证据，取代旧版本作为当前交付依据。

`a13-missing-fixed-replay`（95402）仍在运行，必须读取完整终态并检查逐快照网页/场次/决定契约计数后才能关闭 A09/A13。用户验收继续保留。


### A13 缺失值修复后集成验证启动

已确认旧回放因修复需要主动中断，未复用其通过状态。当前启动 `a13-missing-fixed-replay`（95402），主抓包及场次子集均无快照上限，保留每个快照的网页/决定/场次事件校验；临时日志仍限定两份归档。

当前全部 182 个契约脚本由 `a13-missing-fixed-contracts`（41342）执行；`a13-missing-fixed-wheel`（39031）重新离线构建并隔离安装。三项任务分别记录输入哈希与报告，当前均不得提前宣称通过。验证期间保持源码不变，待终态后更新交付索引和用户验收开始条件。


### A09 缺失值投影与页面显示修复通过

已修复缺失/NaN/无穷/布尔/错误文本导致网页异常或冒充数值的问题。损伤汇总只有组成项可用时才给出数值，真实完整零值保留；无有效官方间距时可使用有效估计值并标记来源。无数据占位的资源、温度和损伤使用空值。页面以“—”和灰色呈现未知资源/轮胎/损伤，缺失速度不显示有效指针，仪表结构保留。

新增 30 项 `dashboard_missing_values_regression` 检查通过；`a09-missing-values` 5 组相关回归全部通过。实际 Chrome 1440×1000 页面从未知值恢复到真实零值通过，无 pageerror；截图已检查，临时证据位于 `/tmp/asurada-a09-qa/missing-result.json`、`missing.png`、`zero.png`。本机服务已停止。这是 HTTP 回退和合成遥测页面验证，不是实际比赛验收。

此前回放 13502 因明确发现此缺陷而主动停止，退出 130，子进程错误记录为 KeyboardInterrupt；不是通过或运行中，终态记录保存在 `a13-final-replay/process-completion.json`。此前 181 项回归及 wheel 属修复前版本，需刷新受影响证据和最终回放，再完成 A09/A13。U01–U04 全部保留。


### A09 完成审计发现缺失值投影缺口

对照 U03-1“缺失不显示为可信的零”做隔离检查：在 `state.raw={}` 时，网页单项损伤为空，但 `body_damage_pct` 与 `powertrain_damage_pct` 汇总仍为 0；当 `player.ers_pct=None` 时 `build_dashboard_payload` 抛出 TypeError。证据暂存 `/tmp/asurada-dashboard-missing-evidence.json`。这是尚未被当前 181 项回归覆盖的实际缺口，A09/A13 不能仅凭在跑回放通过就关闭。

当前回放源码保持未变，进程 13502 仍运行。后续必须修正网页投影及对应缺失显示，并加入有针对性的回归和页面验证；随后重新判定受影响证据，不能沿用当前 wheel/网页测试作为修复后的完整结论。


### A13 全部 181 个当前契约回归通过

`a13-final-contracts` 已终态退出 0：181 通过、0 失败、0 跳过。对照当前目录发现的所有契约脚本，缺失/多余均为零；源码运行前后及终态复核哈希一致。完整报告、进程终态和覆盖审计位于 `output/architecture-implementation/a13-final-contracts/`。此结果包含本轮新增识别泵、口头停止、网页来源状态与事件契约，并覆盖本机监听及故障注入。

主抓包及重叠场次子集的无上限回放仍在执行（13502），尚未给出通过结论。最终验收表已更新网页来源状态操作说明，U01–U04 全部保持待用户验收。


### A13 当前干净安装验证通过

`output/architecture-implementation/a13-final-wheel/summary.json` 的 11 项检查全部通过，构建和检查期间源码及网页输入哈希不变。在全新临时源码目录离线构建 wheel，再安装到全新 Python 虚拟环境，验证完整 Python 模块、资产哈希、CLI 启动和 demo 日志、训练档案 CLI 场景，以及网页所需依赖与 socketpair 发送。新增识别泵、口头停止和来源状态模块可脱离 checkout 导入。wheel SHA-256 为 `35a5f04b1078323409845c97335822be7280253e68781773aec21cfbcd92d287`。

此次是本地打包/安装验证，不是发布，不包含可选模型依赖、真实云 ASR、声音设备或比赛验收。当前全部契约回归与无上限回放进程仍在运行，须读取各自终态后决定 A09/A13 是否通过。


### A13 当前最终回放与完整契约回归启动

已启动 `a13-final-replay`，主抓包与各场次子集均不设快照上限，临时日志保留两份归档。每个接受快照新增网页决定/快照绑定、场次事件恢复和源时间 live/stale 校验；原有决定严格 JSON 往返继续执行。运行输入哈希已记录，当前不得以启动状态声明通过。

同时启动 `a13-final-contracts`，使用当前 `run_regressions.py --suite contracts --timeout 180` 自动发现全部 181 个契约脚本；包含本轮新增口头停止、网页来源与事件契约。主回放单独执行。进程句柄分别为 13502 和 85396，须读取终态和报告后判定结果。干净安装验证在结果核对后执行；U01–U04 仍待用户验收。


### A12 训练治理开发审计通过

当前 8 组分割、入口、导出、连续预测窗口、来源、关联及重训入口回归全部通过，运行期间源码未变。再次读取并验证 14 个隔离资产的模型/特征哈希、整场分区无交叉、已验证输入来源及 `human_validated=false`；完整修复版导出重新通过校验。审计位于 `output/architecture-implementation/completion-audit/A12.json`。

已有真实六阶段训练、347 个模型/特征组合全值对照与布局修复后完整导出差分作为历史证据保留；它们不等于当前全链路最终验证。规则版本从 domain-v3 到 domain-v4 的标签来源变化已明确记录，未声称所有 CSV 字节相同。没有生产启用模型，也没有把伪标签拟合指标当作真实驾驶质量。A13 当前版本综合回放仍待完成，U01–U04 继续保留。


### A09 单条语音事件与场次事件接入

补齐事件契约缺口：`OutputLifecycleEvent` 现在逐条携带 `voice-event-v1`；权威 `UnifiedStateStore` 在开始场次、切场与倒带时产出 `session-event-v1`，包含当前/前一作用域和来源时间。后续快照保留最近一次作用域变更，避免最新值传输合并后丢失该记录。快照与网页投影携带同一事件，恢复时拒绝未知版本或跨场/epoch 绑定；旧快照仍可读取。这是最近一次场次变更的投影，不是无损全量事件队列。

`output/architecture-implementation/a09-event-protocol-check/summary.json` 当前 11 组回归全部通过，运行期间源码哈希不变，包含新增 13 项事件契约检查、来源/快照、生命周期、退休场次、语音事件游标以及真实本机 WebSocket 握手、异常帧、慢消费者、关闭行为。测试进程已结束。A09 仍待最终当前版本回放覆盖，A12/A13 尚未关闭；U01–U04 保留待用户验收。


### A09 来源绑定与断流显示缺口修复

核对发现网页原先把连接存活显示为 live，即使遥测早已停止。现增加 `dashboard-binding-v1` 的场次/epoch、快照与决定 ID，拒绝错误决定绑定；场次 UID 序列化为字符串以避免浏览器整数精度损失。服务端每次发送以源时间重算 `dashboard-source-v1`，与核心默认 15 秒阈值一致，不让传输心跳更新遥测年龄。网页现区分传输通道与 live/stale/future/unavailable 来源状态，未更改仪表绘图结构。

`a09-source-contract` 的来源契约、快照契约、慢消费者隔离 3 组测试通过，其中新增来源检查 21 项。本机 HTTP 回退实际 Chrome 页面完成 live → stale → unavailable → live；无 pageerror，1440×1000 仪表正常渲染，截图已检查。Browser 技能未提供，使用现有 Playwright；其自带浏览器版本缺失，改用已安装 Chrome，无安装依赖。临时 UI 证据位于 `/tmp/asurada-a09-qa/`，测试服务器已停止。此测试屏蔽 WebSocket，仅证明 HTTP 回退与显示状态；A09 完整协议/事件契约审计及 A13 当前版本综合验证尚未完成。


### A03 主循环口头停止验证及交付审计通过

当前代码已重新运行 5 组停止/识别/跨场取消回归，全部通过且运行期间源码未变。此前 9 组本地调度、5 组 IPC 和 shared_speech 修正测试环境后的复验均有报告；相关服务源码哈希一致。实际 CLI 主循环在已有播放期间接收口头停止，并验证播放器收到停止、无晚到播放及识别线程退出。审计见 `output/architecture-implementation/completion-audit/A03.json`。

口头入口需显式 `--spoken-interrupt`，使用耳机或隔离回声输入；没有实现 AEC。模拟转写/播放器不能替代 U02 真实语音验收，最终 A13 综合验证仍待完成。


### A03 持续识别泵接入口头停止模式

- 新增 RecognitionPump，复用全局单识别工作槽，普通识别结果采用容量 1 的最新值信箱；停止命令在泵线程调用 VoiceTurnInterruption.stop，不等待主线程的 LLM 请求。停止清空待处理结果并取消当前识别上下文；结果带生成代次/场次绑定，过期场次不得交付。
- phase3_macos_voice_loop 新增 --spoken-interrupt，实际接入泵的生命周期、next_result 与停止回调；该模式跳过旧播放暂停识别分支。CLI --help 已实际执行确认选项可用，README 更新操作方式与边界。
- recognition_pump_regression 使用真实泵与实际 VoiceInputCoordinator，在假 LLM 阻塞时注入完整识别结果，验证口头停止取消任务并清理播放、没有晚到播报、信箱容量/最新值、旧场次丢弃及泵线程关闭。a03-recognition-pump/summary.json 六组当前回归全部通过，源码哈希未变。
- 这是排队识别结果的技术验证，不是云端 ASR/麦克风/声学验证。模式显式启用且要求耳机或回声隔离输入，未提供 AEC；默认保留播放期暂停识别。A03 仍需实际主循环级模拟验证及完整生命周期审计，不将组件测试替代入口验证。


### A03 口头打断生产入口仍缺失，禁止提前关闭

- 读取 voice loop 实际控制流发现：播放/冷却期间直接 continue，process_completed_turn 同步执行期间也不发起下一次识别。现有 voice_interrupt_regression 验证的是独立 stdin 停止、在途取消与晚到 ASR 丢弃，不能作为播放中口头打断证据。
- 当前源码未发现已接入的 AEC；不得把键盘停止或识别结果注入冒称声学回声/真实口头打断通过。A03 保持进行中，需补并发识别接入及回声边界配置，真实声学效果仍由 U02 验收。
- 新增 spoken_stop.py 作为并发识别路径的命令路由：只接受完整识别且精确匹配唤醒词加注册 stop/cancel 别名，不将部分识别、裸停止词或句中提及当成停止。spoken_stop_regression 九项检查通过，a03-spoken-stop/router.json 保存结果。
- 路由尚未接入生产 voice loop，不能据此称口头打断完成；后续必须接入单一麦克风识别工作者、停止回调和有界结果传递，再验证 LLM 阻塞/播放期间实际主循环继续监听与取消。


### A03 声音调度入口与当前回归复核

- 核查实际 --live-udp 入口通过 LiveSpeechService 建立/附着共享服务，并显式注入 AsuradaApp；macOS voice loop 使用 live_speech_client 同一默认 socket。共享客户端退出只 detach，服务持有唯一输出对象与独立 SpeechOutputDriver，服务锁阻止第二 owner；离线 CSV/录制/demo 保留独立运行对象。
- a03-completion-local/summary.json 九组当前调度、独立时钟、停止失败恢复、换场、事件、实时提交以及播放取消/预算/结果回归通过。
- 经正常授权运行 a03-completion-ipc：启动、权威状态、排队适用性、策略适用性和停止屏障五组通过。shared_speech 失败于子进程无法导入 phase3_voice_regression，本轮自建 runner 仅传 src；原始失败 stdout/stderr 留存，生产逻辑与测试断言未更改。
- a03-shared-recheck 单独补齐 src/scripts PYTHONPATH 后重跑共享 owner/重试/退出场景，结果写入该目录。A03 尚需汇总本轮全部证据并核对真实语音打断接入后才能关闭。


### A07 单一能力定义交付审计通过

- 扩展 capability_interaction_definition_regression：临时注册一个新只读能力后，经实际 CapabilityExecutor 调用既有领域 handler、返回绑定结果，并确认缺权限时拒绝；与既有 ASR/路由/投影/提示/目录测试共同证明无需额外路由表。
- a07-completion-check/summary.json 七组当前回归全部通过、源码哈希未变，覆盖全部注册处理器、schema/输出作用域、调用次数、当前/历史权限、快照取代、语音优先级、时效与能力/父任务预算。
- completion-audit/A07.json 汇总逐项证据，A07 更新为开发验证通过。注册表属于可信应用配置；新增行为仍需实现对应 handler，控制行为继续由输出调度器执行，不冒称支持不受信任的任意插件。


### A04 长序列退场隔离修复与交付审计通过

- SessionLifecycle 与 ConsoleVoiceOutput 均将仅保留 16 个 UID 的队列替换为运行对象生命周期内的退场 UID 集合。这里只保留身份标识，不保留旧抓包/快照；新建运行对象用于明确重新回放时重新开始。
- 永久 retired_session_regression 使用 64 个连续场次，检查多个早期 UID 带更高 epoch/帧号仍不能切换状态、重绑声音或新建播放，新 UID 仍接受，新实例可明确回放旧 UID。修复前 23 项中 20 项失败，修复后全部通过。
- a04-retired-scope/summary.json 十一组当前回归全部通过，源码哈希未变；completion-audit/A04.json 逐项关联包/快照倒带、乱序与旧场拒绝、缓存 TTL/来源、时间窗口、未来/非法时间戳、实际 LLM 等待取消、声音换场及 Session 线布局证据。A04 更新为开发验证通过。
- 断流发现依赖配置的新鲜度/预算边界，不冒称瞬时检测；最新完整综合回放仍由 A13 承担，真实比赛与语音继续保留用户验收。


### A04 生命周期审计发现长序列退场边界

- a04-completion-check/summary.json 十组当前回归通过、源码哈希未变，覆盖包布局、倒带/乱序、缓存 TTL、运行时钟、时间加权窗口、旧 epoch/UID 拒绝、发布重置取消 LLM 和输出、后台规划换场。
- 未据此关闭 A04：SessionLifecycle 的 retired UID 队列只保留 16 项。实际建立 18 个不同场次后重送首个场次，UnifiedStateStore 接受旧 UID 并切回旧场次；a04-retired-scope/before.json 保存复现结果。
- 该长序列未被旧场次单次切换回归覆盖。需要修复退场身份生命周期并同步核查声音侧对应缓存，再运行扩展回归；A04 继续进行中。


### A01 统一领域事实交付审计通过

- 修复共享 _rear_rival_risk_reason 的固定距离绕行：后车 DRS 风险描述接收统一 defend_state；前后车理由函数在领域距离 unavailable 时不格式化无效时差。新增带实际 DriverState 后车对象的 rival_evidence_policy_regression，11 项通过，防止仅以无对手 fixture 误判整条路径已覆盖。
- 移除后车查询额外 1.4/1.5 秒的“逼近/准备防守”分支与 ERS 独立 55% 分级；未知后续时差趋势不再推断压力必然回落。保留已有 DRS 距离提示，它与可配置攻防决策阈值含义不同。
- a01-domain-completion/summary.json 13 组当前生产回归全部通过、源码哈希未变；completion-audit/A01.json 按共享评估、燃油来源、缺失值语义、内容绑定记录及跨核心/查询/LLM 一致性汇总证据。A01 更新为开发验证通过。
- 此结论是框架事实一致与开发侧契约通过，不是规则实战收益通过；最终综合版本仍需 A13，真实比赛验收仍留给隼人。


### A01 呈现层停止重建领域阈值

- persona_style 的整体姿态、最大风险与下一步重点现在显式接收 attack_state/defend_state/tyre_state，response_composer 从统一评估传入；移除呈现层独立 1.0/1.1/1.2 秒和 65% 行动阈值。当前主策略和处罚优先级语义继续保留。
- 磨损展望按领域 stable/manage/box_now/unavailable 标签表达，不再以 30/50/70% 自行建立另一套分级。保留实际磨损/胎龄/攻防窗口，说明缺少连续磨损依据时不能准确预测未来可跑圈数，移除硬编码未来一到三圈的确定性损耗判断。
- presentation_domain_regression 29 项检查覆盖高磨损但自定义阈值未触发、低磨损已触发保胎/进站、默认边界、整体重点和防守阈值一致性。
- 首次相关回归有两项因新文案使用“后续”而旧测试期待“未来/接下来”失败；改为自然表述“无法准确预测未来可跑圈数”，未放宽旧测试。a01-presentation-domain/summary.json 最终八组回归全部通过，源码哈希未变。


### A01 解释查询不再把问句前提当成策略事实

- 新增 rival_explanation_domain_regression：修复前 18 项中 15 项失败，覆盖未知/负数/NaN 后车时差、配置阈值、无对应决策却宣称防守以及已有进攻却被解释为未进攻等情形。
- rear_pressure_relief_outlook、defend_outcome_projection 与 why_defend 的直接压力条件复用领域 defend_state；数据不可用时不再据此预测压力回落或收益很低。已有进站/损伤证据仍作为独立依据保留。
- why_defend 只有在传入 DEFEND_WINDOW 主策略时称为当前防守决策，否则区分直接窗口条件与未确认决策；why_not_attack 对实际 ATTACK_WINDOW 直接保留当前理由，对未提供主策略的查询只说明条件。进攻距离解释使用领域配置阈值，无效时差不被视为窗口内。
- a01-rival-explanation/after.json 18 项通过；summary.json 七组查询与语音相关回归通过、源码哈希未变，未修改既有回归断言。A01 仍保留进行中，继续审查呈现层的领域阈值副本与总体一致性。


### A01 攻防与场次风险总结复用领域事实

- rivals.attack_or_defend_summary、attack_defend_tradeoff 与 session.main_risk_summary、risk_severity_followup、risk_escalation_timing 的直接防守条件统一读取领域 defend_state，攻防总结与代价查询读取 attack_state，去除这些行动判断的固定 1.0/1.1/1.2 秒副本。
- 进攻代价更低的后方条件必须是已知 clear，不能把缺失后车时差当成安全；已有当前主策略和具体对手信息仍可作为回答依据。
- 两条场次风险追问在燃油偏紧时复用 FuelAssessment.describe，避免以油箱比例得出的低油量结论搭配不可靠的 fuel_laps_remaining 数值，也移除没有预测依据的“一两圈必然恶化”说法。
- 新增 summary_domain_policy_regression 的 14 项检查覆盖自定义阈值开/关、默认进攻窗口、未知后方与油箱来源回退；a01-summary-policy/summary.json 七组回归通过，测试期间源码哈希未改变。A01 仍需审查其余说明/展望路径后关闭。


### A05 整体交付审计通过；A01 三条对手查询进一步统一

- completion-audit/A05.json 按模型/规划独立权限、观察与关闭无影响、缺失分数不充当零、资产/特征/审批证据绑定以及记录作用域/TTL 汇总 11 组回归与 5,071 快照差分。相关决策/准入/资产/规划源码逐项与差分输入 SHA256 一致，A05 更新为开发验证通过。
- 模型审批记录用合成文件验证绑定，未启用真实模型；规划 evidence 是明确策略引用，不冒称独立签名授权。差分证明权限隔离，不证明驾驶收益，最后综合交付与用户验收仍保留。
- A01 在 capabilities/rivals.py 的 front_gap、rear_gap、attack_outcome_projection 三条查询中改用领域标签及其配置阈值。缺失、负数或 NaN 时差不再宣称直接攻防窗口；进攻预测在后车时差缺失时显示未知，不再用浮点格式化 None 崩溃。固定 DRS 检测规则不在此次修改范围。
- 新增 rival_query_domain_regression 经实际注册查询入口验证，a01-rival-query/summary.json 六组生产回归全部通过且源码哈希未变。其他对手/场次总结查询仍需核对，A01 保持进行中。


### A05 连续录制差分通过；A01 展望修复正式合入

- 工具会话 50553 终态退出 0。a05-contributor-replay/report.json 记录完整 UID16 的 106,103 包、5,071 个规范快照，无解码/状态拒绝；四套引擎独立处理，关闭与观察低/高值消息差分为 0，active 相对关闭有 271 个快照改变输出，20,284 次精简决策往返一致，全部绑定输入未变化，耗时 311.676 秒。
- 这是原始录制流加合成规划极值的权限隔离验证，不代表真实规划推荐优于规则或真实模型质量通过；没有调整默认准入。
- 该回放结束后，按候选前后 SHA256 正式替换 response_composer._tyre_wear_outlook 的独立攻防距离判断，使其复用 assess_domain 的攻防标签，同时保留当前主策略动作语义。a01-outlook-promoted 保存 promotion.json 与六组生产回归结果，新增的永久 27 项查询检查通过。
- A01/A05 整体状态仍需各自交付审计，最终综合回放和安装验证还需覆盖这次合入之后的源码。


### A02 任务预算与取消交付审计通过

- completion-audit/A02.json 按单调 deadline、取消、线程容量、晚到丢弃、后备请求不扩预算和实际问答接入逐项关联源码与验证证据，A02 更新为开发验证通过。
- a02-completion-check/summary.json 六组当前回归全部通过且源码哈希未变；涵盖不配合退出的阻塞后端、实际命令进程等待输出/阻塞 stdin 的取消与回收、超量输出、HTTP/sidecar 上下文传递、能力/用户/父任务预算最小值，以及超时回退核心回答。
- 复用先前 provider_http_cancellation 本地真实链路的七项检查，同时逐项比对相关 task/HTTP/socket/sidecar 源码及测试脚本 SHA256，确认未改变。其证据是本地测试服务器，不是云端服务或真实麦克风验收。
- 不可强杀的第三方 Python 线程继续占用原槽位直到返回，不能冒称所有底层任务都被硬终止；A03 的声音生命周期与 U02 的实机体验仍独立保留。整体目标未完成。


### A01 磨损展望永久回归补齐

- 新增 scripts/tyre_outlook_domain_regression.py，实际通过能力注册入口调用查询，检查默认/自定义攻防阈值、边界、缺失/负距离与领域标签一致；并保留当前主动作提示及轮胎数据不可用行为，共 27 项检查。
- a01-outlook-candidate/permanent.json 在隔离候选模块经真实 resources handler 导入后全部通过，生产 response_composer 尚未替换。脚本本身不属于当前连续回放的核心源码输入集，未破坏该回放绑定。
- 本轮再次轮询工具会话 50553，仍确认运行；未重复启动，未将等待视为差分通过。并行继续 A02 源码审计，确认 TaskContext.wait 的交付前检查、有界工作线程超时后占位及 LlmExplainer 的剩余预算传递；尚未完成工作包整体证据汇总。


### A05 连续录制差分启动，A01 磨损展望阈值候选

- a05-contributor-replay/run.py 对 UID16 完整原始抓包建立四套独立状态存储与 StrategyEngine：关闭、观察低值、观察高值、active 高值。模型均关闭以隔离规划因素；注入完整、有限的合成规划，逐规范快照比较实际消息，并验证四套 DecisionRecord 的精简快照往返。输入清单绑定抓包及全部核心源码；无快照上限，无运行日志复制，不代表真实模型或训练质量验收。
- 本轮启动工具会话 50553，后续两次轮询均确认仍在运行，尚无终态报告。保持同一进程，不修改其绑定源码。
- A01 审查发现 _tyre_wear_outlook 使用独立攻防距离 1.0/1.1，而核心默认阈值为 1.2/1.0，且忽略自定义阈值与无效负距离。a01-outlook-candidate 保存仅将攻防判断复用领域标签的候选与前后源码哈希。
- verification.json 五个端到端查询场景（默认进攻/防守、自定义进攻/防守、负距离）修复前均失败、候选均通过。隔离验证必须替换 resources handler 已导入的函数引用，直接加载候选 response_composer 不会切换注册 handler；已修正验证接入并复跑。候选尚未合入，需等待当前差分回放终态并加入永久回归。


### A05 标准决策记录保留规划准入与输入

- 核查发现过去只有 verbose debug 包含 contributor_admission 和规划输入；标准 DecisionRecord.arbitration 只保留仲裁输出。精简 telemetry-v1 快照在回读后不能解释当时规划的准入来源与时效范围。
- StrategyEngine 现将 planner_inputs 写入既有 arbitration 字典：保存策略版本/模式/证据引用，仅保留已准入贡献参与评分的数值及绑定/有效性。同步贡献绑定本次 snapshot_id、UID、epoch 和源时间戳，标注 snapshot_only；后台贡献保留原始计算快照及 event_key/TTL。明确是仲裁输入记录，不将每项输入冒称实际改变了最终行动。
- 该字段沿用现有 decision-v1 数据契约，并由 decision-content-v1 整体内容哈希覆盖；旧记录缺少新字典仍按原有内容恢复，无需改写历史记录。
- planner_record_regression 检查 disabled/observe/active 三种实际引擎输出、精简快照 roundtrip、无准入输入为空、同步绑定、准入策略影响内容 ID 和篡改拒绝；planning_lane_regression 增加后台绑定/TTL 经精简快照保留检查。a05-planner-record/summary.json 八组相关回归通过且源码哈希未变。
- A05 保持进行中，仍需把整体交付证据完成汇总并核对差分回放覆盖；不以新增字段或本组测试替代最后综合验证。


### A05 规划贡献缺失/非法分数修复

- 先运行 a05-completion-check 六组当前回归全部通过，再审查实际仲裁路径发现旧覆盖缺口：规划 scalar 将缺失字段转为 0，并允许 Infinity/NaN 进入优先级计算。新增 planner_output_quality_regression 的 before.json 有 84/85 项失败，包含准入未拒绝及排序变化/异常，故不能据既有绿灯关闭 A05。
- ContributorPolicy.admit 现校验实际参与仲裁的三项进站支持数值和四项长期规划数值，要求 enabled 严格为 True、字段存在且为有限非布尔数值。诊断字段允许缺失，不据此产生评分权。仲裁入口复用同一校验；进站支持无效则其依赖规划不参与评分，避免缺失数据被当成低风险或无交通代价。
- 新增永久 planner_output_quality_regression 覆盖每项评分字段的缺失、null、NaN、Infinity、bool、字符串和完整有效贡献，共 85 项通过。旧 contributor 回归中的合成规划补全实际评分契约，不放宽原有观察/关闭无影响及 active 有影响断言。
- a05-planner-output/summary.json 七组相关回归全部通过，包含真实进站规划、长期天气历史与后台规划 lane，测试期间源码哈希未变。默认准入权限未调整，A05 仍保持进行中，后续继续核对整体交付条件与最终综合版本。


### A04/A07 时效与预算正式接入，A12 全量导出比较完成

- 六场次导出会话 42925 已正常结束：exit_code=0、duration_s=1664.1648、inputs_unchanged=true。比较会话 26587 也已结束，comparison.json 完整逐行逐字段比较六张表；五张特征表完全一致，83,437 行 labels 唯一变化是 label_rule_version 从 domain-v3 到 domain-v4，标签值、记录 ID 和顺序未改变。
- a12-layout-fixed-export/validation.json 与 impact-conclusion.json 保留新数据验证及差分结论。此处证明输入内容关系，不证明模型真实质量；未重训、重写既有资产来源或启用任何模型。A12 仍需最终治理审计。
- 导出终态后，逐个校验原源码与候选 SHA256，正式接入 runtime_context.py、state_summary_for_llm.py、speech_applicability.py、voice_input.py。查询两条播报入口使用能力定义 freshness_ms；LLM 请求取能力、用户配置与父任务剩余预算的最小限制；控制能力清单复用单一定义；未来/非法时间戳不能形成比赛证据，摘要出口使用校验后时间戳。
- 三个永久回归已加入 scripts：runtime_context_clock_regression、capability_voice_freshness_regression、capability_voice_deadline_regression。a04-a07-clock-policy-promoted/summary.json 中 12 组实际生产模块回归全部通过，测试期间源码哈希未变；promotion.json 保存前后绑定。
- A04/A07 仍保持进行中，需按工作包整体条件完成审计。此前 164 项综合回归、完整回放与安装包是本次修复之前的证据，最终发布验证需覆盖最终源码，不能沿用为最终版本。


### A04 时间戳摘要出口补全验证

- 在隔离运行上下文候选上继续验证发现，LLM 摘要顶层 metadata 仍直接复制未经校验的 source_timestamp_ms。summary-before.json 记录非法值残留与 Infinity/NaN 严格 JSON 序列化失败；该问题不能仅靠隐藏比赛字段解决。
- state_summary_for_llm 候选改为复用 RuntimeContext 已校验的时间戳，避免两套时间戳语义。待合入的 runtime_context_clock_regression.py 覆盖九类无效/未来时间、比赛证据与历史遮蔽、元数据及严格 JSON 和三个新鲜度边界，48 项全部通过。
- a04-context-clock-candidate/related-summary.json 五组既有陪聊、辅助摘要字段、LLM 证据、过期作用域和快照契约回归退出 0。以上仍是隔离候选验证，尚未改动训练导出绑定的生产源码；A04 保持进行中。
- 本轮再次轮询训练导出工具会话 42925，确认仍在运行，继续等待同一进程，不重复启动。


### A13 Session 布局修复后的完整回放终态

- 工具会话 42981 已结束，退出 0；`a13-layout-fixed-replay/process-completion.json` duration_s=1344.9549、reported_passed=true、inputs_unchanged=true、changed_files=[]。
- report.json 主抓包无快照上限，31,726 个规范快照、0 拒绝、31,726 个决定往返验证通过；分场次样本属于同源重叠子集，不叠加成独立覆盖量。保留完整报告及输入哈希清单，临时日志按既有轮转/自动清理策略处理。
- 该证据覆盖已正式接入的 Session 布局修复与投影 v2，尚未包含正在隔离验证的 A07 查询策略和 A04 运行上下文候选；不称为最终交付版本。六场次训练导出会话 42925 本轮末仍确认运行，后续继续等待同一进程。

### A04 运行上下文的未来/非法时间戳边界

- A04 保持进行中。完成核查发现 RuntimeContextDetector 把未来数据年龄 max(...,0) 后认作新鲜；_coerce_int 对 Infinity 抛 OverflowError，bool 被转成时间戳 1。`a04-context-clock-candidate/before.json` 保存实际结果。
- 隔离 runtime_context 候选保留未来数据的负年龄，并归为 future_snapshot/非比赛；时间戳只接受正、有限、整数数值，bool/字符串/小数/无穷大/空值均不可冒充有效时间。现有 0/15000/15001 ms 边界保持一致。
- verification.json 全部 22 项检查通过，含实际 LLM 摘要在未来时间戳下移除领域评估、主策略及比赛历史。候选未接入，后续需与 A07 候选一起完成永久回归和当前入口复验；当前回放/导出绑定源码未动。
- A08 的依据/数值规则验证记录仍有效，但其上游时间质量依赖由此明确列为未关闭；不能凭 A08 单包状态宣称全部解释链的时间质量已完成。

### A06 开发完成条件逐项核对

- A06 状态更新为“开发验证通过”，`completion-audit/A06.json` 关联实际 App.run_live_udp 接入、策略后台开关及七组当前回归。UDP 有界接收与策略解耦，日志/原始录制/网页/最新状态分别有有界异步消费者，覆盖真实入口退出排空和健康记录。
- 观察模型独占有界工作槽，忙时跳过且不重复准备快照，切场/过期隐藏旧诊断；取消未退出的模型仍占有原槽，重启不复制工作者。规划按场次/新圈/轮胎/天气/对手进站等事件刷新，事件变化立即撤销旧贡献，并有周期刷新和 TTL。
- 慢磁盘、慢模型、慢规划、消费者故障和队列过载已由阻塞注入验证；丢弃/合并/失败/仍在运行均明确记录。单调时钟记录接入排队及解码、组帧、策略、输出提交阶段，原始抓包有损时不冒称完整。
- 有限边界：输入复制/准备仍有同步 CPU 成本，已准入 active 模型仍在实时决策内同步执行；不保证硬实时或强制终止任意本地线程。指标止于输出提交，实际发声及游戏压力体验留在 A13/U01/U02，不能由这里的通过替代。

### A08 开发完成条件逐项核对

- A08 状态更新为“开发验证通过”，`completion-audit/A08.json` 保存七组当前检查与源码指纹。引用只可解析到当前绑定 state/strategy 证据，空值/非有限值不可作为有效证据；比赛普通文本包装回退被拒绝，格式/证据错误进入确定性回退。
- 数值声明使用白名单字段、单位、运算和精度，重新计算并由模板渲染；缺 request_id、错误数值/单位/顺序、模板外数字、伪造引用、NaN/Infinity/bool 均有拒绝测试。实际 voice override 在服务端复核，值、文本及请求身份篡改不可通过。
- 过期/切场的策略与比赛历史从非比赛摘要移除，陪聊历史按自身作用保留；快照/决定不匹配拒绝，真实 latest 读取入口取绑定决定。澄清只输出受控问句，不能借状态字段传递任意比赛断言。
- 检查范围是可机器验证的依据、数值、格式、请求和时效绑定，不声称消除全部定性或因果语言幻觉。A07 尚待接入的逐能力时效/deadline 策略另行跟踪；真实供应商和听音体验仍在用户验收范围。

### A07 语音解释预算候选验证

- `a07-query-policy-candidate/deadline-before.json` 实际语音协调入口复现：overall_situation 的能力 deadline=100 ms，用户配置=900 ms，后端仍收到 899 ms，能力策略未生效。
- voice_input 候选对比赛解释取 min(用户配置, 能力 deadline)，已有父任务继续收紧剩余预算；陪聊与复盘独立路由保持原预算定义。移除该文件重复控制能力集合，改为导入注册表派生集合，修复前两个集合逐项相同。
- deadline-verification.json 五项通过：后端实际预算分别为 99/49/28 ms（能力限制、用户更短限制、父任务更短限制）；已取消父任务不请求后端；控制集合引用唯一来源。验证报告保存预算数组副本，避免后续取消测试清空历史观察值。
- related-summary.json 保存隔离候选的语音解释集成、陪聊、语音输入、语音控制、LLM 边界五组原有回归结果。候选尚未接入生产，需连同时效候选及永久回归统一接入后复验；当前回放/导出源码绑定未变。

### A07 完成核对发现查询时效策略未接入

- A07 保持进行中。现有路由、字段、关键词、handler、工具 schema 与播报优先级已由注册表驱动，但 speech_applicability 的查询回答时效仍硬编码 15 秒，未使用 CapabilitySpec.freshness_ms。
- `a07-query-policy-candidate/before.json` 实际复现：将 fuel_status 声明为 100 ms，200 ms 旧快照仍被接受；这不是预期的单一策略入口。
- 同目录 speech_applicability.py 隔离候选在查询提交两条路径读取对应能力 freshness_ms；verification.json 12 项通过，覆盖 100/15000 ms 策略下 50/200/16000 ms 数据。现有能力均为 15000 ms，其边界行为不变。候选尚未接入，正在运行的回放与训练导出输入未动。
- 另查 voice_input._apply_llm_sidecar 仍将 self.llm_timeout_ms 传给请求，没有消费 capability deadline_ms；后续需复现并确定能力预算与用户/父任务预算共同约束，不能仅有工具执行器消费该策略就标 A07 完成。

### A11 开发完成条件逐项核对

- A11 状态更新为“开发验证通过”，`completion-audit/A11.json` 关联当前源码与三组回归逐条检查。session_fact / verified_performance / user_preference 三类数据分离，事实按驾驶员、UID/epoch 查询，所有类型有来源及有效期；偏好只接受明确用户输入，官方圈时差以有效事实 ID 重算且保存证据快照。
- 当前 profile CLI 回归验证保存、查询、修改、撤销偏好，过期不可用、重复不延长 TTL、他人数据隔离；缺数据不造表现，编造差值被拒绝。报告显示读取已有结果，偏好不改写比赛事实。
- `a11-training-cli-followup/report.json` 五项实际命令入口检查通过：查看草稿→启用→重复启用不变→后续圈复盘→CLI 读取同一持久观测。使用明确 synthetic fixture；原有 training_plans 回归还覆盖跨 UID/epoch/条件拒绝、过期草稿不能启用及工作流恢复不重复。
- 该工作包达到记忆来源、有效期、作用域和训练草稿/后续表现可关联的开发条件。真实训练收益与驾驶体验仍由 U04 验收，不将观测差值称为训练因果。用户本地真实档案未修改。

### A10 开发完成条件逐项核对

- A10 状态更新为“开发验证通过”，依据 `completion-audit/A10.json`。这是该工作包的完成条件核对，不是由回归数量直接推导整体完成。
- 真实场次全流程：当前生产 CLI 对原始抓包执行七步复盘，投影 v2、官方圈索引、18 项区段比较、训练草稿及报告来源绑定均有实际输出；重复任务保持 attempts=7。
- 恢复与副作用：当前 10 组对应回归证据覆盖实际子进程在 SQLite 已提交、工作流未检查点时退出，恢复后不重复记忆/草稿，也不延长已有条目的有效期；持久模型/工具次数和期限不因恢复而重置，完成结果可在运行预算过期后读取，恢复/读取重新核对所有者。
- 受限工具与失败追溯：只读工具拒绝控制动作、未知能力、过期/越范围/超次数请求；取消和超时不提交晚到结果；CLI 区分调用失败与历史任务已完成，失败和用量未知项留有记录。源码指纹与逐条 checks 保存于审计文件。
- A10 的生产流程与开发恢复验证完成；真实驾驶训练价值、听音体验和用户最终 U01–U04 不在此代填。A01–A09/A11–A13 仍按各自完成条件核查。

### A03/A08/A09/A13 本地监听与原生导出缺口复验完成

- 核查旧审批记录，历史拒绝原因为 usage limit。本轮经正常 require_escalated 审批获准，未绕过审批：先两项本机网页/取消传播验证通过，再完成 21 项此前受监听权限限制的回归。`a13-layout-fixed-listeners/summary.json` 21 passed，process-completion.json 退出 0、输入不变。
- `a13-layout-fixed-native-export/summary.json` 原生 say 文件导出通过：WAV 单声道 16 kHz/16 bit、帧数大于零、PCM 流分块及总字节非零。测试不播放音频，不代表实际扬声器/麦克风或 AEC 通过；旧受限环境空音频的底层原因未单独证明。
- `a13-layout-fixed-regression-coverage/report.json` 按脚本名去重核对当前发现清单：164 组（142 常规 + 21 监听 + 1 原生导出），全部通过，无缺项；唯一单独运行的是 phase1 全量回放。当前源码与常规回归绑定哈希一致。此核对覆盖开发回归清单，不自动证明 A01–A13 全部产品完成条件。
- 旧“监听/原生文件导出仍未验证”的当前限制由本节替代；用户验收文档已同步，真实供应商、听音和 AEC 边界保留。全量回放 42981 与六场次导出 42925 本轮末均确认仍运行；差分脚本待导出终态后执行。

### A12/A13 修复版本综合证据与训练影响核查

- `a13-layout-fixed-integrated/summary.json` 142 组选定回归通过，process-completion.json 确认退出 0 且绑定输入未变；仍有明确排除的监听/原生 say 项及单独完整回放，不能称全部套件通过。
- `a13-layout-fixed-wheel/summary.json` 11 项干净构建/安装检查通过，wheel SHA256 d77f1ad1512d11a03db88d54de9d02b0f5752293cfc3d9b3676f892d1614dc26；验证期间核心/网页输入不变。范围仍是当前本机、离线安装及 socketpair，不包含真实服务和听音。
- 修复版本不限快照数完整回放已启动，会话 42981，目录 `a13-layout-fixed-replay/`；旧会话 63047 已有明确中止终态，此次因已接入实质修复重新验证。写入本条时新会话仍在运行，临时日志保留限制继续生效。
- `a12-session-layout-impact/report.json` 全六场次独立线字节核查共 18,477 个 Session 包，正确位置管制状态与旧导出时未知回退 NONE 的归一化结果差异为 0；当前 marshal_zones/network_game 无解码器之外直接消费者。此证据仅限该字段及这些输入，不代替完整特征/标签差分。
- 已启动全六场次当前版本重新导出，工具会话 42925，目录 `a12-layout-fixed-export/`。input-manifest.json 绑定配置、元数据、原始抓包、核心及导出脚本；待终态后执行表完整性和逐表旧新比较，再决定是否需要重新训练，不自动宣称旧模型评估适用于修复版本。

### A04/A10 Session 布局正式接入与生产 CLI 验证

- 旧回放会话 63047 经工具确认仍在运行后，因已证实 Session 布局缺陷主动中止；工具退出 130，子进程 stderr 亦为 KeyboardInterrupt，`a13-domain-v4-replay/interrupted.json` 记录原因。此次未完成、不算通过，不是因观察超时而重复启动。
- 对照原回放输入哈希与候选边界报告哈希后，正式接入 pdu_decoder.py / review_capture.py；promotion.json 保存接入指纹。新增永久 session_packet_layout_regression，独立线偏移覆盖四种管制值、marshal zone、天气预报首项与尾部字段，以及全部截断长度、v1 缓存和旧任务冲突。
- `a04-session-layout-promoted/summary.json` 六组通过；后续增强字段哨兵检查的 `a04-session-layout-final-boundary/summary.json` 通过。README 明确 v2 投影迁移需新目录和新任务 ID，保留旧证据，不能只改版本标识。
- `a10-layout-fixed-production/verification.json`：未经隔离替换的生产 CLI 从原始抓包完成 106,103 包、5,071 快照的七步流程；18 项区段比较、训练草稿、v2 投影哈希绑定通过；同 task-id 再次运行后 attempts 仍为 7。该结果不等于真实训练价值验收。
- 当前综合回归已启动，工具会话 33179，输出 `a13-layout-fixed-integrated/`；本条写入时仍在运行。正式接入改变了真实管制和 marshal zone 字段，旧版本全量回放、导出/模型数据及安装包证据均需核对适用性，不能自动沿用为当前语义验证。A01–A13 整体尚未完成，U01–U04 保留。

### A04/A10 解码候选边界与缓存版本验证

- Session 候选按 EA F1 25 v3 规范拒绝非 753 字节数据报；`a04-session-layout-candidate/boundary-report.json` 九项通过，包括全部 724 种头部完整但正文截断长度、超长包、有符号 trackId/zoneFlag、独立线位置的安全车/联网状态。
- 复盘候选投影升为 review-projection-v2，旧 v1 manifest 明确版本冲突且不修改旧投影/manifest；旧任务绑定同样冲突并保持原记录。迁移方式是新输出目录及新任务 ID，不覆写已有历史证据。
- `related-summary.json` 六组相关回归通过。首次 durable_capture 回归的失败来自隔离导入未设置 asurada.review_capture 包属性；修正验证加载器后测试原样通过，失败日志保留为 harness-before-*，未更改生产或回归断言。
- `review-boundary-verification.json` 使用带完整长度校验的候选重新运行原始真实抓包并绑定 v2 投影：七步完成、18 项区段比较、训练草稿存在、重试结果相同及 attempts=7。该候选 pdu_decoder SHA256 为 7e0f0a042f635eea0f2c15a1d690f0c0c01f2dcfd6c88947783d75a2883025ec；review_capture 候选哈希在 boundary-report.json。
- 尚未正式接入；回放会话 63047 本轮末再次确认运行。后续接入须保留永久回归，并核查最新生产哈希没有漂移，重新验证最终集成版本。A04/A10/A13 保持进行中。

### A04/A10 Session 包布局缺口与隔离修复

- 当前 domain-v4 真实场次复盘 `a10-domain-v4-real-review/` 虽完成七步，但区段比较从旧证据 18 项变为 0；5,071 个快照中 5,061 个管制状态未知。此结果暴露了底层解码错误，不能作为 A10 完成证据。
- 对照 EA 官方 F1 25 v3 PDF 第 4 页（https://forums.ea.com/t5/s/tghpe58374/attachments/tghpe58374/f1-games-game-info-hub-en/61/4/Data%20Output%20from%20F1%2025%20v3.pdf），Session 标量前缀为 19 字节，随后是 21 个五字节 marshal zone，之后才是 safetyCarStatus/networkGame；旧代码把两者放进 21 字节前缀，错误读取数组字节，marshal zones 起点也偏移两字节。规范中的 trackId 为有符号 int8，候选同时按此处理。
- `a04-session-layout-candidate/report.json` 实际核对原始抓包 1,033 个 Session 包：正确线位置全为 0，旧解码 1,031 个为 187、2 个为 0；隔离候选全部正确。四种状态及独立写入 zone_start/zone_flag/networkGame 断言通过。
- 同目录 `review-verification.json`：候选仅替换当前进程的解码器，真实抓包七步复盘恢复 18 项比较及训练草稿，重复调用结果相同、attempts 仍为 7。未修改生产源码，未改变正在运行的回放输入。
- 后续必须完成截断包/有符号赛道/既有包构造回归、投影缓存版本迁移与正式接入，再重建最终集成证据。当前 141 组通过未覆盖正确线布局，不证明此缺口不存在。回放工具会话 63047 在本轮末仍确认运行；不是因等待超时而重新启动。

### A13 domain-v4 当前版本综合验证

- `a13-domain-v4-integrated/summary.json`：141 组选定回归通过，0 失败、0 跳过；process-completion.json 确认退出 0，绑定源码未变。覆盖最新能力播报优先级、未知管制语义及复盘异常修复。selection.json 明列 21 项监听权限、1 项原生 say 空音频及单独完整回放的排除原因；不能据此称全部套件通过。
- `a13-domain-v4-wheel/summary.json`：全新临时源目录构建及独立 venv 离线安装，11 项检查通过，核心/网页输入哈希未变。实际运行 demo、复盘 CLI 场景、安装后的核心与网页协议组件；wheel SHA256 为 1002eecdb16b76c739d3c052b87679cdb3593568917be261398e06024251de53。仅本机 Python/macOS 环境，不代表监听、云端服务或实机音频已通过。
- 新的不限快照回放已启动，工具会话 63047，输出目录 `a13-domain-v4-replay/`。写入本条时确认启动且仍在运行，尚无完成结果；使用两份临时归档及当前文件的既有容量限制。当前磁盘可用约 9.6 GiB。必须等待该会话终态，不能以旧回放报告代替或另起重复任务。
- 用户验收文档修正了“旧全量回放仍待结束”的过时描述，明确旧版本已通过、当前版本需要重新核验；U01–U04 状态保持待验收。

### A10/A11 复盘管制状态边界核对

- 核查确认复盘已有未知/受管制圈排除规则；但直接输入 JSON 对象形式的 safety_car 会在条件集合计算触发 TypeError，导致整份分析失败。实际复现后，区段复盘接入共用 normalize_race_control，非法值归为未知，保留按整圈排除的行为。
- 新回归覆盖 None、UNKNOWN、bool、数值、对象、数组及 FULL/VSC/FORMATION，均不生成区段比较或训练重点；单个未知样本排除所在圈，同时其他有效圈继续分析，不满足三圈时不生成训练重点。
- `a10-review-race-control/summary.json` 四组通过（区段复盘、管制质量、抓包投影、训练计划），source-manifest.json 记录源码哈希和修复前实际异常。属于离线开发验证，未完成全量综合复核或 U01–U04 用户验收。

### A01/A04 赛道管制未知值统一

- 完成条件核查发现两种相反的错误：组帧器将 None/99/非法文本转为 NONE，领域评估将 None/UNKNOWN/bool 当作 controlled，并输出“None 阶段”等确定性文案。`a01-race-control-audit/report.json` 保留输入、实际结果和旧源码哈希。
- 新 race_control 共用状态映射，仅接受有效枚举；包级状态仅接受真正的整数，不接受 bool/浮点/数字字符串。未知值统一为 None，领域 race_state 为 unavailable，不生成 SAFETY_CAR 候选，也不触发进站/长期规划/通用解释中的“存在管制”分支。有效 NONE/FULL/VSC/FORMATION 继续分别表示无管制与有效管制阶段。
- 查询/天气/总体展示明确数据不可用；规范解码、CSV 缺失字段、待机展示和非比赛 LLM 遮罩不再补造 NONE。领域规则升为 domain-v4，旧评估缓存按版本重算；未知值通过快照序列化往返保留。
- `a01-race-control-final/summary.json` 九组全部通过：新管制质量、统一事实、快照、包输入、语义、LLM、陪聊、长期规划历史及网页协议。新用例覆盖非法/缺失输入、有效四态、候选不误报、CSV 显式值与缺失、待机和往返。验证后仅清理未使用导入，未再改业务语义。
- 此变更影响未知管制输入的领域语义，旧全量回放与安装包不自动覆盖新版本；后续综合核对需绑定新哈希。A01/A04 总体完成仍未据此宣告，最终 U01–U04 保留。

### 当前综合回归终态与 A07 优先级接入

- `a13-integrated-current-worktree/` 会话 35338 已结束，选取的 139 组全部通过，无失败/跳过，绑定核心/脚本/网页/pyproject 输入哈希未变。selection.json 明列排除的 21 组既有监听权限项、1 组原生 say 空音频及独立全量回放；排除不等于通过，不能称全部测试套件全绿。
- 综合运行期间新增外部探针发现 speech_priority 仍仅存在于注册定义，实际查询输入和播放任务均写死 95；声明 77 时两者仍为 95。`a07-speech-policy-before/report.json` 保留实证，原始源码未在综合运行中修改。
- 综合终态后接入 capability_speech_priority，查询输入、普通回答、repeat_last 与辅助控制回答从注册表读取优先级，保留未知类型的原 95 回退。当前已有能力声明值不变，没有调整既有默认优先顺序。
- `a07-speech-policy-fixed/summary.json` 五组通过。新增实际 ConsoleVoiceOutput 到假播放后端检查自定义查询优先级与重复播报自身优先级，既有控制、队列调度、语音与能力扩展回归保持通过。139 组结果绑定该修复前版本，不声称已覆盖这次修改。
- 其余工作包完成条件、监听/原生音频环境项及最终版本集成证据仍需继续核对，U01–U04 保持待用户验收。

### A09/A13 网页依赖干净安装验证

- 官方 PyPI 的 websockets 15.0.1 下载在默认受限网络下未取得分发包；经工具批准的包下载成功。批准仅用于依赖下载，不等于许可本地监听或真实服务测试。wheel 及 SHA 位于 `a13-dashboard-dependency/`。
- `a13-dashboard-wheel/summary.json` 十一项通过：当前核心从干净临时源码构建，在全新虚拟环境离线安装 asurada[dashboard]，由声明实际解析安装 websockets==15.0.1；原有资产、demo、工具模块和复盘档案 CLI 场景保持通过。
- 网页 Python 源码复制到临时目录，导入时核对 asurada 来自新安装环境而非工作区源码；实际 ProtocolStateClient 使用安装后的依赖，通过 socketpair 发送状态并回收 worker。网页源码和核心构建输入哈希前后不变。
- 最新核心 wheel SHA256 为 c0703f5b3e9ccc2429394c3908aa024122dd5d47a238633b8b385b82c393c848。网页仍以仓库脚本交付，并未冒称其静态资源已打进核心 wheel；没有部署。验证范围为当前 macOS ARM64/Python 3.9 环境，不代表其他目标环境或浏览器/监听验收。
- 此前“新网页依赖未做干净安装”的限制由本节替代。A01–A13 总体完成条件仍需逐项核查，当前版本整体回归与监听环境项继续，U01–U04 原样保留。

### A09 异常帧与服务生命周期闭合

- 新异常帧回归发现 Sans-I/O 适配层丢弃文本事件时漏校验 UTF-8；`a09-error-frames-before/` 保留失败。补充跨分片增量 UTF-8 解码，非法文本发送 1007 并回收连接，合法跨片字符与其间 Ping 保持有效。未掩码、分片控制帧、保留位、未知 opcode、单字节 Close、损坏 Close 原因均由协议层给出对应错误响应。
- HTTP 入口改用 DashboardHttpServer，统一持有最多 16 个活动连接和 worker；服务停止后拒绝新派发，shutdown 中断现有网络等待，共享一秒收尾预算后返回实际线程状态。VoiceMeterSocketCache 增加 stop/close，失败 bind 关闭已创建 socket；main 启动与退出路径用 finally 清理 WebSocket 和音量计资源。
- `a09-lifecycle-final/summary.json` 四组全部通过。真实 socketpair 覆盖正常 HTTP 响应、容量拒绝、在途请求关闭与 worker 清空、音量计接收线程结束；注入启动失败验证已启动服务清理及失败 socket 关闭。异常帧与新 WebSocket 慢客户端测试保持通过。
- 这些验证不打开监听端口，仍不证明真实浏览器、TCP accept 或实机闭环。静态文件读取和 feed 文件读取仍为普通本地文件操作，关闭预算不代表能强制打断任意内核磁盘阻塞。新依赖的干净安装与整体集成核对继续推进，U01–U04 保留。

### A09 成熟协议层与有界收发接入

- 生产 DashboardWebSocketServer 改用 websockets 15.0.1 的 ServerProtocol 处理增量握手与控制帧。握手总预算 0.5 秒、请求累计上限 16 KiB；ProtocolStateClient 的单线程独占协议实例，非阻塞 socket/select 同时处理接收与发送，保留一条待发最新状态，不再仅发送不读取。
- 客户端 Ping/Pong、Close 由协议层响应；普通入站消息作为只读订阅的非命令数据丢弃，库的入站消息上限 4 KiB。发送缓冲上限、0.5 秒发送/关闭预算、2 MiB 展示 payload 上限显式执行；发送未完成不增加 sent，超大广播跳过并计入健康计数，不能使后续广播线程退出。
- `a09-protocol-final/summary.json` 两组通过。新增真实 socketpair 经当前生产握手与 ProtocolStateClient 验证原三项失败全部修复，并验证慢 socket 写入阻塞时另一连接正常、待发队列合并、超时回收、未完成发送计数、关闭应答与 worker 回收。既有 dashboard_transport 用假连接验证旧发送工具的行为，不借它代替新循环覆盖。
- pyproject 增加 dashboard 可选依赖并固定 websockets==15.0.1，当前虚拟环境已具备该版本；README 说明安装和运行方式。源文件哈希记录在证据目录。依赖在全新安装环境的解析尚待复验。
- 当前没有绑定监听端口或启动真实浏览器，不能称 TCP listener/浏览器验收通过。服务端关闭竞态、HTTP 服务整体收尾与控制帧异常组合仍需继续检查，A09/A13 尚未整体完成。U03 保留，iOS/ESP 排除。

### A09 WebSocket 控制与握手缺口实证

- 重新读取 server.py 与 ws_client.py：LatestStateClient 仅发送不接收，_handshake 只读取一次 recv。新增 dashboard_protocol_regression 用实际已连接 socketpair 经过当前握手与发送类验证，不绑定监听端口、不启动浏览器。
- `a09-protocol-before/summary.json` 明确失败：正常握手、升级响应、状态发送三项通过；Ping/Pong、Close 应答、分片握手三项失败。这是实现缺口，不能归类为环境监听限制，也不能被旧 dashboard_websocket 只检查正常握手/发送的通过覆盖。
- 已核对 RFC 6455 第 4.2/5.5 节与 websockets 15.0.1 官方线程服务文档，并核对项目虚拟环境已有该版本。下一步使用成熟协议实现处理握手和控制帧，同时保留本项目每客户端最新状态队列、容量上限、发送取消与健康数据；必须验证迁移后这些边界没有退化。
- 当前尚未替换生产协议实现。还需依赖声明、真实协议回归、慢消费者/关闭验证和受环境影响的监听集成复验；此开发缺口不留给 U03 代替。来源和源码哈希在同目录记录。

### A07/A11 正式接入、回放终态与安装验证

- 全量回放 87984 已正常结束：退出 0，用时 1196.47 秒，reported_passed=true，488 个绑定输入哈希未变。`a13-final-source-replay/` 主抓包 31,726 快照、0 拒绝及对应决定往返全部通过，四个重叠分场次样本均无帧数上限并通过。此证据绑定本次正式接入前版本，不证明候选代码已参与全量回放或真实战术真值。
- 终态核对后，再次检查联合候选 SHA、四个待替换原文件 SHA 及新目标不存在，正式接入七个文件：能力定义/交互/快速识别、训练记忆/复盘档案、两个常规回归脚本。promotion.json 记录实际目标文件哈希，没有覆盖期间其他改动。
- `a07-a11-promoted/summary.json` 正式工作区十组全部通过，无失败/跳过：新能力定义、新复盘档案、训练记忆、能力执行器、分析 Agent、持久分析、复盘副作用崩溃恢复、快速识别、语义、语音控制。此前候选未接入的历史限制由本节替代。
- 新增 [本地复盘档案说明](ASURADA_REVIEW_PROFILE_CN.md)，README 说明真实模块入口与能力元数据的扩展方式。详略设置只消费于复盘展示，局部 driver-id 不作为远程身份认证；观测差值不升级为训练因果效果。
- `a13-promoted-wheel/summary.json` 九项通过：干净临时源码构建、全新虚拟环境离线安装、全部源码和资产可用、demo 与日志配置、新入口 help，以及安装后真实 CLI 的完整 19 个偏好/观测场景。构建输入前后哈希未变；新 wheel SHA256 为 5717e91e98aa8988eac0316286f663accedae2c35bb9330016cc892d72bcbc10。没有部署、真实云端/音频/监听或用户档案写入。
- A01–A13 总体完成仍未证明：其他工作包的生产入口与退出条件核查、受环境限制的集成项及最终版本综合覆盖继续推进。U01–U04 保持待用户实机验收；iOS 暂缓、ESP 适配排除。

### A07/A11 联合候选与常规回归准备

- 新增可随项目脚本集运行的 review_profile_regression.py，通过真实 CLI 子进程复用 19 项偏好/观测场景；新增使用说明覆盖命令、有效期、局部档案身份及自定义记忆数据库边界。
- 将 A07 三个源码候选与 A11 两个源码候选合并到同一个临时包。`a07-a11-combined-candidate/integration-summary.json` 五组通过：能力扩展入口、复盘档案入口、既有训练记忆、能力执行器、分析 Agent。核对实际导入路径，资源由工作区提供，不启动真实播放。
- candidate-manifest.json 绑定联合候选源码、两个常规回归脚本与使用说明，便于正式接入前再次核对。主源码仍未变；全量回放 87984 最新工具确认运行中，已约 19 分钟，无终态前不覆盖其绑定输入。
- 正式接入、工作区回归、发布包复验仍待完成，联合隔离通过不作为 A07/A11/A13 完成结论。U01–U04 保留。

### A11 圈时观测表现入口候选 v2

- `a11-profile-candidate-v2/` 增加 record-performance --task-id。读取明确归属驾驶员的 completed 复盘，按 UID/epoch/赛道分组取最近至多三圈的首尾官方圈时；两圈以下返回 insufficient_laps，不生成表现记录。
- 写入前通过该任务 persist_session_facts 的 memory_ids、同驾驶员与作用域查询、事实值和原数据 SHA 唯一匹配两条未到期事实，再调用 TrainingMemory 的 official_lap_delta_v1 算术验证。记录保留原始事实快照、圈号、UID/epoch、复盘 ID、SHA、30 天有效期，并明确 observed_lap_delta_not_causal_effect；不推断训练收益或驾驶动作原因。
- show 只读取当前任务/原数据 SHA 匹配且未到期的 verified_observations。记忆写入使用稳定的复盘与作用域身份，重试沿用原记录与有效期；不修改已完成任务。一个多作用域任务的写入仍为逐条幂等，不宣称跨记录原子事务。
- 实际 CLI 子进程/SQLite 验证现为 19 项通过，新增保存后展示、证据绑定、重复记录不变、异主写入拒绝、过期事实不能重新验证、空复盘不造表现。manifest.json 绑定最新两个源码与测试；原始用户档案未修改。
- 此项仍为候选，须与 A07 候选在当前全量回放终态后正式接入、加入常规回归和使用说明，再复验安装包。不能将隔离通过等同于 A11/A13 已完成。

### A11 显式偏好与复盘展示候选

- `a11-profile-candidate/` 增加 review_profile 模块命令：set-detail brief/detailed、preferences、revoke-detail、show --task-id。要求显式本地 driver-id 与已有复盘数据库；它是本地档案选择，不是远程认证。show 复用 completed_review 的驾驶员所有权及完成状态检查。
- TrainingMemory 的专用设置入口仅接受受控详略值，来源固定为显式用户输入。有效期为有限正数；当前有效值的相同请求不刷新创建时间或延长到期，显式改变值或已到期后重新设置可创建新的有效期。撤销仅删除本档案的该偏好，不动事实或表现记录。
- 实际展示读取未到期偏好，默认详细。简略输出保留原比较、训练草稿与观测、来源 SHA、限制说明及完整持久报告定位；不会改写 completed 任务或重新执行复盘。这一入口不改变语音链的详略设置，也不把偏好当作比赛事实。
- 候选包中实际 CLI 子进程与 SQLite 验证 13 项通过，含设置/更新/撤销、重复撤销、相同设置不延长 TTL、过期不可见、不同档案隔离、异主复盘读取拒绝、简略证据保留及完成任务不变。无真实用户档案被修改；manifest.json 绑定原始文件与候选哈希。
- 当前仍为隔离候选，待回放 87984 终态后接入。已验证表现的生产生成与读取仍需补齐，不能凭偏好入口候选标记 A11 完成。

### A11 生产记忆入口复核

- 重新检查 TrainingMemory、session_review_workflow、TrainingPlanStore、ReviewVoiceService 和分析 Agent/回答链。生产复盘仅写入 session_fact；verified_performance 的 put/query 目前仅出现在回归用例，user_preference 仅有存储校验，未发现生产编辑/撤销与消费入口。源文件哈希与结论见 `a11-entrypoint-audit/audit.json`。三种类型存在不等于三种记忆已用于产品。
- 后续开发必须补齐：显式本地驾驶员档案的偏好设置/读取/撤销入口；复盘依据有效圈事实生成、保存并读取已核验的观测差值；结果消费时保留来源、作用域、到期信息并区分观测与因果。不能由模型猜测偏好，也不能把训练草稿升级为已验证能力。
- 验证需经实际 CLI/复盘报告入口，覆盖不同驾驶员隔离、到期不可用、偏好更新与撤销、任务恢复不重复或延长记忆，以及无有效圈数据不生成表现结论。既有训练计划启用与后续圈关联保留，实际训练价值仍交由 U04。
- 这是明确的开发缺口，不归类为监听环境限制或最终实机验收项。当前回放绑定源码继续保持不变，能力注册候选也尚待正式接入。

### A07 快速别名与交互候选 v2

- 补充可迁入常规脚本集的 capability_interaction_definition_regression，验证新增定义经实际 recognize_turn、CapabilityRegistry 权限判断及交互路由生效，覆盖字段副本、显式别名覆盖、特定别名优先级。候选包的 integration-summary.json 现为六组全部通过；三个原始源码哈希仍与候选准备时相同，等待回放终态后正式接入。

- `a07-interaction-registry-candidate-v2/` 在前述交互元数据候选上，把 KeywordFastIntentASR 的 35 组默认别名迁入同一 CapabilitySpec。fast_alias_order 显式保留旧表的同分优先顺序；构造识别器时从当前注册表生成别名，新增注册项无需再编辑 ASR 的默认表。复杂上下文语义推断仍保留专用逻辑，不把它声称为已消除的业务分支。
- 62 个隔离检查通过，其中 all_alias_matches 覆盖 278 条原句、带前后缀句子和歧义句，与旧匹配结果逐项一致；真实 recognize_turn 验证新增注册项可识别。保留原 56 个交互场景对照、字段所有权及工具目录一致性检查。
- 已有 fast_intent、semantic_voice、voice_control、capability_executor、analysis_agent 五组回归在候选包下全部通过。脚本以规范化绝对路径核对实际导入位置，使用工作区资产与假/Null 播放器；不是主源码接入或声音端到端验收。初次验证脚本的临时路径字符串断言受 /var 与 /private/var 别名影响，改为 resolve 后通过，未修改生产行为以规避失败。
- verified-candidate-manifest.json 绑定三个候选源码和验证脚本。全量回放 87984 仍由工具确认运行，主源码未覆盖；须在其终态后接入候选并执行正式工作区验证。A07/A13 与最终 U01–U04 仍未整体完成。

### A07 交互元数据集中定义候选

- 当前实现仍在 interaction.py 单独维护路由名称、请求字段与默认问句，能力注册表并未覆盖这些扩展点。本次按原行为提取到 CapabilitySpec 的 route_handler、requested_fields、default_query_text；交互入口改为消费同一能力定义。requested_fields 是信息投影，不冒充“所有字段必须存在”的 required_facts 门禁。
- 候选及可重复准备/验证脚本位于 `output/architecture-implementation/a07-interaction-registry-candidate/`。54 个现有交互能力，加系统广播与未知能力回退共 56 个场景，候选结果与原实现逐项一致。另验证仅新增注册项即可改变路由/字段/问句、调用者不能修改注册的字段元组、工具目录读取同一元数据，共 59 个检查通过。
- 测试在独立临时包副本执行，两个源码候选尚未覆盖主工作区。当前全量回放 87984 继续使用其原始绑定版本；须取得终态并核对源哈希后再接入和运行正式入口回归。此项尚不代表语义关键词、场次模式策略及整个 A07 已完成。

### 当前版本综合验收与历史记录解释

- 本文“当前进展”保留历次过程证据，同一事项以上方较新的已核对终态为准。旧节中的“候选未接入”“运行中”“依赖未安装”不能作为当前事实；也不能仅因旧问题已修复就推断整个工作包完成。表格开发完成条件仍是 A01–A13 的核对标准。
- 已开始 `output/architecture-implementation/a13-final-source-replay/run.py`，执行主抓包和四个重叠分场次样本的无帧数限制回放。当前工具会话为 87984，终态以 process-completion.json 和 report.json 为准；此时尚未通过，不得重复启动。
- 输入绑定在原始采集清单基础上补入当前全部核心 Python 源码与脚本，覆盖最近新增的工具契约、日志配置和云端 TTS 文件；结束时重新核对哈希。回放执行范围不等于每个被绑定模块均被调用，云端与声音链仍用各自的测试证据。
- 回放临时日志最多保留两份归档及当前文件，结束后自动清理。已另行清除六个可丢弃临时日志，共 237,354 字节，其中四个与正式 stdout/stderr 副本逐字节相同；原始抓包、训练导出、正式验收证据保留。
- 开发侧剩余核对包括：当前版本全量回放终态、受监听权限影响的集成测试、原生 TTS 空音频定位，以及各工作包生产入口与原始退出条件的逐项核查。U01–U04 保持待用户实机验收，不能用这些环境限制替代尚未完成的开发工作。iOS 暂缓，ESP 适配排除。

### A13 当前安装包与实时 ASR 依赖验证（最新）

- 从当前源码和 setup.py 明确选择的资产创建干净临时构建目录，离线构建 wheel，再装入全新 Python 虚拟环境，运行安装后的 CLI help、带归档配置的 demo、新增模块导入和资产验证。`a13-current-wheel/summary.json` 七项通过，所有源文件进入 wheel，资产哈希与 24 份模型报告路径验证通过；构建前后输入哈希不变。
- 当前 wheel 为 `a13-current-wheel/asurada-0.1.0-py3-none-any.whl`，SHA-256 `4ad011786651fae47e30dc14711feef6aa98f0442c11d027a7f3db34cf73db75`。这不是发布/部署，也不代替可选模型推理、HTTP listener 或实际语音验证。
- 项目声明的 websocket-client 1.8.0 已从官方 PyPI 下载为本地 wheel。首次受限下载未获得分发包；经工具批准的网络下载成功。随后使用本地 wheel 和 `asurada[realtime-asr]` 在全新 Python 3.9.6 环境离线解析安装，版本、WebSocketApp/create_connection API 与安装包中的 ASR 模块导入均通过，见 realtime-asr-verification.json。
- 同一依赖已离线安装到项目 `.venv`，不再只是 metadata 声明；`a13-installed-realtime-asr/` 复测既有批量/实时 ASR 适配及取消。未向云端提交音频或建立真实 WebSocket；麦克风、真实后端和用户听音仍待验收。

### A03 云端 PCM 格式一致性

- 发现 Doubao renderer 可配置上游 MP3/WAV/Opus，却始终对外声明 pcm_s16le，缓冲接口也直接按 PCM 包装 WAV。当前没有对应解码器；现改为上游格式非 pcm 时在网络调用前明确拒绝，并在 README 写明支持范围。
- 跨 SSE 分片不足一个 16 位采样值的单字节暂存并与下一片拼接；输出帧按两字节对齐，结束仍余半个采样值时报 tts_pcm_sample_truncated，不能返回完成。所有完整 PCM 字节保留，无降采样或丢片。
- `a03-cloud-pcm-contract/summary.json` 四组通过。新测试覆盖三种不支持格式在网络前拒绝、1/3/697 字节等不齐分片重组、奇数目标帧长输出对齐、实际 WAV 包装与原始 PCM 完全一致，以及流式/缓冲两入口拒绝末尾半个采样值；原有成功结束、真实 socketpair 中断/取消和客户端流完整性保持通过。
- 此项不证明真实云端声音或本机扬声器验收。整体开发与最终用户验收仍分开，iOS/ESP 排除。

### A03 云端 SSE 完成语义闭合（最新）

- 已通过真实浏览器读取[火山引擎 SSE 官方文档](https://docs.volcengine.com/docs/6561/1598757?lang=zh)第 3.4 节及错误码表（页面更新时间 2026.05.25）：事件 152 为会话结束，20000000 为合成成功结束码，151/153 分别为取消/失败。来源记录见 `a03-cloud-tts-completion/protocol-source.json`。
- Doubao SSE renderer 现在要求收到 152 + 20000000 且实际音频非空。EOF 未见结束事件报 stream_incomplete，151/153 明确失败；不再把部分音频收集完视为完整合成。JSON 事件要求对象，损坏 UTF-8 严格拒绝，移除无效的 JSON 重试分支。旧本地 HTTP fixture 的结束 code=0 修正为文档成功码，未扩大兼容接受范围。
- `a03-cloud-tts-completion/summary.json` 四组通过：缓冲与流式入口分别覆盖正常结束、缺失结束、空成功、取消、失败、错误结束码、非对象、损坏编码/JSON；socketpair 真实 HTTP/SSE 验证完整 HTTP body 但缺业务结束事件仍拒绝，底层连接关闭，原有主动取消及提前关闭保持通过；服务请求预算与客户端流完整性回归保持通过。
- 这不证明供应商真实服务、实际听音或完整 listener 部署通过。边收边播已经交付的部分声音无法撤回；此修复保证后续终态不冒充成功。原生 say 空音频和监听权限项仍保留，整体继续，iOS/ESP 排除。

### A13 当前工作区可运行契约综合核对

- `a13-current-runnable-contracts/selection.json` 明确选取 132 组，排除先前确认的 21 组监听权限失败、1 组原生 say 空音频，以及独立执行的全量回放；排除不是通过或已完成。主源码与测试输入哈希在本次执行前后均不变。
- 首轮综合结果 131 通过、1 失败、0 跳过，原始失败报告保留。失败是 tts_process_cancellation_regression 在两秒准备窗口内未观察到测试 converter 的 PID，尚未进入取消断言；该次失败未记录 worker 原因，不能断言底层根因已确定。
- 为测试增加启动失败诊断、失败路径取消和线程回收后，单独诊断复跑通过。随后把测试准备窗口改为 8 秒/任务预算 10 秒，并独立记录 fixture_startup_ms 和 cancellation_ms，取消后仍要求两秒内返回且子进程已回收。没有修改生产超时/取消行为；此调整针对测试准备阶段，不将初次失败抹去。
- `a02-tts-cancel-readiness/` 核对测试修订后的进程取消、服务请求取消及播放取消，具体结果以该 summary.json 为准。监听环境与原生 TTS 验证仍待完成，不能称整个 contracts suite 全绿。

### A07/A10/A13 正式接入与回放终态（最新）

- 无上限回放 61934 已结束，退出 0，用时 1342.16 秒，reported_passed=true，全部绑定输入哈希不变。证据 `a13-bounded-log-full-replay/process-completion.json` 与 report.json。主抓包 31,726 个快照、0 拒绝、31,726 次决定往返校验；四个分场次样本分别 5163/4879/3166/5071 帧全部通过，均无帧数上限。样本与主抓包重叠，不相加为独立覆盖；不证明真实声音/设备或逐帧战术真值。
- 回放终态核对后，将 v3 工具校验与日志 CLI/AppConfig 候选共七个文件正式接入。覆盖前核对原文件仍匹配回放 manifest，未覆盖其他新增改动。README 已说明归档删除行为、默认不限制、0 的语义及原始抓包独立保留。
- `a07-a13-promoted-contracts/summary.json` 正式工作区十组通过：工具边界/字段/作用域、正常能力、Agent、区段、持久分析、日志 CLI/轮转/异步收尾及复盘崩溃恢复。此证据不再只是隔离副本测试。
- `a10-review-side-effect-crash/` 通过真实子进程在外部 SQLite 已提交、工作流检查点未提交时强制退出的两类测试：首次记忆写入、训练草稿创建。恢复后无重复行、既有行与有效期不变、六步流程完成，再读完成结果不重复执行。该语义是幂等恢复，不是跨数据库原子回滚，也不是云端请求恰好一次。
- 上述全量回放绑定正式接入前版本，后续最终版本综合验证仍需对应新哈希；监听环境、原生语音及其他未完成项继续推进。A01–A13 不因这十组通过而整体标记完成，U01–U04 保留，iOS/ESP 排除。

### A07 圈段结构与作用域契约候选（v3）

- 最新候选覆盖 tool_contract.py、capability_executor.py、capabilities/history.py、capabilities/segments.py，保存在 `output/architecture-implementation/a07-output-contract-staged-v3/`。圈/区段输出 schema 细化到 scope、圈号、正耗时、证据来源和引用、比较数组与 eligible_segment_count；保留已有额外证据字段。
- 执行器在返回分析工具结果前核对 scope 与请求的 UID/epoch/track 完全一致。新增 exclusiveMinimum 子集支持，保证耗时严格为正。校验结构与绑定不等于证明源数据真实，也不替代原有确定性比较/回答校验。
- 更新故障测试先验证合法完整结果通过，再分别测试十类错误，避免空合法 fixture 导致所有失败用例因同一无关原因通过。六组隔离回归均退出 0、reported_passed=true，既有分析与区段流程保持可用。
- 此候选仍未接入回放绑定的主源码。61934 最新工具确认运行中；全量回放及正式工作区验证完成前，不标记 A07/A13 完成。iOS、ESP 继续排除。

### A13 生产日志保留配置候选（隔离验证，未接入）

- 将 replay_log_max_archives 接入 AppConfig、AsuradaApp 构造的 ReplayLogger，以及 CLI 的 --replay-log-max-archives。省略保留现有全部归档行为；0 只保留当前文件；负数在启动 live 服务前拒绝，Python 配置也拒绝布尔/字符串/负数。该配置不限制原始 UDP 抓包。
- 候选源码位于 `output/architecture-implementation/a13-log-retention-config-staged/`，三组测试通过：CLI 配置传递及实际 Logger 构造、文件轮转保留、异步日志收尾。live 服务用假实现，文件操作仅临时目录，未删除用户已有日志或绑定端口。
- 初次结果汇总误把 stdout 前导运行日志当作 JSON 解析失败，原始汇总保留为 summary-before-parser-fix.json；使用项目现有 parse_report 重新解析相同 stdout，确认三组均退出 0 且 reported_passed=true，没有重复执行测试。
- 全量回放 61934 仍在运行，候选等待终态后接入主源码；当前不能将此项标记为生产配置已交付。

### A07 工具契约候选边界复核（v2，尚未正式接入）

- 最新候选位于 `output/architecture-implementation/a07-output-contract-staged-v2/`。普通查询的 speak_text/action_code 也使用注册表输出 schema；历史工具仍在有界 worker 内完成输出检查和到期复查。
- 增加 JSON 类型检查（拒绝 tuple、非字符串 key）、深层非有限值、128 KiB 序列化大小和 32 层嵌套限制。声明中的未知关键字即使位于未出现的可选字段也拒绝；当前只支持注册表使用的 schema 子集，其他特性必须显式增加实现。
- 六组隔离候选回归均退出 0 且 reported_passed=true，包括新增 14 项边界与既有合法工具/分析流程。证据 scope 保留子进程可能重新导入工作区源码的限制，正式接入后须在工作区重跑。
- 全量回放会话 61934 仍确认运行。临时日志仍为 3 个文件，本次观察约 42 MB，磁盘剩余约 502 MiB；未扩大日志保留，也未重新启动回放。核心源码保持绑定版本，候选待回放终态后接入。

### A07 工具输出契约执行缺口与隔离修复

- 新增 capability_output_contract_regression，经真实 CapabilityExecutor 返回路径注入坏 handler 结果。`a07-output-contract-before/summary.json` 失败：缺字段、非对象、错误单位、NaN、布尔数值、错误集合类型六类均未被拒绝，证明注册表 schema 尚未在该边界执行。
- 修复候选保存在 `output/architecture-implementation/a07-output-contract-staged/`（tool_contract.py、capability_executor.py），以独立包副本测试，不修改全量回放 61934 绑定的核心源码。候选在 handler 前验证输入、完成前验证分析工具输出，拒绝非有限 JSON、超过 128 KiB/32 层结构和不支持的 schema 关键字；仅实现当前注册表使用的 schema 子集，不宣称通用 JSON Schema 支持。
- 候选的输出故障回归、现有执行器、分析 Agent、区段工具和持久分析五组退出码及 reported_passed 均通过。子进程若自行优先导入工作区源码，仍可能使用旧实现，因此这些是隔离候选验证，不替代正式接入后的回归。
- 待当前全量回放终态核对后，将候选接入并执行工作区回归；目前不能标记 A07 完成。回放仍在会话 61934 运行，未重复启动。

### 最终用户验收任务已单独保留

- 新增 [最终用户验收任务表](ASURADA_FINAL_USER_ACCEPTANCE_CN.md)，覆盖 U01 真实比赛、U02 语音、U03 网页、U04 复盘训练的操作、核对结果、证据和问题复验记录，全部保持待验收。
- iOS 与 ESP 已排除；键盘停止与口头打断/AEC 分开记录。此交付不表示 A01–A13 已完成，开发侧与用户实机结论仍分别记录。

### A13 全量回放临时日志容量修复（最新）

- 失败根因为 ReplayLogger 仅限制单个文件 16 MiB，轮转归档无数量上限；全量回放临时目录不断累积展开的 debug 数据。未删除用户已有日志或抓包。
- ReplayLogger 增加可选 max_archives（非负整数），默认 None 维持既有生产保留行为；仅清理匹配自身时间戳归档命名的普通文件。phase1 回归临时目录设置为 2，保留最近两个归档及当前文件；逐帧处理、严格快照往返与决定比对不减少。
- `a13-replay-retention/summary.json` 两组通过：真实临时文件系统连续轮转、最新记录保留、零归档、默认不清理、无关文件保留、非法配置拒绝，以及既有异步日志入口与退出排空。
- 已启动新会话 61934，证据目录 `output/architecture-implementation/a13-bounded-log-full-replay/`。run.py 重新绑定输入哈希，主抓包与分场次样本均无帧数上限，进程终态和报告待核对；不预判通过。生产运行的持久日志保留策略尚需单独明确，此项仅解决本次回归临时磁盘累积。

### 范围调整：本轮不做 ESP 适配（最新要求）

- 隼人明确要求“不做esp适配”。A09 仅推进核心与网页契约，U03 仅保留网页验收；iOS 继续暂缓。历史进展中提到的 ESP/iOS 待办不再作为本轮完成条件。
- 撤回刚新增的 ESP feed_status 辅助模块、测试及 stream 接入，保留已有 ESP 适配器与固件。后续不推进 ESP 适配或设备验证。
- 核心、语音、复盘、训练与网页的既定改进继续，最终用户验收任务保留。

### A13 全量回放执行终态

- 会话 9168 已结束：退出码 1，用时 218.08 秒，绑定输入哈希均未变化。证据见 `output/architecture-implementation/a13-after-rollover-full-replay/process-completion.json` 和 `stderr.txt`。失败原因为 ReplayLogger 写入时磁盘空间不足（OSError errno 28），没有生成 report.json，不能视为全量回放通过；下方运行中记录仅保留历史。

### A13 帧回绕修复后的无上限全量回放（运行中）

- 已启动唯一执行会话 9168，调用 phase1_regression.py --snapshot-limit 0 --sample-snapshot-limit 0，输出 `a13-after-rollover-full-replay/`。工具最近一次确认进程仍运行，无最终结论，不重复启动。
- input-manifest.json 记录实际命令、当前 core 源码、主回放脚本/pyproject、主抓包与 Shanghai 样本文件哈希。包装器将在进程结束后写 process-completion.json，包含退出码、用时、报告 passed 以及前后哈希变化；stdout/stderr 独立保存。
- 范围为完整录制主抓包与其分场次样本，样本与主抓包可能重叠，不可相加为独立场次证据。未测真实比赛、HTTP 监听或声音设备。运行期间不修改已绑定核心源码，后续须核对终态和报告具体断言，再判断证据是否足够。
- 整体目标仍进行中，iOS 暂缓，用户真实验收保留。

### A04 32 位帧计数回绕处理（最新）

- 新增 frame_counter 的 uint32 模序比较，PacketEpoch 与 SessionLifecycle 统一使用：overall 正常回绕继续前进，frame 同步回绕不当作倒带；新 epoch 下迟到的回绕前包按 floor 拒绝。组帧缓存淘汰也采用模距离，防止高编号旧残帧跨回绕残留。
- 比较前提为两包相距不足 2^31 帧；恰好半范围按旧值保守处理。同 UID 的真正重新启动仍需显式生命周期信号，不能仅凭计数猜测。
- 首轮 `a04-frame-counter-rollover/summary.json` 三过一失败，失败为新测试的接收时间低于旧包，正确触发已存在时间拒绝。修正测试保持接收时钟递增后，`a04-frame-counter-rollover-fixed/summary.json` 四组通过：实际录制包注入 fffffffe→ffffffff→0→1，经组帧/归一化/状态仓保持 epoch=0、历史连续，迟到包拒绝、真实倒带和缓存淘汰保持正确。
- 本次改变遥测主链边界，需要后续综合回放；测试不是长时间真实游戏实测。整体继续，iOS 暂缓，用户真实验收保留。

### A03 TTS 流完整性与完成语义（最新）

- 新增 TtsStreamValidator 并接入 stream_tts 与 play_streamed_tts：消费前核对唯一 start、从 1 连续的帧序号、严格 base64、声明/实际字节数和累计上限（16 MiB/65536 帧）；end 的总帧数和字节数必须一致，拒绝结束后的数据及没有 end 的 EOF。completed 必须有非空音频且 start 成功。
- `a03-tts-stream-integrity/summary.json` 四组通过：九类畸形流、收集与播放两个实际入口拒绝坏帧；已有真实非音频播放器正常结束、主动取消、自动超时、客户端上下文仍通过。旧客户端上下文测试使用空 completed fixture，已改为实际一帧，避免测试鼓励空音频成功。
- 本节证明协议完整性，不证明声音内容正确或用户实际听到；流中部分音频可能在后续错误发现之前已播放，不能撤回。云端供应商自身正常结束事件、完整 HTTP 服务和真实听音仍需另验。iOS 暂缓，其余目标继续。

### A02 修正播放总预算默认值（最新）

- 核对生产 VoiceSidecarSpeechBackend 直接调用 play_tts 且未传 timeout_ms，发现上轮沿用 2500 ms 网络配置作为总时限，会使正常长播报提前取消。现将网络连接/读空闲预算与播放总时限分离：前者沿用 config.timeout_ms，后者新增 playback_timeout_ms=60000，可用 ASURADA_VOICE_SIDECAR_PLAYBACK_TIMEOUT_MS 配置；显式 timeout_ms 覆盖本次总时限，零/负值拒绝。
- README 已记录配置。此前进展中“默认总时限沿用 config.timeout_ms”的描述由本节取代。服务端合成仍受自身默认 15 秒上限，客户端停止依然共享取消信号。
- `a02-playback-budget-separation/summary.json` 四组通过。新增完整 play_tts→流解析→实际非音频进程→played 路径：网络预算 30 ms，测试播放器等待 120 ms 仍正常完成；核对网络独立参数，保留自动总超时/主动取消/播放器失败和客户端上下文回归。此用例未调用扬声器或真实 HTTP。
- 整体继续，监听环境及原生声音问题未消失；iOS 暂缓，用户真实验收保留。

### A02 实际边收边播入口迁移（最新）

- VoiceSidecarClient.play_streamed_tts 已替换 urllib 流读取，使用有界、可取消的 sidecar 行传输并发送剩余预算头；TaskContext 直接共享 PlaybackControl.event。停止不再依赖关闭一个被读锁占用的 buffered response，底层传输 watcher 可 shutdown 所属 socket。
- 新增整段播放 deadline watcher，将到期转为 PlaybackControl.cancel，覆盖网络等待与已附着播放器的结束等待。异常/完成时关闭传输并清理播放器和 meter，TaskCancelled/TimeoutError 转为已有 PlaybackCancelled 接口。
- 行为变化：timeout_ms（未传入时 config.timeout_ms）现在是边收边播总时限，不仅是单次网络 read 超时；较长播报须显式配置适当预算，默认值仍沿用现有配置。此变化需要实际体验验收。
- `a02-live-playback-transport/summary.json` 三组通过；`a02-live-playback-deadline/summary.json` 三组复核，包含主动停止、自动总超时、流关闭、既有实际 fixture 播放器进程回收，以及 socketpair 云端流取消/服务端上下文。尚无真实扬声器、真实 HTTP listener 或云端音频验收。
- 原生 say 空音频、综合服务验证及其他工作包继续；iOS 暂缓，用户真实验收保留。

### A02 TTS 客户端合成与流收集预算（最新）

- VoiceSidecarClient.render_tts/stream_tts/collect_streamed_tts 接受 TaskContext；未传入时仍建立默认任务预算。缓冲合成走已有可取消 JSON HTTP；流收集复用有界行传输，传递 X-Asurada-Timeout-Ms，共用父取消信号并取父 deadline/自身超时最小值。客户端直连 sidecar，不采用环境代理。
- 服务错误维持 VoiceSidecarClientError 边界；关闭流收集器会关闭 HTTP 资源。`a02-tts-client-context/summary.json` 四组通过，验证缓冲上下文、流预算/取消、传输预算头、解析关闭及连接前取消，并保留真实 socketpair 云端流/HTTP 取消和服务端预算回归；`a02-tts-client-error-contract/summary.json` 复核兼容包装。
- 实际边收边播 play_streamed_tts 仍使用独立 PlaybackControl/urllib 路径，尚未完成此次传输迁移，不能以合成/收集接口测试推断播放链路完成。下一步继续这条实际播放器入口。整体继续，iOS 暂缓，用户真实验收保留。

### A02 云端 TTS 流读取取消与容量（最新）

- 将 JSON HTTP 连接所有权提取为共享 _open_response，新增 iter_http_lines：统一 DNS/TCP/TLS/代理与取消资源回收，限制单行 1 MiB、HTTP 总量 32 MiB，流式重定向明确拒绝。现有 JSON 请求/重定向语义保留。
- Doubao TTS 改为该受控 HTTP SSE 读取，支持 TaskContext，默认总预算 15 秒，严格 base64 解码并限制解码音频 16 MiB；移除已不需要的 requests 可用性门槛。显式关闭消费者迭代器时同步关闭供应商连接。
- TTS 执行槽延伸至 produce_and_deliver 完成，覆盖惰性音频迭代与发送；_send_tts_stream 在退出/错误时显式关闭迭代器，防止只约束创建流对象而不约束实际网络读取。旧无上下文 renderer 的底层中断仍不保证。
- `a02-tts-stream-transport/summary.json` 四组通过，核对既有 JSON 取消/重定向/LLM 传输和 TTS 请求；`a02-cloud-tts-stream-cancel/summary.json` 三组通过，新增实际 socketpair HTTP/SSE 正常音频解码、提前关闭连接、阻塞读取消回收，保留 TLS 与请求容量回归。最后移除未使用 requests 门槛后由 `a02-cloud-tts-final/summary.json` 复核。
- 以上未创建 HTTP listener，不能替代真实供应商、实际代理/TLS 组合与共享语音交付验收；TTS 客户端预算传输、系统 say 空音频及其余整体门槛继续处理。iOS 暂缓，用户实测保留。

### A02 TTS HTTP 请求上下文接入（最新）

- /v1/tts/render 与 /v1/tts/stream 统一进入 _tts_request，读取 X-Asurada-Timeout-Ms 并受服务器默认 15 秒总上限限制；合成使用进程级独立两个执行槽。watch_stream 覆盖请求渲染与交付阶段，监视对端 EOF、服务关闭与 deadline，结束时取消剩余工作。超载明确 503，预算错误 400，取消不交付。
- MacOSSay/Piper 声明 supports_task_context，服务实际传递同一 context；本地合成/转换进程复用上轮取消回收。旧 renderer 保持可调用，但没有上下文能力的后端只受外层等待/执行槽约束，底层资源不保证可中断。
- `a02-tts-request-context/summary.json` 四组通过：请求 helper + 实际 socketpair EOF、并发满载拒绝、预算校验、buffered/streamed context 路由，以及本地转换子进程取消、音频有效性、LLM sidecar 回归。未创建 HTTP listener，不能代替实际 HTTP 服务整链验收。
- 云端惰性流式 TTS 迭代器的底层网络取消/容量、客户端传输预算和完整监听测试仍需补齐；系统 say 空音频未解决。A01–A13 继续，iOS 暂缓，用户真实验收保留。

### A02 本地 TTS 合成/转换进程预算（最新）

- MacOSSay/Piper sidecar renderer 的 render/stream_render 接受可选 TaskContext，未传入时建立 15 秒内部总预算。say→afconvert 共用剩余预算，Piper 文本经有界 stdin 输入；复用已有进程组取消与回收实现，替代无超时 subprocess.run。读取音频前后检查预算，并拒绝超过 16 MiB 的输出文件。
- `a02-tts-process-budget/summary.json` 三组通过：新增实际 fixture 转换子进程挂起→取消→回收、两阶段同一预算递减；保留无效 WAV 拒绝与已有 Piper 后端测试。不是原生 TTS 音频质量验收；系统 say 空输出问题仍待解决。
- HTTP 服务入口当前仍未把客户端断开取消传至这两个 renderer，当前服务调用仅获得默认内部时限；需要下一步接入请求 TaskContext/有界执行槽及流式清理，不能宣称整链取消完成。iOS 暂缓，其他开发及用户验收范围保留。

### A13 原生合成定位与实时 ASR 发布依赖（最新）

- `a13-say-voice-matrix/report.json` 比较 Tingting、Albert、Eddy 中文三种已列出的系统声音，均为 say/afconvert exit=0、WAV frames=0。afinfo 进一步确认转换前 AIFC 已 audio bytes=0/audio packets=0；因此问题位于原生合成输出阶段，不只是默认 voice 或 WAV 校验，环境服务/系统权限等具体根因仍未证实。不削弱有效性检查，不将这项失败标绿。
- 另核对生产 voice_sidecar_asr 三处 import websocket，当前虚拟环境没有 websocket-client，pyproject 也缺少声明。新增 realtime-asr extra 固定 websocket-client==1.8.0；PyPI 该版 Requires-Python>=3.8，兼容项目 Python 3.9（https://pypi.org/project/websocket-client/1.8.0/）。未选要求更高 Python 的新版本。
- 会话 36554 构建 wheel exit=0；`a13-realtime-asr-package/metadata-check.json` 检查实际 wheel 包含 realtime-asr 与对应 Requires-Dist 并记录哈希。README 增加安装命令与验证边界。本轮没有安装依赖或调用云端，元数据成功不能代替真实 WebSocket/TLS/ASR 验收。
- 整体工作继续；监听测试受限、原生声音输出及其他综合门槛仍未闭环。iOS 暂缓，用户真实验收保留。

### A13 分析与语音接入后的综合契约回归（最新）

- 会话 76168 已确认 exit_code=1。`a13-integrated-analysis-voice-contracts/summary.json` 执行当前全部 142 个 contracts（不含 phase1 全量原始包回放）：120 passed、22 failed、0 skipped。新增分析/答案/持久恢复/用量/语音入口，以及模型特征、训练分割、取消和领域策略等回归通过。整体套件未通过，不能宣布开发完成。
- failure-triage.json 按逐项 stderr 留证分类：21 项在实际监听 socket 创建处遇到 PermissionError，包含网页 WebSocket、共享语音及 HTTP sidecar；保留失败，不通过模拟或豁免改成绿灯。本轮未重复申请已受限的监听权限。
- 另一项 phase3_voice_sidecar_tts_regression 为 tts_audio_empty_or_truncated。已使用相同默认 voice/169 WPM 单独执行系统 say 导出 AIFF，再由 afconvert 转单声道 16 kHz/16-bit WAV，两个进程 exit=0，但 WAV frames=0、payload_bytes=0。`say-diagnostic/report.json` 和产物保存证据；首次诊断错误地把空 voice 传入 -v，已按生产逻辑改为省略该参数后完成复现。无扬声器播放，原生语音合成失效根因尚未确定；现有音频有效性拒绝行为正确，不能削弱校验。
- 本轮未改动生产源码。A13 需在允许监听的测试环境完成服务整链，并解决原生 TTS 输出，再执行改动后完整回放；其他工作包继续。iOS 暂缓，用户真实验收保留。

### A07 赛后复盘接入现有语音协调器（最新）

- 新增 ReviewVoiceService，VoiceInputCoordinator 从环境配置加载。仅 companion（非比赛）路径中以“复盘/帮我复盘/请复盘”开头的问题进入分析；控制指令和比赛中路径保持原路由。复盘范围从已授权的已完成官方圈索引取得，多个场次明确拒绝，不拿当前断流状态补造历史数据。
- 流程复用持久分析、工具权限/预算和证据回答，将回答通过现有 VoiceQueryBundle response_override 交给原有语音输出与交付回执。超时/取消不交付，数据不可用返回明确提示。此为显式复盘入口，尚不支持自动选最近复盘或连续多轮历史引用。
- 配置：ASURADA_REVIEW_TASK_ID、ASURADA_REVIEW_STORE（必须已有）、ASURADA_REVIEW_DRIVER_ID；规划器选择 ASURADA_REVIEW_PLANNER_COMMAND 或 ASURADA_REVIEW_PROVIDER（openai-responses/doubao-responses/doubao-chat，复用既有模型认证配置）。未配置任务 ID 时功能关闭；不要把驾驶员身份配置当多用户认证系统。
- `a07-review-voice-entry/summary.json` 三组通过，覆盖 PTT 文本转录→真实 SQLite→脚本规划器→证据回答→现有输出，以及比赛/控制隔离；`a07-review-voice-deadline/summary.json` 复核内部预算超时无交付。空播放后端与转录 fixture 不代表真实麦克风、播报或共享服务实机验收。
- 后续需复盘选择、连续上下文、真实供应商/声音交付和综合回归。A01–A13 继续推进，iOS 暂缓，用户真实验收保留。

### A07/A10 持久模型用量记录（最新）

- 分析日志在模型尝试前保存 outcome_unknown/usage=null；成功或预算内明确失败时保存 provider 的模型、API 类型、输出上限和用量元数据。失败响应附带用量也保留；取消/超时后的迟到 worker 不写结果，其已预留尝试仍明确未知。
- 最终结果 provider_usage 汇总整个持久任务，包括失败和恢复前的尝试，区分完整用量与缺失/部分用量。已知输入/输出 token 单独累计，费用为 null/not_calculated，不把未知用量当零费用。读取已完成结果保留累计记录；认证头不进入记录。
- `a10-analysis-usage-ledger/summary.json` 三组通过，新增真实 SQLite + mock HTTP 的失败用量、恢复只新增一个请求、缺失用量、最终读取和凭据不落盘验证，保留恢复/取消/预算及 HTTP 协议回归。
- 当前实现是持久用量证据，不是实际供应商账单核对或金额硬上限；中断前未返回的用量需外部账单才能补足。整体架构仍进行中，下一步继续产品入口接入与综合验证。iOS 暂缓，其他用户实测保留。

### A10 已完成分析结果的独立读取（最新）

- 分析结束时将最终结构化结果与任务状态在同一 SQLite 事务中保存，提交和返回前检查执行预算。再次运行同一已完成任务直接读取结果，不启动规划器，也不修改原始到期时间。
- 新增 read_review_analysis.py，使用独立读取预算，不需要模型配置。已完成/数据不足结果在执行期限过后仍可读取；未完成任务依然受原始执行期限限制。读取重新核验历史读取权限、驾驶员、复盘状态/内容摘要、最终结果绑定，并重新执行证据回答校验。旧日志若没有 final 检查点会明确拒绝，不假设其已完成结果可恢复。
- `a10-analysis-result-read/summary.json` 三组通过，包含实际独立 CLI 到期后读取、权限撤销拒绝和既有恢复/取消/预算行为；`a10-analysis-result-commit-budget/summary.json` 复核提交预算调整。测试为本地 SQLite 与命令规划器故障注入，未调用真实模型或语音。
- 仍需持久供应商 usage/成本以及语音分析入口整链；A01–A13 继续推进，iOS 暂缓，用户真实验收保留。

### A07/A10 分析任务持久日志与进程恢复（最新）

- 新增 durable_analysis.py，复用 WorkflowStore 的 tasks 表和同任务非阻塞文件锁。CLI 默认持久化分析，输出 analysis: 命名空间任务 ID；通过 --analysis-id 重用同一 ID，在原始截止时间内恢复。已完成规划/工具调用按输入摘要重放；不确定结果的模型尝试和未完成读取在执行前计入持久预算，重启不重置模型/工具次数或任务到期时间。
- 请求绑定问题、场次、驾驶员、权限、规划器配置、预算及完整复盘摘要；同 ID 输入变化拒绝。恢复入口和缓存工具读取均重新检查已完成复盘的所有者，内容变化拒绝。取消状态通过 watcher 传入同一 TaskContext，取消后不提交成功回答。
- `a10-durable-analysis/summary.json` 三组通过；`a10-analysis-process-recovery/summary.json` 包含两次独立 CLI 子进程故障后恢复；`a10-analysis-persistent-budgets/summary.json` 两组最终复核，包含累计模型/工具预算、原始期限、互斥执行、缓存读取、回答恢复、取消及权限撤销拒绝。
- 语义为已提交调用复用，未提交只读工具可能重试；不声称外部模型请求恰好一次。当前仅原始预算内恢复，完成结果超出到期时间后的独立历史读取入口、持久供应商 usage/成本、真实模型调用及语音分析接入仍待实现。A01–A13 继续进行中，iOS 按要求暂缓，其他用户实测保留。

### 范围调整与 A07 证据回答接入（最新）

- 隼人明确要求“ios先不管”。iOS 的接入、状态拆分、多端一致性和设备验收暂缓，不作为本轮目标完成的阻塞项；A09/U03 已调整。历史进展中的 iOS 待办仅保留追溯，后续综合验收也排除 iOS。核心、语音、网页、ESP32、复盘训练的既有要求继续执行。
- HTTP 分析规划器已复用既有 provider 配置和可取消传输，支持 Responses/Chat 的结构化单步选择、输出 token 上限、usage 记录；`a07-http-analysis-planner/summary.json` 三组通过。仅模拟供应商协议验证，不代表真实 API 或计费验收，总成本控制仍待补齐。
- 新增 analysis_answer.py，从分析循环选中的成功工具结果生成中文回答，核对任务/场次/复盘绑定、单位、有限数字、圈时差与区段极差推导，并保留证据、比较条件和排除项。不能比较时返回 insufficient_data；不将圈时变化解释成训练收益。接入 ReviewAnalysisAgent 后 CLI 直接包含 answer，失败或最终预算检查未通过时移除回答。
- `a07-grounded-analysis-answer/summary.json` 四组回归通过（答案、分析循环、HTTP 规划器、区段工具）；`a07-answer-final-budget/summary.json` 复核分析入口。覆盖实际命令规划器子进程到 SQLite 工具和答案的 CLI 流程，以及错误单位/场次/引用/推导/非有限数字拒绝。
- `a07-grounded-analysis-answer/recorded-review-answer.json` 使用此前保存的录制复盘工具结果，保存输入哈希与四段证据回答：第 3 圈比第 1 圈快 2.451 秒，T11-T13 区段极差显示为 0.453 秒。此为录制结果表达验证，尚未接入实时语音入口或持久分析恢复。A01–A13 继续进行中，U01–U04 按新范围保留。

### A07 有界分析工具循环与命令规划器入口（最新）

- 新增 ReviewAnalysisAgent，按规划器 next_step 的 call/finish 协议执行现有 analysis_tool；默认最多 6 次规划、4 次工具，复用 TaskContext/有界 LLM 执行槽，限制上下文与单步 JSON 大小。每步保留决策和工具观测；参数错误可作为失败观测供下一步纠正。
- 工具只能来自权限过滤后的注册目录，并绑定调用方指定 review_task_id；拒绝其他复盘任务、写/控制工具和未注册名称。finish 只选择成功观测 ID，未知/失败 ID 拒绝，空选择标 insufficient_data；最终携带真实工具结果，不接收任意模型文案作为事实。
- CommandAnalysisPlanner 复用可取消、有界输入/输出的命令执行器；run_review_analysis.py 提供实际 CLI。当前为规划器协议和执行链，尚未接入云端模型适配、自然语言回答/播报、语音交互，也未完成实际 token/费用核算。
- `output/architecture-implementation/a07-analysis-loop/summary.json` 三组通过：脚本规划器驱动实际 SQLite/执行器/独立命令 CLI，覆盖结果引用、失败后纠正、调用预算、目标复盘绑定、禁止控制工具与空结果；圈/区段工具回归保留。该结果不证明真实模型规划质量。A01–A13 保持进行中，U01–U04 保留。

### A07 参数化区段比较工具与录制数据 CLI 验证（最新）

- compare_review_segments 注册独立 schema，复用完成复盘/驾驶员校验和历史作用域，接收复盘任务、2–10 个圈号及 top_k（1–20）。从 analyze_segments 的原始区段记录选择相同场次/epoch/赛道/条件/距离范围，返回按耗时极差排序的结构化比较、逐圈时长和证据。
- 缺圈/重复圈、条件或距离不同的区段列入 excluded；无可比区段返回 insufficient_data，不补造排名。结果声明 observed_segment_spread_not_causal_diagnosis；现有可比条件仍只覆盖复盘已采集的条件，不推断交通/燃油等已被控制。
- 真实独立 CLI 查询已保存录制复盘第 3/4/5 圈，前三为 T11-T13 Load Carry（453.162 ms）、T7-T10 High Load（408.339 ms）、T1/T2 High Load（392.046 ms）；`a07-real-review-cli/segment-tool-acceptance.json` 与已完成复盘比较结果、来源哈希对应通过。
- `output/architecture-implementation/a07-structured-segment-tool/summary.json` 四组回归通过，新增排名/top_k/差值/证据/不可比数据/无数据路径，并保留圈工具及固定能力回归。下一步仍需开放交互工具循环与回答证据转换。A01–A13 保持进行中，U01–U04 保留。

### A07 录制原始包到复盘再到 CLI 圈比较验收（最新）

- 使用当前 review_raw_capture.py 对 Shanghai 录制场次重新执行完整复盘，会话 68759 exit_code=0；`output/architecture-implementation/a07-real-review-cli/` 保存 106,103 包/5,071 快照投影、完成的七步复盘和数据库。
- 首次 query_snapshot_tool CLI 暴露复盘投影缺 total_laps，而入口强制 decode_snapshot 的问题。新增经校验的 ReviewScope（UID/epoch/track），仅允许 historical analysis_tool 使用；结果以 scope_id 标识且 snapshot_id=null，不补造实时字段。固定实时问答不能使用该作用域。
- 修复后真实独立 CLI 查询第 1/2/3 圈，圈时 103031/102369/100580 ms，返回 delta_ms=-2451。tool-acceptance.json 核对投影证据哈希、三圈与差值、数据库查询前后内容哈希未变，passed=true。原始录制仅作为离线业务证据，不是真实比赛在线验收。
- `output/architecture-implementation/a07-review-scope-cli/summary.json` 三组通过，增加仅含作用域的真实子进程 CLI、历史作用域与快照区分、禁止用于实时固定问答；已有权限/驾驶员/epoch/参数拒绝回归保留。
- 下一步仍须接入开放分析工具循环和结构化结果到回答/播报的证据转换，不将 CLI 成功当作语音 Agent 闭环完成。A01–A13 保持进行中，U01–U04 保留。

### A07 参数化圈比较工具接入既有执行器（最新）

- 能力定义新增 compare_review_laps，注册输入/输出 schema，接收 review_task_id 与 2–10 个不重复正整数圈号。CapabilityExecutor 在既有预算、权限、快照绑定和有界线程中执行结构化 handler，返回 data（圈时、差值、ms 单位、来源证据、场次作用域），不从播报文案反向提取数值。
- 复用 WorkflowStore 的已完成 official lap index；driver_id 来自执行器可信配置，不接受工具参数覆盖。拒绝未完成复盘、驾驶员不匹配、缺历史读取权限、场次/epoch/赛道不匹配、缺圈及无效参数。比较仅表示观测圈时变化，不推断因果。
- query_snapshot_tool.py 增加 --arguments-json/--review-store/--driver-id，可通过现有 CLI 调用；要求复盘数据库已存在。analysis_tool 不进入固定语音问答路由，避免无参数调用错误；后续交互工具循环仍须接入，不据此宣称 Agent 产品流程完成。
- `output/architecture-implementation/a07-structured-lap-tool/summary.json` 三组通过：真实 SQLite checkpoint/执行器上的 fixture 圈证据与拒绝路径、已有 capability handler 和 executor。通用 schema 字段与参数所有权调整后由 `a07-lap-tool-schema/summary.json` 复核。尚待真实复盘产物/CLI 和语音开放分析整链验证。A01–A13 保持进行中，U01–U04 保留。

### A12 全部 347 个模型/特征组合完整数值对照通过（最新）

- 会话 58557 已确认 exit_code=0；`output/architecture-implementation/a12-all-feature-values/report.json` 为 completed/passed=true、rows_checked=83,437、differences={}。六场全部完成，涵盖新补齐的接近率、区段预览、驾驶阶段因子与计时支持等级。
- completion-audit.json 核对 347 个模型/特征组合每个均比较 83,437 次，额外 30 个资产/导出清单哈希未变化；主审计亦核对抓包、当前核心源码/脚本和完整导出未变化。此前只验证共有列的证据由本次更完整的输入数值对照补足。
- 通过范围是全部模型必需输入值与当前已保存训练导出的相等性（缺失类别表达归一），不包含模型输出质量、决策行为差分、连续语音或多端一致性。未授予生产准入，仍需改动后综合回放。A01–A13 继续进行中，U01–U04 保留。

### A12 改动后全部必需特征的完整数值对照（运行中）

- 新增 audit_runtime_feature_values.py，读取 14 份已封存重训报告，共 347 个模型/特征组合；对六场原始包执行实际解码、组帧、生命周期和生产上下文/特征构建，按记录 ID 与已验收 features.csv 严格顺序逐行比较。任意缺列也计为差异，不再只比较交集。
- 该流程不执行模型推理或生成新标签，目的是验证运行时全部模型输入相对已保存训练特征的一致性。逐列保存比较次数、差异次数及首个例子；启动和结束核验核心源码/脚本、抓包和完整导出，额外保存 30 个资产/清单文件哈希。
- 已启动唯一会话 58557，输出 `output/architecture-implementation/a12-all-feature-values/`；最新工具确认仍运行，前四场完成（5,163/4,879/3,166/5,071 状态），总进度约 29,000 状态，暂未发现差异。不是终态，不提前判定通过。
- A01–A13 保持进行中；本轮不改变模型默认模式或准入，U01–U04 保留。

### A05/A12 修复 7 个模型的运行时结构性缺列（最新）

- 针对实际重训 14 资产执行完整列集合审计，`a12-current-retraining/feature-coverage.json` 发现 7 个模型缺列：驾驶三模型分别缺 brake/throttle/steering_phase_factor；对手模型缺 timing_support_level，部分还缺 gap_closing_rate_behind；defence_cost 另缺 next_two_segments。旧“共有列一致”没有覆盖这些列，不能替代本检查。
- 新增 model_temporal_features，共享导出原有接近率和区段预览函数；ContextProfile/StrategyEngine 生成后车接近率及后续区段组合，运行时补全部六类字段。默认预览距离 120/280 米与本次已导出配置相同；自定义导出预览配置仍须单独绑定，不能推定兼容。
- prepare_model_inputs 增加 absent_columns；两类运行时在 observe/active 都拒绝结构性缺列，明确 feature_columns_not_generated，不再由编码器静默补 NaN。键存在但值未知与结构性缺列区分，已有物理质量门禁保留。
- 首轮因新模块缺 future annotations 而在 Python 3.9 导入失败，已修正。`a12-runtime-feature-completeness-fixed/summary.json` 四组通过（实际导出、编码、输入质量、时间上下文）；`a12-missing-feature-guard/summary.json` 验证 14 旧资产列覆盖与双模式缺列阻断；`a12-current-retraining/feature-coverage-fixed.json` 验证 14 新资产列集合均覆盖。
- 本轮改变了模型输入与 ContextProfile，之前全量回放和 83,437 状态共有列对照不替代改动后的全列数值对照/综合回放；尚需执行。资产完整性不等于新运行行为验收，生产准入未授予。A01–A13 保持进行中，U01–U04 保留。

### A12 全场共有特征对照完成（最新）

- 会话 26080 已由工具确认 exit_code=0，`output/architecture-implementation/a12-feature-parity-audit/report.json` 为 rows_checked=83,437、differences={}、examples={}。此次实际遍历全部六场状态，而非每场前 64 状态。
- 已纠正报告 scope，并保留 original_scope_text 记录启动时描述错误；64 限额只作用于对照目录中的主表输出，不能将该抽样导出当完整训练输入。正式重训使用另一份已验收完整导出。
- 结论限于当前模型清单特征中同时存在于运行时构建器的共有列，None/UNKNOWN 缺失表达归一；不涵盖缺失于运行时构建器的列，也不证明模型收益。14 资产完整性与本次共有特征一致性分别留证，生产准入仍未授予。

### A02 有界同来源重定向与预算延续（最新）

- request_json 增加 max_redirects（默认 0，云端 provider 配置 3）；各跳转共用总 deadline/cancellation，前一连接先清理。307/308 保留方法/正文；301/302 的 POST 及 303 非 HEAD 转 GET 并移除正文相关调用方头。跨来源（scheme/host/port）跳转拒绝，不将认证和请求数据转发到其他来源。
- `output/architecture-implementation/a02-http-redirects/summary.json` 四组通过：实际 socketpair HTTP 重定向线协议覆盖五类响应、方法/正文、剩余预算、跨来源不联系和循环上限，TLS/CONNECT、HTTP 取消和 provider 上下文回归保留。
- 与旧 urllib 自动行为的差异是跨来源跳转明确拒绝，需将 provider base_url 配置为最终来源；仍未完成真实 DNS/TCP/供应商及完整交互入口验收。A01–A13 保持进行中，U01–U04 保留。

### A02 实际 TLS/CONNECT 离线协议验证通过（最新）

- 新增 http_tls_protocol_regression，运行时生成仅用于测试的临时证书和私钥，使用真实 SSLContext 与 HTTPConnection/CancellableHTTPSConnection 在 socketpair 上传输；仅替换 TCP 建连，不创建 listener、不连接外部服务，测试结束清理证书。
- `output/architecture-implementation/a02-http-tls-protocol/summary.json` 通过六种场景：可信 TLS 取 JSON、CONNECT 后 TLS 取 JSON、不可信证书拒绝、主机名错误拒绝、TLS 握手取消、CONNECT 响应等待取消。核对实际 CONNECT 认证头、目标请求不带代理认证，以及取消后对端关闭。
- 该结果强于前序 mock TLS/代理构造检查，但仍不覆盖 DNS/实际 TCP 建连、系统代理服务、公网供应商、完整语音交互或设备验收；重定向兼容仍未完成。特征对照 26080 本轮工具确认仍运行。A01–A13 继续进行中，U01–U04 保留。

### A02 DNS/TCP/TLS 建连阶段的取消边界（最新）

- 新增 http_connection：DNS 查询通过进程内最多两个槽位执行；调用者取消后立即结束等待，不可中断的系统解析仍占槽直到返回，满载明确拒绝。TCP 使用非阻塞 connect_ex/selector，按同一任务预算检查并在失败/取消时关闭 socket；多个地址尝试不重置预算。
- HTTPSConnection 在握手前公布 TLS socket，取消 watcher 可对连接/代理隧道/TLS 当前 socket 反复 shutdown，避免 socket 替换竞态只关闭旧对象；仍由默认 SSL context 执行目标主机证书验证。代理 CONNECT 与真实 TLS 服务器尚未验收。
- `output/architecture-implementation/a02-http-connect-cancellation/summary.json` 四组通过：新增故障注入 DNS 占槽/恢复、TCP 关闭、TLS 中断/主机名透传，保留代理路由、实际 socketpair 读写取消、LLM 上下文回归。后续 watcher 竞态调整由 `a02-http-connect-cleanup/summary.json` 定向复核。
- 特征对照会话 26080 本轮仍由工具确认运行，未重启。A02 仍待真实连接/代理、重定向兼容和综合入口验证；A01–A13 保持进行中，U01–U04 保留。

### A02 HTTP provider 代理路由与 socket 取消回归（最新）

- 可取消 HTTP 传输增加显式 trust_env 选项；云端 Responses/Chat provider 开启后按 urllib 的代理发现及 bypass 规则选择路径。HTTP 目标使用代理绝对请求地址，HTTPS 目标通过 HTTP 代理 CONNECT 后由 HTTPSConnection 建立目标 TLS；代理认证仅置于对应代理请求/隧道头，目标请求不附隧道认证。
- 默认 trust_env=false 保留已有直接传输调用方行为；不支持的代理配置（包括 SOCKS/TLS 到代理）明确拒绝，不静默直连。自动重定向尚未恢复；connect/DNS/隧道握手阶段的取消资源释放仍待补齐，不能据此宣布 urllib 的全部行为兼容。
- `output/architecture-implementation/a02-http-proxy-routing/summary.json` 四组通过：代理路由构造（模拟配置、无真实网络）、既有 socketpair 上实际 HTTP 读写/取消/超时/超大响应/资源关闭，以及 provider/sidecar 上下文测试。socketpair 测试不创建 listener，也不替代真实 CONNECT/TLS/代理服务器验证。
- 特征对照 26080 本轮工具确认仍运行，未重启。上一轮已完成 14 资产完整性核验，本轮未改变默认模型或批准状态。A01–A13 继续进行中，U01–U04 保留。

### A12 六阶段真实重训与 14 资产完整性核验通过（最新）

- 会话 66662 已由工具确认 exit_code=0，retraining-report.json 为 passed=true/stages=6/assets=14；输出保持在独立目录 `output/architecture-implementation/a12-current-retraining/`，未替换默认报告或模型。
- 新增同目录 completion-audit.json，重新读取 14 份封存报告，验证模型/特征哈希、validation_status=matched、train/val/test UID 均非空且两两不交叉；同时按各训练器 partition 或 partition_manifest 实际字段保存完整分割、窗口版本、标签来源与报告指标。artifact_integrity_passed=true。
- 指标仍不构成生产批准：fuel_risk/front_pressure 报告 R²=0，future_grip_drop_score R²=-0.0946965993971951；其余高分也主要针对规则/代理标签，不能证明驾驶收益。production_admission=not_granted；尚待特征对照 26080 终态、模型行为与适用域评估。该进程本轮确认仍运行。

### A02 语音 sidecar LLM 客户端与服务端取消传播（最新）

- VoiceSidecarLlmExplainerBackend 与 VoiceSidecarClient.explain 接收并透传上层 context，走可取消 HTTP 分支。服务端 /v1/explainer 接入 _explain_request，按请求预算、传输剩余预算和服务端 15 秒上限取最小值，复用 watch_stream 监听对端 EOF、服务关闭和 deadline，并将同一 context 传给 LlmExplainer。
- `output/architecture-implementation/a02-sidecar-context-wiring/summary.json` 三组通过：模拟 HTTP transport 核对客户端透传；无 listener 的服务方法测试核对预算、非法值、模拟连接 EOF 与 shutdown 取消；既有直接 HTTP 上下文和真实命令进程取消回归保留。
- 这些测试不替代真实 socket/服务端资源恢复和供应商验证；直接 HTTP 的代理兼容、连接/DNS 取消仍待处理。A01–A13 继续进行中，U01–U04 原样保留给隼人。

### A12 完整导出验收通过并启动真实重训（最新）

- 导出进程 90335 已由工具确认 exit_code=0；stdout/stderr 和 process-completion.json 归档至 `output/architecture-implementation/a12-current-training-export/`。主表与标签各 83,437 行，六个配置 UID 均覆盖；战术表 72,166 行、事件表 1,512 行、攻防表 144,566 行、策略动作表 73,181 行。
- 同目录 validation.json 为完整六表验收 passed=true，核对唯一身份、完整配置场次分割、主表/标签对应、派生来源及内容哈希。验证范围不包括标签真实性或模型收益。策略动作表无原始 val 记录，训练器使用既定整场后备分割；实际策略训练阶段已 exit_code=0，不是放宽类别门禁。
- 已启动唯一重训会话 66662，独立目录 `output/architecture-implementation/a12-current-retraining/`。最新进程仍运行，资源风险、驾驶质量、对手压力、策略动作四阶段已各 exit_code=0；其余阶段和最终 14 资产封存尚待终态核验。未替换默认模型、未批准 active。特征对照 26080 本轮确认仍运行。

### A02 HTTP provider 共用任务上下文（最新）

- OpenAI/Doubao Responses 与 Doubao Chat 改用既有 request_json 有界直接 HTTP 传输，并提供 explain_with_context；实际 LlmExplainer 工作线程传入上层任务。Doubao 主/备请求保留相同 cancellation 与 deadline，后备只获得剩余 timeout，取消后不启动后备。
- `output/architecture-implementation/a02-http-context-wiring/summary.json` 四组通过，新增模拟传输测试验证三类请求上下文/头部、后备递减预算、取消禁止后备及外层取消传到 provider；命令取消、LLM 边界和任务运行时回归保留。该测试不证明真实 socket 释放或供应商调用成功。
- HTTP 传输目前为直接连接，不继承 urllib 环境代理/重定向行为；代理兼容与 connect/DNS 阶段取消仍需纳入后续验证。VoiceSidecarLlmExplainerBackend 及服务端贯通尚未完成。A02 不标记完成，A01–A13 继续进行中，U01–U04 保留。

### A02 LLM 命令后端贯通取消与资源回收（最新）

- CommandLlmExplainerBackend 复用 capture_process 的有界 POSIX 子进程执行器，支持 explain_with_context；LlmExplainer 在实际工作线程中传递原任务上下文，命令执行与上层共用 deadline/cancellation。旧 explain(request) 入口仍可独立使用，其他 provider 尚未全部迁移。
- 子进程 stdin 使用非阻塞分段写入，与 stdout/stderr 同时推进，避免不读取输入的命令阻塞取消；输入限制 4 MiB，JSON 输出按 UTF-8 字节累计限额，错误输出保留有界尾部。取消或超时沿用进程组终止及子进程回收。
- `output/architecture-implementation/a02-command-resource-cancellation/summary.json` 四组通过：新测试使用真实本地子进程验证等待输出、阻塞 stdin 的取消、子进程回收、单工作槽恢复、超大输出拒绝和中文输入往返；既有命令回答、采集取消及任务运行时回归通过。未调用真实 LLM 服务，不代表 HTTP provider 或真实语音验收。
- 本轮复核完整导出 90335、特征对照 26080 均由工具确认仍在运行，尚无完成报告，未重启或提前训练。上一轮审阅产出了源码清单与五组回归证据，本轮继续落实实现。A01–A13 保持进行中，U01–U04 保留给隼人。

### A12 重训资产集合与运行时配置一致（最新）

- retrain_current_models 从运行时 DEFAULT_*_REPORT 配置导出预期报告路径到模型名映射，收尾要求实际单模型报告集合完全一致；不再只靠数量 14 判断交付齐全。最终资产清单附明确模型名。
- `output/architecture-implementation/a12-runtime-asset-set/summary.json` 通过：预期名称覆盖 MODEL_NAMES，模拟六阶段成功但产出 14 份错误位置报告时仍拒绝，已有失败中止/数据门禁检查保留。该编排测试不替代真实训练成功路径。
- 完整导出 90335 与特征对照 26080 最近轮询仍运行；未重启、未提前训练或替换资产。A01–A13 保持进行中，U01–U04 保留。

### A12 当前运行时模型统一重训入口（最新）

- 新增 retrain_current_models.py：先验证完整导出并写 validation.json，顺序运行六类训练脚本，将日志和阶段退出码写入独立输出目录；首个非零退出停止后续训练，不覆盖已有非空目录。
- 所有训练成功后检查每份单模型报告的 validation_status=matched，生成并重读资产完整性清单，要求 14 份资产；最后再次验证数据与训练前验收结果一致。输出不会自动替换当前模型或批准 active。
- `output/architecture-implementation/a12-retraining-entry/summary.json` 两组通过：编排测试验证缺完成清单时不启动训练、保留已有输出、失败阶段不继续；来源测试保持通过。编排成功路径及 14 个真实新资产尚未验收，待全量导出完成执行。
- 同时补 training_provenance 拒绝“有 validation.json 但无 manifest.json”的残留验收情形。完整导出 90335、特征对照 26080 最新轮询仍运行。A01–A13 保持进行中，U01–U04 保留。

### A12 数据验收报告与训练输入绑定（最新）

- training_provenance 读取同目录 validation.json（若存在），要求 training-export-validation-v1/passed=true，清单哈希与当前 manifest 相同，当前使用的表路径和内容哈希均匹配。模型报告保留 validation_status=matched 和验收报告 SHA-256。
- 不匹配时拒绝；未提供验收报告时明确 not_provided，不伪称验收完成。当前接口保留旧数据训练兼容，因此完整新数据重训仍须先显式执行验收并保存 validation.json，不能只凭训练命令成功宣告数据合格。
- `output/architecture-implementation/a12-validation-provenance-binding/summary.json` 两组通过，经过实际导出与 validate_export 产物验证绑定，故意修改已验收表哈希后训练来源读取拒绝。
- 完整导出 90335 与特征对照 26080 仍运行，尚无完成清单/对照报告；未启动新的全量训练。A01–A13 保持进行中，U01–U04 保留。

### A13 当前代码全量顺序回放通过（最新）

- 会话 68330 已正常退出，exit_code=0。`output/architecture-implementation/a13-current-full-replay/report.json` 全部检查通过；主抓包 666,921 包，31,726 个接受快照/决策往返，拒绝数 0。四个分场次另验证 5,163/4,879/3,166/5,071 个决策，合计 18,279。
- 共 50,005 次决策 JSON 往返，其中分场次数据来自主抓包子集，不能称 50,005 个互不重复的真实场景。历史窗口均为 1 秒源时间；每个接受状态经过当前生命周期、策略与内容身份恢复检查。
- completion-audit.json 核对六个输入文件哈希均未变化，启动清单中现有核心源码和 phase1_regression 脚本均未变化；八个独立导出/训练脚本及测试发生了已记录的后续修改，不被本次回放加载。stdout/stderr 已归档，verification-scope.json 更新为完成。
- 该结果证明当前录制数据上的顺序策略与决策契约检查通过，不证明新旧策略完全相同、连续语音/IPC/实时异步链或真实设备验收。训练导出 90335 与特征对照 26080 最新轮询仍运行。A01–A13 保持进行中，U01–U04 保留。

### A12 导出与运行时特征对照（运行中）

- 已启动独立特征对照进程会话 26080，经过实际 export_dataset/build_feature_row，使用同一状态和上下文调用运行时两种特征构建函数，对当前资产清单所需的共有列逐值比较。None/UNKNOWN 按类别缺失表达归一；结果写入 `output/architecture-implementation/a12-feature-parity-audit/report.json`。
- 启动时误将 sample_limit=64 理解为每场只计算前 64 行；随后确认 select_feature_label_indices 在整场计算结束后才抽样输出。实际对照覆盖全部遍历状态，导出主表仅采样，派生表仍按原流程生成。进程继续执行，不将其报告为前 64 状态抽样；脚本内初始 scope 文本须在完成后按实际数量纠正。
- 本轮尚无特征一致性结论，不能依据空 stderr 宣布通过。原回放 68330、完整导出 90335 仍运行，不使用该对照产生的抽样表作为完整训练数据。A01–A13 保持进行中，U01–U04 保留。

### A12 导出场次覆盖与窗口校验（最新）

- validate_export 要求主表覆盖全部配置 UID；仅总行数相符但遗漏配置场次时拒绝。派生记录不仅要引用存在的主表 ID，还必须具有相同 UID；主表与标签比较记录 ID 到 UID 的映射。
- 验证窗口版本和实际秒数，并要求当前记录身份版本；读取前后比较 manifest 内容，防止验证中清单发生变化。仍不证明原始抓包每一帧均已导出，完整导出进程终态及其统计另行核对。
- `output/architecture-implementation/a12-export-scope-completeness/summary.json` 实际小样本导出回归通过，新增缺失配置场次和错误窗口时长拒绝用例，已有篡改/分割/关联用例保留。
- 完整回放 68330、完整导出 90335 最新工具轮询均仍运行，未重启。A01–A13 保持进行中，U01–U04 保留。

### A12 完整导出验收入口（最新）

- 新增 validate_training_export.py / training_export_validation，要求完成清单与当前窗口版本，逐表核对声明行数、唯一非空记录 ID、UID 对应配置分割、主特征/标签 ID 集合一致、派生行关联主表。逐表留 SHA-256，并检查验证期间大小/修改时间未变。
- 验收入口输出独立报告，错误返回非零退出；不将仍在生成、缺 manifest 的目录视为可训练完整数据。其范围是数据结构/身份/分割一致性，不判断模型价值或标签正确性。
- `output/architecture-implementation/a12-export-validation/summary.json` 两组通过，补派生来源/文件变化检测后 `a12-export-validation-verified` 通过；补标签分割和记录 ID 篡改拒绝后 `a12-export-tampering-verified` 通过。用实际小样本导出产物验证，非全量导出验收。
- 全量回放 68330、全量导出 90335 最新轮询仍运行；待后者成功退出再执行完整目录验收，不提前启动模型训练。A01–A13 保持进行中，U01–U04 保留。

### A12 防守成本来源接入与运行时模型范围对照（最新）

- train_defence_cost_baseline 读取实际 features/labels 的 provenance，报告保留输入哈希、清单、窗口版本；其标签明确为 formula_proxy/human_validated=false。
- `output/architecture-implementation/a12-defence-provenance/summary.json` 两组通过：remaining_training_partition、training_provenance，范围是训练分割保护与来源处理，不代表当前完整数据重训完成。
- 当前运行时 14 模型对应六类训练入口均已加入来源透传：资源风险 4、驾驶质量 3、对手压力 3、趋势 2、策略分类 1、防守成本 1。其他离线实验模型入口不属于此项已接通范围，后续总体验收仍须核对。
- 完整回放 68330 与完整导出 90335 最新轮询均仍运行；下一阶段须在导出成功并核对分割后，实际重训至独立产物目录、逐报告检查来源和指标，不能把入口改动当成新资产已交付。A01–A13 保持进行中，U01–U04 保留。

### A12 策略分类与趋势模型来源透传（最新）

- train_strategy_action_baseline 从 strategy_action_features_path 指定表取得 provenance，报告保留导出窗口与标签来源，未存在来源字段时不推定。
- train_tyre_degradation_trend_baseline 将输入来源传给两个子模型报告；future_tyre_wear_delta 声明 telemetry_delta，future_grip_drop_score 声明 formula_proxy，两者均非人工验证标签，避免混淆真实遥测变化与公式构造目标。
- `output/architecture-implementation/a12-strategy-trend-provenance/summary.json` 覆盖训练分割入口、剩余训练分割、未来窗口及来源读取回归；此轮不是使用全量新导出训练完全部模型的证明。
- 导出会话 90335 已写出六张 CSV，检查时约 41 MB，完成清单尚未生成；与回放 68330 的 stderr 均为空。两个长期任务仍待终态与产物验收，不能将部分 CSV 当作完成数据集。A01–A13 保持进行中，U01–U04 保留。

### A12 驾驶质量/对手模型来源透传（最新）

- training_provenance 支持单表输入和指定清单表路径键；不需要 labels 的训练不伪造标签文件哈希。摘要保留实际解析后的输入路径。
- train_driving_quality_baselines 与 train_rival_pressure_baseline 透传 provenance 到各模型报告，保留窗口版本。两者重算的标签单独声明 proxy_derived_from_features/human_validated=false，区别于导出标签来源。
- 对手模型报告删除写死的 DEFAULT_FEATURES/DEFAULT_LABELS，改为实际输入路径；直接函数调用未提供来源时为 null/not_provided，避免给出错误位置。
- `output/architecture-implementation/a12-model-group-provenance/summary.json` 三组通过；补单表/指定清单键后，`a12-single-table-provenance/summary.json` 一组通过。范围为来源读取与既有训练分割回归，尚未完成使用当前全量导出的六模型重训验收。
- 回放 68330 与导出 90335 仍由原进程执行；策略分类、趋势、其他训练入口仍需继续补来源。A01–A13 保持进行中，U01–U04 保留。

### A12 资源模型报告继承导出来源（最新）

- 新增 training_provenance：读取 features/labels 文件 SHA-256，若存在同目录 manifest.json 则核对其声明的两个输入路径，保存清单内容 SHA-256、窗口、记录身份、标签来源及导出分割。缺清单时显式 missing，不推测版本；声明输入不匹配时拒绝。
- train_resource_risk_baselines 主入口在读 CSV 前取得 provenance，并传入各模型训练报告；报告同时保留 context_window_version/label_provenance，原有训练后的 partition_manifest 继续独立记录实际分割。直接调用训练函数未提供 provenance 时标为 not_provided。
- `output/architecture-implementation/a12-training-provenance/summary.json` 两组通过：training_provenance、training_entry_partition，覆盖缺失/已有清单、数据内容变化、错误输入拒绝及既有训练入口分割检查。尚未使用正在生成的完整导出执行新训练，不宣称新模型产物已交付。
- 最新检查：完整回放会话 68330、完整导出会话 90335 均仍运行；本轮新增来源模块仅由训练脚本使用，不被这两个已启动流程导入。其他模型训练入口的来源透传还需继续接入。A01–A13 保持进行中，U01–U04 保留。

### A12 训练导出对齐运行时窗口（最新，完整导出运行中）

- export_phase2_training_data 使用 UnifiedStateStore 默认容量与 recent_seconds(CONTEXT_WINDOW_SECONDS)，移除固定 12 帧历史对训练语义的影响；旧 max_history_frames 参数仅保留调用兼容，不再决定历史窗口。导出清单记录 source-time-weighted-v1、窗口秒数及 rule_derived/human_validated=false 标签声明。
- `output/architecture-implementation/a12-export-current-window/summary.json` 三组通过：export_partition、training_windows、training_entry_partition。实际导出测试观察时间窗口调用，并禁止旧 recent 路径，检查清单来源声明。
- 六个配置样本存在且 UID 不同，已启动不限样本帧数导出：`export_phase2_training_data.py --config asurada-core/training/configs/phase2_dataset_v2_extended.json --output-dir output/architecture-implementation/a12-current-training-export --sample-limit 0`。完整导出结果未判定通过；stdout/stderr 在 `/tmp/asurada-current-training-export.stdout` 和 `.stderr`，不覆盖旧导出或模型。
- 原全量回放会话 68330 仍运行，未改动其使用的核心与回放脚本；启动时全脚本 manifest 中本轮独立导出脚本及测试的哈希会变化，收尾审计须明确列出，不能声称全工作区哈希不变。A01–A13 保持进行中，U01–U04 保留。

### A12 已保存模型评估材料审计（最新）

- 读取当前全部 14 个运行时对应的报告，逐份保存报告路径与 SHA-256、validation_source、行数及治理字段，证据为 `output/architecture-implementation/a12-current-asset-evaluation-audit/report.json`。
- 14/14 均无 partition_manifest、context_window_version 和 label_provenance。字段缺失不证明历史训练必然发生泄漏，但不能作为当前整场分割、时间窗口和标签来源要求的完成证据。不得仅补写字段或批准文件替代重新导出/评估。
- 现训练脚本已调用 session_partitions，资源风险训练读取 session_uid 为字符串；后续须实际运行当前导出与训练链，取得可追溯的分割与评估产物，再审核是否有模型可进入 active。本轮没有重训或改变资产/默认模式。
- 全量回放会话 68330 最新 25 秒轮询仍在运行；未启动第二份回放，也未改动其运行源码。A01–A13 保持进行中，U01–U04 保留。

### A13 当前代码全量顺序回放（历史运行记录，终态见上方）

- 后续核验：会话 68330 再次轮询仍运行，未生成 report.json，stderr 为空。input-manifest.json 已记录六个输入文件的 SHA-256/大小/修改时间（合计 1,730,414,874 字节）；哈希期间检查文件未变化。verification-scope.json 明确本轮逐帧策略/记录覆盖范围及连续语音、异步实时链、IPC/设备不覆盖项。输入哈希任务会话 47381 已正常结束。
- 修正 phase1_regression 的旧固定 recent(12) 历史，改用与当前入口一致的 recent_seconds(CONTEXT_WINDOW_SECONDS)；生命周期拒绝的快照不再继续推理。每个接受的快照新增严格 JSON 序列化与 decode_snapshot 往返，核对完整 DecisionRecord。
- 已启动 `phase1_regression.py --snapshot-limit 0 --sample-snapshot-limit 0 --report-path output/architecture-implementation/a13-current-full-replay/report.json`，完整抓包与分场次均不限快照。进程会话 68330 最新轮询仍在运行；stderr 当前为空，不等于验证通过。后续须继续观察同一会话，不重复启动。
- `output/architecture-implementation/a13-current-full-replay/run-manifest.json` 保存启动阶段 346 个源码/脚本/模型报告与文本资产文件哈希；stdout/stderr 暂在 `/tmp/asurada-current-full-replay.stdout` 与 `.stderr`。回放为进程内解码、组帧、策略及记录检查，Null 音频，无真实 UDP/IPC/设备验收。
- 本轮结果待报告生成后逐项分析；A01–A13 保持进行中，U01–U04 保留。

### A01 决策内容身份与恢复一致性（最新）

- 新决策使用 identity_version=decision-content-v1，以完整记录（排除 decision_id 自身）的规范 JSON 计算 SHA-256，覆盖领域规则评估、动作、候选、仲裁和准入依据。相同快照/动作但不同批准依据不再共用旧的快照+动作 ID。
- restore_decision 对新身份版本核验内容哈希，拒绝内容不匹配及未知身份版本；历史无 identity_version 记录按 legacy 兼容。此校验用于内容一致性，不提供签名/来源认证，也不阻止有写权限者修改内容后重算哈希。
- `output/architecture-implementation/a01-decision-content-identity/summary.json` 四组通过，覆盖严格快照往返、准入/仲裁修改拒绝、同动作不同政策的身份区分、资产证据及模型质量消费者。移除旧 ID 计算的未用导入后，相关领域/LLM 消费者检查记录于 `a01-decision-identity-consumers/summary.json`。
- 尚需完整顺序回放和跨端契约验收；legacy 保留原始身份语义，不伪称已完成历史记录的内容认证。A01–A13 保持进行中，U01–U04 保留。

### A05 决策保留已核验的准入证据摘要（最新）

- validate_assets 返回每个活动模型的已核验摘要，包含证据内容 SHA-256、模型/特征 SHA-256、模型名、批准状态及时间窗口版本。StrategyEngine 保留初始化时的摘要，逐帧调试记录使用深拷贝，避免仅靠可变化的文件路径追溯。
- DecisionRecord 增加可选 model_admission，快照序列化/恢复保留该字段；旧 decision-v1 缺字段时恢复为空字典。记录对应启动时已验证的证据，删除/修改外部文件不追溯修改历史；当前不是运行中热撤销批准机制。
- `output/architecture-implementation/a05-admission-provenance/summary.json` 四组通过，新增真实引擎决策、严格 JSON 往返、历史兼容和证据文件删除后的摘要稳定性；`a05-admission-snapshot/summary.json` 既有快照契约通过。
- 尚待评估报告实质验证、批准撤销/重载策略和综合回放；不能把摘要哈希视为模型效果证明。A01–A13 保持进行中，U01–U04 保留。

### A05 活动模型证据与资产绑定（最新）

- StrategyEngine 初始化时调用 ModelAdmissionPolicy.validate_assets，逐个验证 active 模型证据文件；相对路径以该模型报告目录解析。读取真实模型清单并重新核验文件/特征哈希，拒绝缺失、未批准或不匹配的证据。
- 证据 JSON 契约为 version=model-admission-evidence-v1、model、approved=true、context_window_version、model_sha256、feature_schema_sha256、非空 evaluation_summary。当前默认模型模式未改变，未为生产模型生成批准文件。
- model_assets 回归复制真实资产到临时目录，验证相对路径和字段不匹配拒绝；完整 StrategyEngine 入口验证匹配证据可初始化、缺证据拒绝。临时 approved 文件仅为测试夹具，不代表模型效果已获批准。
- 既有固定预测/线程路由测试显式隔离资产门禁；首次 observation_lane 补丁误放在默认引擎夹具，导致局部导入未初始化异常，已纠正。`output/architecture-implementation/a05-admission-evidence-verified/summary.json` 四组通过：model_assets、model_admission、observation_lane、model_output_quality。
- 本契约证明批准记录绑定到哪些资产与窗口，不验证 evaluation_summary 的科学有效性。评估数据、标签、指标阈值、特征语义及真实模型价值仍需后续审核，不能据此宣布 active 效果验收。A01–A13 保持进行中，U01–U04 保留。

### A05 分类模型质量进入决策与观察轨迹（最新）

- StrategyActionModelRuntime 初始化并逐次重置 input/output quality；未加载、输入拒绝、输出异常与有效输出分别记录，避免上一推理的成功/失败状态残留。
- 同步仲裁输入增加 strategy_action_quality 的深拷贝；后台观察把质量与候选放在同一 results 中，由既有 ObservationLane 的 UID/epoch/snapshot 绑定约束。实时路径的后台模式显式标注 background_observation，不读取异步实例的瞬时质量作为本帧结果。
- 测试经过真实 StrategyEngine.evaluate，验证拒绝原因进入决策、后续恢复不修改旧记录；真实后台工作 Future 验证结果含绑定的质量信息。首次验证暴露初始化缺失及旧 observation_lane 活动路由夹具缺当前时间窗口声明；分别补初始化和夹具声明，未放宽生产准入。
- `output/architecture-implementation/a05-output-trace-verified/summary.json` 四组通过：model_output_quality、model_input_quality、model_admission、observation_lane。活动路由夹具仅验证线程路由，不证明实际模型准入或性能价值。
- 资产证据与训练特征一致性、完整顺序回放和最终设备验收仍待完成。A01–A13 保持进行中，U01–U04 保留。

### A05 模型原始输出有效性门禁（最新）

- 新增 model_output_quality，在排序/截断之前校验原始结果。策略分类器要求单样本、类别数匹配、有限非 bool 数值、概率范围 0–1、概率总和在 1e-5 容差内；非法输出不生成候选，记录 last_output_quality。
- 回归器要求单个有限数值，拒绝空结果、嵌套形状、bool、字符串、NaN/Inf；之后才沿用既有 0–100 分数截断。非法输出或预测异常返回 enabled=false/invalid_model_output，不携带 score，避免 NaN 经 min/max 转成正常分数。
- observe 与 active 都执行门禁；只拒绝当前推理，不永久禁用模型，后续正常结果可恢复。输入质量门禁保持不变。
- `output/architecture-implementation/a05-output-quality/summary.json` 三组通过：model_output_quality、model_input_quality、model_admission。新测试加载全部 14 个真实资产，注入非法输出与预测异常，覆盖观察/活动运行时门禁和恢复。测试内切换已加载实例的 mode 不构成资产 active 准入或模型价值验收。
- 仍待将分类输出质量完整接入决策轨迹、验证模型/训练特征与资产证据对应，以及当前架构综合顺序回放。A01–A13 保持进行中，U01–U04 保留。

### A03 下行播放状态的未知语义（最新）

- ConsoleVoiceOutput 与共享服务增加 playback-status-v1，区分 idle/playing/unknown；播放器状态查询异常返回 unknown。兼容 is_playing 在 unknown 时保守返回 true，避免现有 voice loop 将未确认的下行声音当成静音。
- SharedSpeechClient 查询使用独立 50 ms 预算，不修改命令超时；IPC 异常、缺版本或非法状态转为 unknown，保留错误类型。现有 voice loop 的 is_playing 调用直接使用此行为。
- 初次 speech_events 测试因测试适配器 call 缺默认 params 失败；修正适配器后 `output/architecture-implementation/a03-playback-status-verified/summary.json` 三组通过。补确认 idle、预算隔离及非法响应后，`a03-status-budget-verified/summary.json` 一组通过。客户端/服务走无监听 dispatch，IPC 超时为注入，非真实跨进程验收。
- 持续未知会保守影响语音输入可用性，需要真实音频/断连验收；本地输出锁和不合作后端调用仍无硬实时保证。A01–A13 保持进行中，U01–U04 保留。

### A03 切场、抢占、关闭共用停止确认（最新）

- bind_session 与高优先级抢占接入 _request_stop_confirmation。停止异常时仍完成切场记录、发布带 stop_error_type 的 cancel_requested；抢占请求保留排队，不释放旧所有权或重叠播放。
- shutdown 使用同一停止确认入口，之后通过可恢复的 _poll_completed_active 等待确认。超时或持续观测未知返回 false；同步/后续确认后才发布 cancel 并释放所有权。待播仍按关闭语义清理，后续显式关闭可重试。
- `output/architecture-implementation/a03-stop-paths/summary.json` 五组通过：新增 speech_stop_paths 覆盖三入口停止抛错、事件可见、所有权保留、待播策略及恢复关闭；既有 session、scheduling、driver、delivery_receipt 一起通过。没有调用真实音频或 IPC 监听。
- 本次处理抛异常和有限确认等待，不保证不合作 backend.stop 本身不会阻塞；外部 is_playing 的未知状态表达、跨进程关闭与真实播放器验收仍待完成。A01–A13 保持进行中，U01–U04 保留。

### A03 停止异常的未确认回执（最新）

- stop/cancel 活动任务先记录取消请求与发起者，再调用播放器停止。stop 或确认用 is_active 抛异常时保留所有权，返回 cancel_requested，控制回执为 pending；targets 附 error_type，不宣称停止成功。
- 停止活动失败不再阻止待播任务清理。新的停止请求可以再次调用播放器，成功后回执 completed，清除旧停止错误。未自动重试外部播放器副作用。
- `output/architecture-implementation/a03-stop-error-receipts/summary.json` 四组通过，覆盖停止抛错、待播清理和新请求恢复；补 stop/cancel 两种控制的确认查询异常后，`a03-stop-confirmation-verified/summary.json` delivery_receipt 通过。
- 以上为实际交互协调器与假播放器故障注入。切场/关闭/抢占路径的停止异常还需统一处理，真实播放器失联和 IPC 断连仍未验收。A01–A13 保持进行中，U01–U04 保留。

### A03 播放器观测异常恢复（最新）

- _poll_completed_active 对 backend.is_active 异常保留活动所有权，报告 playback_health.status=unknown、error_type 和 consecutive_failures；未知不生成 complete/cancel，也不启动待播任务。后续 tick 继续观测，成功后清除观测错误并按实际状态推进。
- 该异常原本会逃出 tick，触发 SpeechOutputDriver 停止线程；现在仅播放器观测异常在输出层处理，未对任意调度异常进行盲目重试。共享声音服务 health 返回 playback_health。
- `output/architecture-implementation/a03-playback-observation-recovery/summary.json` 四组通过；补服务 health dispatch 验证后，`a03-observation-health-verified/summary.json` 两组通过。实际调度线程配合故障播放器验证连续观测失败、活动所有权保留、无重叠启动以及恢复后不重建线程即可推进队列；服务检查未打开监听端口。
- 播放器 stop/is_playing 控制路径的异常、无响应后端及真实 IPC 状态仍需继续处理；持续未知不会被宣称完成。A01–A13 保持进行中，U01–U04 保留。

### A03 侧车返回状态与实际播放结果区分（最新）

- VoiceSidecarSpeechBackend 不再忽略 play_tts 返回值：必须是 AudioPlaybackResult、status=played 且 audio_bytes 为正整数（排除 bool），才接受为无错误终态。unsupported/accepted/failed、合成 completed 但未播放、空或非法字节数、缺返回对象均转为播放失败。
- 实际客户端 play_rendered_tts 在音频为空时会返回 completed/0，而非抛异常；新增用例经过该真实客户端方法、侧车工作线程和调度 tick，确认最终产生 failed，不把合成完成当作播放完成。测试没有访问网络或播放音频。
- `output/architecture-implementation/a03-sidecar-return-status/summary.json` 三组通过；补真实空音频客户端路径后，`a03-sidecar-empty-audio-verified/summary.json` playback_result 通过。覆盖正常返回、非播放状态、字节有效性和缺返回值。
- 本结果依赖客户端对 played 的报告，尚非声卡/扬声器实测。完整侧车流协议验证、IPC 断连与持久对账仍待完成。A01–A13 保持进行中，U01–U04 保留。

### A03 异步播放器终态传播（最新）

- SpeechBackend 增加 completion_error；MacOSSay/Piper 读取已结束进程的退出码，非零结果记录 player_exit_unsuccessful。VoiceSidecarSpeechBackend 读取已退出线程的 done/error，异常记录 sidecar_playback_failed，缺结果记录 sidecar_result_unavailable。
- 调度器仅在句柄不再活动后读取结果；结果读取异常为 backend_result_unavailable。失败生成 failed 事件、失败任务生命周期，释放所有权并允许队列继续推进，不加入正常完成历史。已请求取消的任务仍以 cancel 收尾，不把取消引发的非零退出当普通播放失败。
- DeliveryContext 将已开始但异步失败的回答原位更新为 failed，并移除请求跟踪；启动前失败仍不记成已说过。
- `output/architecture-implementation/a03-playback-result/summary.json` 六组通过。新增 playback_result_regression 启动真实无音频 Python 子进程，覆盖退出 0/7 的事件、上下文和所有权；实际侧车后台线程调用故障客户端，验证 start/failed 而非 start/complete。既有 delivery_receipt、speech_scheduling、speech_events、speech_session、phase3_voice 同时通过。
- 默认 completion_error 对未扩展的后端仅表示无错误报告；Null 后端也不证明物理播报成功。侧车返回结果语义、真实 Piper/系统音频、IPC 断连及持久对账仍需验证。A01–A13 保持进行中，U01–U04 保留。

### A03 播放器同步启动失败与恢复（最新）

- _start_envelope 成功取得 backend.start 返回句柄后才设置活动所有权；同步启动异常转换为 failed 事件，保留 backend_start_failed/error_type，不把异常文本直接写入回执。启动失败不会占住活动槽，也不会在后续 tick 被误认作完成。
- delivery-receipt-v1 增加 failed 状态；任务生命周期记录 failed；DeliveryContext 将失败任务从跟踪移除，不把未启动的文字加入已说过上下文。控制台查询/策略日志区分 FAILED 与 SUPPRESS。不自动重试失败播报，允许后续独立请求再次尝试。
- SpeechBackend.start 明确资源所有权契约：成功返回移交句柄，同步抛错前负责清理已启动资源。现有 Popen 与线程启动路径符合该调用边界；返回后的异步错误需另经句柄结果检查，尚未由本次实现覆盖。
- `output/architecture-implementation/a03-start-failure-recovery/summary.json` 四组通过；补实际 MacOSSayBackend 指向临时目录中不存在的可执行文件、验证 FileNotFoundError 到事件/任务失败后，`a03-start-failure-verified/summary.json` 三组通过。覆盖直接启动失败、后续新请求恢复、排队启动失败、上下文移除，以及失败后 tick 不产生 complete。
- 没有启动真实音频或访问供应商；播放器异步退出码/侧车错误的终态传播、跨进程对账仍待完成。A01–A13 保持进行中，U01–U04 保留。

### A03 同轮多任务状态转换完整性（最新）

- 新提交与旧待播过期同时发生时，过期待播在移除时发布 cancel，覆盖普通提交及抢占提前返回分支。tick 的既有过期回执保留，不重复发布。
- 旧任务完成、待播启动、新请求入队在同次调用发生时，事件流按 complete/start/新请求事件顺序记录；已发布的完成事件标记去重，原 completed_output 调试回执与任务生命周期仍保留。
- 高优先级抢占先标记 cancel_requested/cancel_reason；播放器延迟确认时发布停止请求，确认后为 cancel，不再误记 complete 或加入正常完成历史。
- `output/architecture-implementation/a03-concurrent-speech-transitions/summary.json` 五组通过；补原完成调试回执保留后，最终证据为 `a03-concurrent-transitions-verified/summary.json`。覆盖过期与抢占同轮、完成/启动/入队同轮及延迟抢占取消，相关 delivery、session、events 和既有 voice 回归一起验证。
- 本轮为实际调度器加假播放器的离线验证；完整事件持久化、重连对账和真实音频验收仍未完成。A01–A13 保持进行中，U01–U04 保留。

### A03 切场与关闭事件补齐（最新）

- bind_session 清理待播任务时发布 cancel，对仍持有的活动播报发布 cancel_requested；保留原任务的 session_scope，不把切场后的作用域写成旧播报来源。活动所有权仍等播放器确认后释放，后续 tick 发布终止事件。
- shutdown 发布待播取消及活动停止请求；同步确认停止时发布 cancel，超时则继续保留活动所有权，由后续 tick 确认。重复关闭已清理的输出不会重复发布终止事件。事件元数据携带 cancel_reason，消费者可识别切场/关闭原因。
- `output/architecture-implementation/a03-session-shutdown-events/summary.json` 四组通过：speech_session、speech_events、delivery_receipt、speech_scheduling。新增检查覆盖切场事件顺序与原作用域、立即/延迟关闭、重复终止去重。
- `output/architecture-implementation/a03-shutdown-context-verified/summary.json` 两组通过，实际协调器/调度器加假播放器验证关闭时待播跟踪被移除、活动回答在确认前仍为 started，确认后更新为 cancelled 并清理跟踪。
- 以上为进程内调用与假播放器验证；服务退出后事件流仍不持久化，跨进程断连对账、真实播放器和关闭路径的端到端验证尚待完成。A01–A13 保持进行中，U01–U04 保留。

### A02/A03 事件读取预算与控制通道隔离（最新）

- VoiceInputCoordinator 将事件刷新移至唤醒判断和快速意图识别之后；快速识别出的控制请求直接跳过读取，唤醒和忽略分支也不读取。普通查询在语义归一前刷新，预算取 100 ms 与整轮剩余时间的较小值，刷新后复查取消/超时。
- SharedSpeechClient 为事件读取复制客户端并设置独立超时，不修改其他语音命令的既有超时。ConsoleVoiceOutput 的本地读取使用限时锁获取，锁繁忙抛出 TimeoutError；DeliveryContext 沿用失败保留游标和后续重试行为。
- `output/architecture-implementation/a03-event-read-budget/summary.json` 六组通过：delivery_receipt、speech_events、voice_interrupt、phase3_voice_input、phase3_semantic_voice、phase3_wake_word。新增实际协调器用例验证停止/取消零次读取、普通查询尝试刷新；另验证客户端预算隔离及线程占用输出锁时读超时。补整轮剩余预算后，`a03-event-turn-budget/summary.json` 一组通过。
- 读取锁等待和 IPC 请求有预算；本地事件序列化仍按现有条数/字节上限约束，不能称硬实时 deadline。控制操作本身仍可能等待原有输出/服务锁，本次仅去除新增事件读取带来的前置等待；没有验证真实 IPC 和物理停止延迟。A01–A13 保持进行中，U01–U04 保留。

### A03 后续播放事件回写交互上下文（最新）

- VoiceInputCoordinator 在处理下一次语音请求、进行语义归一和 LLM 调用之前刷新事件；VoiceTurnInterruption 的输出代理透传 read_events，因此实际 voice loop 的既有协调器调用会经过此入口。DeliveryContext 最多跟踪 128 个本协调器请求，按 session_uid/epoch 过滤，忽略其他客户端请求。
- 排队任务的 start 补入响应上下文，complete 更新同一 request_id，已开始任务被取消时标注 cancelled；未开始就取消的任务不记为已经说过。ConversationContext 按 request_id 更新已有记录，不因旧任务后来完成而把它移成最新回答；重复游标读取不会重复添加。
- 读取失败保留游标用于重试；reset/gap 清除未决跟踪，不能推断完成；切场绑定清理旧对话。刷新为每轮处理前一页、有界工作，尚非空闲期后台持续消费；积压时 health=catching_up，后续仍需限时追赶和持久化。
- `output/architecture-implementation/a03-delivery-context-verified/summary.json` 五组通过，新增实际调度器事件验证排队开始、完成原位更新、重复刷新、读失败保留游标、重启和切场清理。附加 voice_interrupt 回归最初因遗留单引号 spoken 状态断言失败；改为 processed 且 delivery=started，并保留真实句柄数量检查后，`a03-delivery-context-interruption-verified` 两组通过。
- 仍待完整 IPC/真实 voice loop 运行验收、持续空闲消费、跨重启持久账本与控制对账。started 仍仅表示 backend.start，非完整物理发声；以上不完成 A03/A13 全包，U01–U04 保留。

### A03 共享语音异步事件游标接口（最新）

- ConsoleVoiceOutput 记录提交和 tick 产生的非 idle 生命周期事件；同批旧任务完成/取消先于新任务开始，避免重复记录同一事件。新增 read_events，SharedSpeechClient 与 SpeechService 的 events 操作已贯通读取入口。
- speech-events-v1 使用独立 stream_id 和递增 sequence，分页限制 1–128，保留上限 512 条/2 MiB。游标可重复读取且不消费其他客户端的进度；旧流游标标记 reset，超出保留范围或超大/非法事件造成丢失时标记 gap。调用者不能将 reset/gap 解释为任务完成。读取结果不会反向修改源记录。
- events 是只读操作，不进入命令幂等结果缓存，避免缓存大量重复事件页使内存保留量倍增。接口由输出锁串行保护；事件序列化失败报告丢失，不让已执行的播报因日志格式问题变成调用失败。
- `output/architecture-implementation/a03-event-cursor-stream/summary.json` 四组通过；补读取页缓存边界后，`a03-event-stream-bounds-verified/summary.json` 三组通过。新测试经过实际输出调度器/假播放器、tick、服务 dispatch 和客户端 read_events 方法，覆盖 start/enqueue、异步 complete/start 顺序、请求关联、游标分页、重启/丢失、超大事件和只读缓存。没有打开真实 IPC 监听，不能称完整跨进程验收。
- 当前为有界内存事件流，重启会显式丢失旧流；持久账本、客户端消费循环、对话上下文异步回写、重连与重复控制对账尚未完成，需继续接入实际 voice loop。场次切换/关闭等不经 _write_debug_payload 的事件完整性也需审计。A03/A13 仍进行中，U01–U04 保留。

### A03 控制操作与目标播报的因果回执（最新）

- stop/cancel 的 control-result-v1 独立绑定发起控制的 request_id，targets 保留被取消播报的 request_id/output_event_id。播放器仍活动时报告 pending；确认取消目标后报告 completed；没有可处理目标报告 no_op，保留原因。声音 delivery 状态不借旧目标事件声明控制请求已经播报。
- delivery_receipt 仅接受与当前请求匹配的 control_result，辅助控制结果也补 request_id；不再直接透传属于其他请求的控制结果。
- 活动播报保留 cancel_requested_by_request_id，后续 tick 收到实际停止确认而生成 cancel 事件时仍携带该关联。这为后续异步事件对账提供依据，不把提交时 pending 改写成已完成。
- `output/architecture-implementation/a03-control-operation-receipts/summary.json` 五组通过；补延迟确认因果检查后，`a03-control-causal-confirmation/summary.json` 三组通过。新增实际交互协调器/调度器加假播放器验证同时停止活动与待播目标、立即确认与延迟确认、重复停止无目标、外请求回执拒绝以及 tick 后因果关联。
- 完整 IPC 订阅、持久事件账本、重启后的控制对账及真实播放器停止延迟仍未验收；重复控制的多请求关联策略也需随账本收口。A03/A13 保持进行中，U01–U04 保留。

### A03 交互提交与播报回执分离（最新）

- VoiceInputProcessingResult 升级为 voice-input-v2。查询/控制提交返回 processed，不再直接声明 spoken/control_executed；新增 delivery-receipt-v1，按当前请求匹配的输出事件报告 started/queued/suppressed/cancelled/completed/idle/unknown，并保留控制器原始 control_result。缺少事件或事件属于另一请求时为 unknown，不能借上一任务的完成事件宣称本请求成功。
- 对话响应历史只记录与当前请求匹配的 started/completed 内容，并附 delivery_status；queued/suppressed 不再污染“已说过”的上下文。started 表示 backend.start 边界，不表示物理声音完成；Null/假播放器也不构成真实音频验收。
- 6 组既有路由、控制、语义、唤醒和辅助回归通过：`output/architecture-implementation/a03-delivery-receipt-migration/summary.json`。这些既有检查同步迁移为 processed，具体播放语义另由新增测试验证。
- `output/architecture-implementation/a03-delivery-receipt-behavior/summary.json` 三组通过，新增实际 VoiceInputCoordinator + ConsoleVoiceOutput + HoldingBackend 用例确认首条 started、第二条 queued、重复 suppressed、仅已开始回答写入历史；错误请求完成与空回执保持 unknown。
- 本回执为提交时快照，尚需接入异步排队启动/完成事件的持久订阅与上下文回写、取消控制针对旧目标的独立操作回执、错误分类及 IPC 断连对账。当前不伪造这些事件或宣称完整播放状态闭环完成。A03/A13 继续进行中，U01–U04 保留。

### A08 澄清回答共享策略（最新）

- 新增 answer_policy.render_racing_response，由 LlmExplainer 和共享语音服务的适用性函数共同使用。比赛事实继续验证引用与数值；needs_clarification 使用 query_scope/lap_selection/segment_selection 三种受控问题，不要求空问题提供比赛证据，也不对“哪一圈”误做数值声明检查。
- 澄清类型不直接放行模型原文：实际发出的文本由模板生成；非空 claims 或未知 clarification_field 被拒绝。语音服务再比较最终 persona 文本，修改播报内容仍被拒绝，原有场次、时效和上下文适用性检查保留。provider 指令已说明可选澄清字段和禁止澄清携带结论。
- `output/architecture-implementation/a08-shared-clarification-policy/summary.json` 五组通过（answer_policy、llm_evidence、llm_numeric_claims、phase3_companion_mode、phase3_llm_explainer）。新测试经过实际 explainer、VoiceInputCoordinator override 转换和服务端共用适用性函数，覆盖三个模板、模型断言替换、文本篡改及伪造 claims/字段拒绝。更新 provider 指令后，`a08-clarification-provider-instructions` 三组相关回归再次通过。
- 这是无本地监听的调用链验证，不是完整 IPC、真实供应商或真实音频验收。companion 测试通过仅代表已有隔离范围；共享语音服务尚未完成独立陪聊策略、无赛况可用性及控制回执/实际播放状态契约。A08/A03/A13 仍进行中，最终 U01–U04 保留。

### A05 模型物理输入质量与逐次推理准入（最新）

- 策略分类器与资源/驾驶/对手等回归器在编码前共用 physical-inputs-v1。仅检查实际特征列中的 throttle/brake/steer/ers_pct/tyre_wear_pct，沿用领域范围规则；缺失、bool、字符串、非有限或越界值转换为 None，编码器保留为 NaN，避免转成真实零或 bool 数值。
- observe 模式可继续做缺失值推理用于分析，回归结果包含 input_quality；active 模式若所需上述字段不可用则拒绝本次推理，不调用 booster，且不将模型永久禁用。策略分类器返回空候选并保留 last_input_quality；回归器返回 enabled=false 及 required_physical_input_unavailable。此策略目前不开放“缺失条件下也允许 active”的例外，相关能力须另有评估契约。
- `output/architecture-implementation/a05-physical-model-inputs/summary.json` 三组回归通过。新用例加载全部 14 个真实模型资产，165 个非法输入案例验证实际编码为 NaN、观察推理可执行、active 在调用 booster 前拒绝；另验证有效零不被拒绝。测试内切换已加载实例的 mode 只验证输入门禁，不构成模型 active 业务准入。
- 录制输入验证：原编码对照脚本仍传入 recent(12)，已修正为生产使用的 recent_seconds(CONTEXT_WINDOW_SECONDS)。`output/architecture-implementation/a05-model-input-current-window-parity/summary.json` 通过；14 模型的 70 个编码边界对照无差异，四类录制场次共 141 个抽样状态的优化/原 DataFrame 编码路径，其策略消息和 debug 对照无差异。该结论是新版本两种编码路径一致，不是新旧架构策略行为完全不变，也不是完整顺序回放。MotionEx 策略回归另在 `a05-model-input-replay-parity` 通过。
- 尚待覆盖其他物理特征、历史覆盖率、训练/运行特征语义绑定及模型输出合法性；不能据此声称所有模型输入质量和模型价值已验收。录制输入的编码对照另行记录。A01–A13 仍在推进，U01–U04 保留。

### A04 组帧驾驶输入质量接入策略链（最新）

- CarTelemetry 的 throttle/brake/steer 不再补零：缺失为 null，bool、字符串、非有限值和越界值也为 null。raw.input_quality 逐字段保留来源、观测时间、单位和 observed/missing/invalid；历史上下文与组帧共用同一驾驶输入验证器。
- 动态标签只执行证据齐备的判断；缺输入保留 unavailable，不因没有风险标签而认定 stable。独立成立的重刹或滑移等标签仍保留。领域版本为 domain-v3，已有旧版本评估缓存会重新计算。
- 新回归从 CaptureSnapshotAssembler.push 的必需包组装开始，经过严格 JSON 序列化、decode_snapshot、历史上下文、领域评估；额外经过实际 StrategyEngine.evaluate（模型显式 disabled）验证全缺输入不会崩溃且驾驶模式/领域状态保持 unknown/unavailable。覆盖三个字段各自缺失/非法、真实零、来源和独立重刹标签。
- `output/architecture-implementation/a04-packet-input-strategy-verified/summary.json` 五组回归全部通过：packet_input_quality、source_time_context、domain_assessment、phase1_motionex_strategy_detail、model_admission。此前 packet_freshness 也在 `a04-packet-input-quality-verified` 通过；这些是离线生成包与规则链验证，不是原始二进制捕获完整回放或模型缺失值验收。
- 下一步继续其他关键字段质量传播、原始二进制/CSV/模型消费者及多端回放验证。历史稳定性比例对 unavailable 的覆盖政策和风险数值表达仍需收口；本次不宣称全域缺失语义已完成。A01–A13 保持进行中，U01–U04 保留。

### A01/A04 资源数值有效性贯通领域、问答与证据（最新）

- 根据最新源码审阅的复现结果，领域入口拒绝 bool、数字字符串、负数和非有限数值；ERS 与轮胎磨损另外要求 0–100。真实 0 和 100 仍有效。燃油数值也不再将 bool/字符串当作观测。
- 领域版本升级为 domain-v2，燃油规则版本为 fuel-v2；评估缓存仅在规则版本、快照和阈值一致时复用，旧版本缓存重新评估。
- 固定 ERS/轮胎状态、保胎建议和磨损展望在 unavailable 时明确返回数据不足，不再进入健康/充足文案。LLM 摘要中的玩家和对手 ERS/磨损使用同一百分比验证器，非法值为 null，不进入可引用字段集合。
- `output/architecture-implementation/a01-resource-validity/summary.json`：5 passed、0 failed、0 skipped（domain_assessment、capability_handlers、llm_numeric_claims、model_admission、source_time_context）。新增用例覆盖缺失/bool/字符串/负数/越界/NaN/Inf，穿过领域评估、实际问答、LLM 引用字段和规则候选生成；另覆盖合法边界及旧规则缓存重算。
- 本轮没有完成完整 StrategyEngine.evaluate 的所有模型/规划分支、多端投影和原始包的质量传播，不能据此声称非法值已经在全链消除。组帧补零、模型特征消费、通用风险分数的 unavailable 表达、回答类型/交付状态、LLM 底层取消、参数化工具产品入口继续留在 A01–A13。
- 最新审阅建议基线为 `doc/ASURADA_ARCHITECTURE_ADVICE_CURRENT_CN.md`，详细工作包表和最终 U01–U04 验收任务保持不变。下一步从组帧质量向下游传播，避免已经补出的零绕过本轮验证；随后收口澄清/陪聊/比赛事实回答策略。

### A04 驾驶输入缺失语义与覆盖率（最新）

- 时间窗口对 throttle/brake/steer 单独统计有效权重；缺失、非有限值、bool 和越界数值不作为零参与平均。油门/刹车范围 0–1，转向 -1–1 并以绝对值计算负载。
- 某字段有效观测不足已覆盖历史的一半时标记 unavailable；对应加权因素不增加策略分数，驾驶模式为 unknown。真实零仍有效；无历史但当前有效值标记 instantaneous，覆盖为零。ContextProfile.input_quality 对各字段记录覆盖时长和质量。
- `output/architecture-implementation/a04-context-input-quality/summary.json` 五组离线回归全部通过。新增覆盖 None/NaN/Inf/bool/越界、真实零、稀疏油门不足以代表整个窗口；既有频率对照、模型准入、场次路由与 MotionEx 策略回归一起通过。
- 完整链仍有待办：packet_snapshot.py:247–249 的 telemetry 字段仍可补零，历史日志已经丢失的来源不能由下游恢复。本轮改善已显式缺失的输入，不声称所有实时字段都已实现质量传播。下一步从组帧输入来源继续收口；整体 A04/A13 未完成。
- 此轮没有运行此前受拒绝的本地监听集成测试。真实比赛、语音、设备和训练价值 U01–U04 原样保留。

### A04/A05 源时间上下文窗口（最新）

- 实时 pipeline 与 app 的 replay/CSV 入口改用统一一秒 recent_seconds；StrategyEngine 内部不再再次截取最近 12 帧。context_samples 按源时间加权状态占比和驾驶输入，每段最多持有 250 ms，不把长缺口全部当作真实观测。
- ContextProfile 记录 source-time-weighted-v1 和实际 history_coverage_ms。单帧可提供瞬时上下文但历史覆盖为零；重复时间、跨场/epoch、未来样本不增加权重。缓冲区仍有容量上限，覆盖时长如实反映不足，不伪称一定覆盖整秒。
- ModelAdmissionPolicy 记录 context_window_version，StrategyEngine 拒绝未声明新窗口评估的 active 模型。默认模型仍为 observe/disabled。当前是版本准入要求，不证明声明关联的真实评估质量；完整数据和模型再评估仍需执行。
- `output/architecture-implementation/a04-source-time-context-verified/summary.json` 五组无需网络监听的回归通过。新增 10/20/60 Hz 相同场景的时间占比和驾驶上下文一致性，缺口覆盖、重复、外场/未来排除；计时回归改用实际 UnifiedStateStore，模型回归补旧窗口 active 拒绝检查。
- 本轮可在默认沙箱完成，没有绕过此前服务集成测试的自动审批拒绝。A08 本地监听集成测试仍未启动；当前窗口语义改动还需全量合同、完整顺序回放与模型资产评估，旧 114 项通过结果不覆盖本轮。字段缺失数值语义和最低覆盖率领域降级尚待完善。A04/A05/A13 仍进行中，U01–U04 保留。

### A08 数值强制策略与服务端复核（最新）

- 比赛解释中无 claims 的回答若含阿拉伯数字、百分之或常见中文数词加数量单位，返回 llm_invalid_evidence；claims 模板外的同类数值也拒绝。普通“下一圈”等关系描述不作为数量声明。此词法策略不声称证明所有中文隐含数量、定性判断或因果关系。
- VoiceInputCoordinator 保留验证后的原始 answer_text。共享输出适用性函数再次使用同一 render_claims 验证声明，核对 input_event.request_id，并通过同一 persona 渲染函数比较最终 speak_text，拒绝中间修改声明数值、播报文本或请求身份。重复 sidecar 验证保留原模板，不允许借 metadata.template 绕开数值检查。
- `output/architecture-implementation/a08-claims-enforced/summary.json` 五组回归通过（新增服务端篡改测试加入前的结果）；`a08-claims-pure-validation/summary.json` 两组当前纯函数/实际 explainer 回归通过，新增覆盖旧阿拉伯数字、中文数量、百分比拒绝，以及实际 voice override 转换后的服务校验和三类篡改拒绝。git diff --check 通过。
- 计划运行的 `a08-claims-service-verified` 四组本地服务集成回归未启动：require_escalated 自动审批返回 usage limit，明确禁止绕过。没有进程句柄，不可将其视作正在运行或已通过。当前只完成不需要监听的验证；待额度/审批条件恢复后按原命令运行完整集成检查。
- 尚待完整合同复验、真实 provider schema 验证、澄清/伴聊分流以及未覆盖数量语义；114 项全绿基线早于本次数值变更。A08/A13 仍进行中，U01–U04 保留。

### A08 结构化数值声明与程序渲染（最新）

- LlmResponse 与 provider JSON schema 新增 claims，实际模型输入提供规范字段单位映射和 request_id，指令要求使用 {{id}} 占位。支持 value 与同单位 difference，两项来源按声明顺序相减；最多八项、精度 0–3、有限数值、Decimal ROUND_HALF_UP 舍入。
- 实际 LlmExplainer 在引用校验后核验 claims 的字段、单位、数值、精度、请求绑定和 reason_fields，并以程序生成的数值及单位替换占位。模板和 claims 保留在响应，语音 response_override 携带它们；HTTP sidecar 两层验证可重复执行，不能把已渲染数字替换成另一数字后通过。
- `a08-numeric-claims/summary.json` 五组回归通过，新增 13 项实际 explainer 检查覆盖正确差值、模板保留、二次校验、错数/错单位/反向差值/绑定缺失/漏报来源/额外阿拉伯数字/缺占位/重复 ID/非有限数值/渲染篡改；`a08-numeric-provider-contracts/summary.json` 五组适配器合同回归通过。均位于 output/architecture-implementation，使用假后端，没有云模型验收。
- 迁移尚未闭环：无 claims 的旧响应目前仍按旧引用规则处理，不能声称所有数值都已核验；claims 外中文数词与因果表述也未被该机制证明。下一步需执行生产数值强制策略、处理旧测试/后端返回兼容、服务端再核验与澄清/伴聊分流，不能仅以新字段存在标记 A08 完成。
- 本轮模型适配器回归验证既有合同仍可用，不证明真实供应商已遵循新增 claims 指令。A08/A13 继续进行中，U01–U04 保留。

### A13 当前版本完整合同回归（最新）

- `output/architecture-implementation/contracts-integration-5/summary.json`：单次完整 contracts 运行 114 passed、0 failed、0 skipped，进程退出码 0。包含当前新增取消、容量、跨客户端停止、权威场次、同场问答/策略、排队启动复核和辅助窗口，以及既有模型、训练、工作流、多端传输合同。
- `source-manifest.json` 记录 306 个源码/配置文件哈希；运行结束重新比对没有源码变化。`coverage-audit.json` 比对自动发现的 114 个 contracts 与实际结果集合，缺失/额外均为空，未靠子集通过替代全套结果。
- 模型编码检查包含实际模型资产的边界预测与录制样本抽样对照，但 contracts 明确排除 phase1_regression；本轮不是完整顺序回放，也不替代干净安装、平台启动和真实设备验收。模型资产本身未纳入本次源码 manifest。
- 本轮核对了下一步 A08 改动范围：LlmResponse / JSON schema / provider 请求与抽取 / LlmExplainer 验证 / voice response_override 需共同承载数值声明，不能只增加独立验证器。引用存在校验不证明数值或推导正确，尚待实现。
- A01–A13 均不因本轮回归通过而自动完成；U01–U04 继续保留。下一步推进结构化结论校验与完整产品调用链。

### A03/A04 辅助提示距离与时间窗口（最新）

- 播放前 guard 现在接收实际 SpeechJob；服务端对制动点/弯道挡位 source_kind 使用专属适用性判断。制动提示原快照最多 0.35 秒，挡位提示最多 0.75 秒，不能使用普通问答的 15 秒预算。
- 同时检查同圈同场、有效距离和速度、无倒退，以及移动距离不超过当前速度乘对应窗口。目标点已跨过时拒绝；没有距离/目标/速度证据也拒绝。窗口为工程配置常量，不声称已通过真实驾驶体验标定。
- `output/architecture-implementation/a04-assist-window/summary.json` 五组回归通过。新增 16 项确定性检查涵盖两类提示的正常、过期、越过目标、前进过远、倒退、跨圈、缺距离和无效速度；既有真实辅助控制器、共享队列和实际策略生成回归保持通过。
- 此次检查基于生成遥测和假/null 播放器；新增窗口分支为定向验证，完整真实辅助提示经过服务端和设备的验收仍保留。没有解决网络 TTS 合成期间到实际发声的继续变化、attack_mode 专属窗口或长期语义/数值核验。A03/A04/A08/A13 仍进行中，U01–U04 保留。

### A01/A04 主动策略候选决定绑定与适用性（最新）

- 配置权威来源的共享服务对 emit 要求原始/最新快照都有绑定 DecisionRecord。提交 messages 必须等于记录 actions，debug 中实际用于发声的 final_voice_action 必须等于记录 arbitration 对应值，拒绝脱离决定的动作或播报文本。
- 提交与排队启动前复用同一校验：原始快照年龄、关键上下文、主动作及 final_voice_action 仍须受最新核心决定支持。不比较随每帧变化的整个 decision_id；无关速度变化且建议一致时可继续播放。
- `output/architecture-implementation/a04-strategy-applicability/summary.json` 四组回归通过。新增用实际 StrategyEngine 生成 ERS_LOW，真实本地 IPC 在查询后排队；ERS 恢复使旧候选不再启动，无关速度变化仍启动。分别验证修改动作标题和播报文本被拒绝。问答队列、场次权威和调度回归一起通过。
- 当前为受信任本机契约一致性，不是来源认证或签名。制动点/弯道挡位等输出控制器生成的辅助提示仍需专属距离/时效复核，DecisionRecord 内容版本与完整数值推导验证仍待收口。A01/A03/A04/A08/A13 保持进行中；U01–U04 保留。

### A03/A04 排队任务播放前复核（最新）

- ConsoleVoiceOutput 的 speech envelope 保留 start_guard；service 在输出锁内绑定当前提交的校验闭包，只有新提交获得该闭包，既有待播任务保留原始参数。参数先深拷贝，避免后续状态/日志修改改变校验依据。
- 所有 backend.start 之前运行 guard，重新检查服务关闭、跨客户端停止屏障、权威场次/时效及问答事实适用性。校验失败产生 suppress / delivery_no_longer_applicable 生命周期事件，不调用播放器，也不使独立调度线程退出。
- 原有提交校验提取为同一函数，提交与真正开始播放复用，避免两套判定规则。停止与队列开始通过输出锁排序；guard 不反向获取 service dispatch 锁，避免锁顺序反转。
- `output/architecture-implementation/a03-queue-recheck/summary.json` 四组回归通过。新增实际本地 IPC 加假播放器检查：轮胎问答提交时有效并排队，等待期间轮胎数值改变则不启动并产生抑制事件；仅速度变化仍正常启动，调度器持续运行。既有共享服务、场次校验和调度回归通过。
- 此处“播放前”指 backend.start 前，不等于云端合成完成后声卡真正发声的原子时点。原子文件发布/观察窗口、主动策略候选的同场适用性、结构化数值核验与无赛况伴聊授权等仍待完善。A03/A04/A08/A13 未标记整体完成；真实音频与设备 U01–U04 保留。

### A04/A08 同场问答交付适用性（最新）

- PublishedSessionProbe 新增 read_snapshot，合同/文件大小/身份/时效校验后返回同一次读取的发布内容；原 scope 调用接口保持兼容。输出服务使用这份最新快照比较问答适用性。
- 普通问答拒绝原始回答快照超过 15 秒或来自未来；检查赛道、圈、位置、轮胎类型、旗号、进站/处罚及共享风险结论变化。固定能力用原 handler 在旧/新状态重新生成结果，只有影响结果的变化才拒绝，不以整个 snapshot hash 的每帧变化为条件。
- LLM response_override 的声明 reason_fields 必须在旧/新摘要都存在且值相同；未知、歧义或发生变化的证据拒绝。沿用已有 evidence_fields 与摘要生成，不建立第二份字段别名规则。它只检查声明依据仍适用，不证明自然语言数字和因果说明正确。
- `output/architecture-implementation/a04-query-applicability-final/summary.json` 四组回归通过：相同 scope 轮胎回答数值变化拒绝、无关轮胎变化仍允许燃油回答、LLM ERS 证据变化拒绝、无关速度变化仍保留 ERS 依据、旗号变化拒绝、最新发布有效但原回答过期拒绝，以及既有能力 handler/场次取消/共享输出回归。
- 当前在服务接收问答时检查；排队后真正开始播放前还需再次验证。主动策略候选、无比赛依据的澄清/伴聊授权及字段质量完整契约仍待继续；不能将此项当作全部 A04/A08 完成。U01–U04 保留。

### A03/A04 输出服务校验接入侧场次发布（最新）

- 实际 live CLI 启动共享语音时，传入 AppConfig.replay_log_dir/latest_snapshot.json 作为固定 session_source。服务健康信息公布该路径；启动器复用外部或已有服务时检查来源，不接受来源不一致的服务。
- 配置来源的服务在 bind_session、策略播报和语音回复前，读取核心原子发布的最新场次与 epoch，检查合同和 15 秒时效；客户端旧 scope 不能覆盖服务状态。文件缺失、格式无效、过期时拒绝普通交付，stop/cancel 仍可执行。
- 独立 50 ms 观察器检查最后接受的场次，切场/倒带/发布失效时请求停止旧播放和待播队列，使用与交付相同的串行锁；服务退出收尾观察器，异常可从 authority_error 查看。底层物理停止仍遵循现有确认机制。
- `output/architecture-implementation/a04-speech-authority-final/summary.json` 四组回归通过，包括真实启动器固定来源、错误来源拒绝复用、本地真实 IPC 的旧场绑定/交付拒绝、发布变更停止旧播放、过期发布拒绝、缺发布仍能停止，以及既有共享队列/停止屏障。
- 本次来源仍为异步原子文件发布，不是跨进程原子事件总线；读取和播放之间仍有观察窗口。同 scope 事实变化的适用性、伴聊/离线模式的显式授权、接入所有权租约、断流与事件契约仍需继续收口。无 session_source 的显式独立服务仍供测试/离线使用，生产 live 入口强制匹配来源。A03/A04/A13 仍进行中，U01–U04 保留。

### A03 跨客户端停止屏障（最新）

- 共享播报服务在串行 dispatch 内记录 stop/cancel 屏障。所有非停止播报请求必须携带合法 produced_at_monotonic，产生时间不晚于屏障则拒绝；屏障在实际停止前建立，即便播放器停止失败也不会让旧任务重新入队。服务新实例也拒绝其创建之前的候选。
- VoiceTurnInterruption 在 begin 记录产生时间，输出代理保留该时间；LiveSpeechSubmission 在复制/排队前记录时间，后台发送保留它。SharedSpeechClient 使用独立浅拷贝绑定时间，避免并发请求互相修改。停止后的新请求仍可正常播报，不是永久静音。
- 独立客户端回归暴露 macOS/Python 3.9 的 time.monotonic 进程起点问题；新增 speech_clock 显式读取 POSIX CLOCK_MONOTONIC，用于本机跨进程比较。线程内预算和队列年龄继续使用原本单调时钟。
- `output/architecture-implementation/a03-stop-barrier-final/summary.json` 四组回归全部通过。覆盖两个独立进程共享所有者、另一客户端停止后旧轮次拒绝、停止前排队但停止后才发送的候选拒绝、新请求允许、缺失/未来/非有限时间拒绝，以及既有停止与队列行为。
- 此屏障面向受信任的本机客户端，时间字段不是外部鉴权凭证。缺少新时间字段的旧调用明确失败，部署需同时更新客户端和服务。尚未完成场次接入权威、同场事实变化校验、停止高优先级通道和统一持久轨迹；模拟播放器证据不等于真实音频停止验收。A03/A04/A13 仍进行中，U01–U04 保留。

### A02/A13 实时 TCP ASR 服务端生命周期（最新）

- 实时 TCP 服务端采用八个连接处理名额、八个监听 backlog，超出立即关闭；单次 socket 读写 2 秒，单帧 4 MiB、连接累计输入 16 MiB，整连接默认 60 秒。未退出的 provider/close 仍占原名额，不因取消而新开无限线程。
- handler 创建 TaskContext，支持该能力的实际 provider 在 open_realtime_session 收到同一上下文。独立观察客户端 EOF、总预算和服务关闭；取消时 shutdown 客户端连接，并通过 context 让已有 Doubao WS session 停止。所有输出前检查 context，旧结果不会在取消后发送。
- 重复 start 明确拒绝并关闭原 session，未知消息和无效 Base64 明确失败。finally 取消上下文、收尾观察线程、关闭当前 provider session。非协作 provider 不声称已被杀死，它保留有界连接槽直到实际退出。
- `output/architecture-implementation/a02-stream-server-verified/summary.json` 三组回归全部通过。新增实际本地 TCP 检查涵盖重复 start、断连/服务关闭取消正在打开的 provider、总 deadline、超长帧、八个不合作调用在取消后继续占位且第九个连接被拒绝，以及 session/观察线程收尾；既有实时识别客户端和 HTTP 服务协议回归保持通过。
- 本次使用本地假 provider，没有真实云端、麦克风或设备。初次 DNS/握手的即时取消、跨进程场次权威与停止屏障、统一发布验证仍待完成。A02/A03/A13 未标记完成，U01–U04 保留。

### A02/A03 批量 WebSocket provider 取消与音频分块（最新）

- Doubao batch WS 后端声明 supports_task_context，服务端现有 dispatcher 会传入整轮 context。连接超时受剩余预算约束；发送、接收、分块间等待均检查取消。独立观察线程 abort 阻塞连接，finally shutdown 并等待观察线程退出，取消后的迟到连接不发送音频。
- 每段接收与最终等待有固定截止时间，持续 partial 不再无限续期。正常 provider 状态、转录、追踪 ID 和 metadata 保留；provider 错误仍报错。
- 测试发现原音频函数先将 WAV 归一化为 PCM，导致 WAV 解包分支不可达，PCM 也未按 chunk_ms 分块。现在 WAV 在内存中解包并校验 16 kHz/单声道/16 bit，PCM 按完整采样和配置时长分块；压缩格式保持整段。格式不符明确拒绝，不把错误采样率声明为 16 kHz。
- `output/architecture-implementation/a02-batch-ws-verified/summary.json` 四组回归全部通过。新增覆盖阻塞发送/接收取消、deadline、迟到连接、分块等待取消、正常结果与 provider 错误、连接与线程收尾、实际 dispatcher 上下文传递，以及真实 WAV 字节解包和 PCM 样本完整性。
- 证据使用假 WebSocket 模块和生成音频，无真实云端/TLS/麦克风。首次 DNS/握手取消、实时 TCP 服务端容量和生命周期、统一场次权威及跨客户端停止屏障仍未完成。A02/A03 保持进行中，U01–U04 保留。

### A02/A03 批量 Doubao HTTP provider 接入取消（最新）

- `DoubaoFlashHttpSidecarAsrBackend` 现在声明并消费 TaskContext，服务端实际 dispatcher 会把请求上下文传入该 provider。带 context 的请求使用可取消 HTTP 传输，连接/读取时限同时受配置和任务剩余预算约束；无 context 的原 requests 路径保留。
- 可取消传输支持显式认证头与响应头返回；provider 维持原 API key / app/access key 组装、资源 ID、请求 ID、音频与模型参数，按大小写无关方式读取 provider 状态和日志 ID。内部 X-Asurada-Timeout-Ms 不发送给 provider。
- `output/architecture-implementation/a02-provider-http-verified/summary.json` 四项回归全部通过，新增七项检查。完整本地链路为实际 VoiceSidecarClient → 实际 VoiceSidecarServer → 实际 Doubao HTTP 适配器 → 本地假 provider：验证正常协议、认证/资源字段、响应追踪、音频/选项，以及客户端取消后上游 socket 断开、两层取消观察线程退出。
- 此次使用测试 key、假音频和本地 HTTP，无真实 provider/TLS/麦克风验收。它证明客户端取消传播到 HTTP provider 连接关闭，不证明远端供应商收到音频后的内部计算已停止。
- 仍待统一：批量 WebSocket provider、实时 TCP ASR 服务端、DNS/握手前取消、其他执行通道。A02/A03 未标记完成，U01–U04 保留。

### A02/A13 批量 ASR 服务端预算、断连和容量限制（最新）

- HTTP sidecar 改为最多 16 个连接处理线程，超出立即关闭连接；已接入连接读写超时 2 秒与 JSON 请求体 16 MiB 上限，超大声明在读取正文前拒绝。此处是有界连接治理，不声称所有 HTTP 慢速分段读取已有总 deadline。
- `/v1/asr/transcribe` 使用进程级两个无排队执行名额。客户端携带剩余毫秒预算，服务端以上限配置（默认 15 秒）截断。等待中检查任务 deadline、客户端 EOF 和服务关闭信号；超时返回 504，满容量返回 503，断连取消上下文不写回结果。
- 未退出的 provider 在超时/断连后仍占执行名额，避免弃置调用累积。支持 `supports_task_context` 的 provider 收到 context；其余后端仍由有界执行器承载，未假定其能够物理取消。
- `output/architecture-implementation/a02-server-asr-final/summary.json` 四项回归，新增七项实际 HTTP 服务检查：断连传递取消、两个非协作慢调用超时占位、第三请求过载、健康接口可用、实际退出后恢复、超大正文拒绝、24 个空闲连接的上限。全部使用本地回环和假 provider，无云端或音频设备。
- 尚待完成：真实 provider 的 context 消费、实时 TCP 服务端容量/生命周期、服务端音频/TTS 等其他执行预算、DNS 与首次输入接收的总时限。A02/A13 仍进行中，U01–U04 保留。

### A02/A03 批量 ASR HTTP 与音频转换取消（最新）

- `VoiceSidecarAsrRecognizer` 向实际 `transcribe_asr` 传递整轮 context。带 context 的 HTTP 请求采用显式拥有 socket 的 http.client 传输；连接/发送/响应头/响应体共享请求配置与整轮预算的较小值。取消观察 shutdown socket，即便 Connection: close 导致 HTTPConnection 清空 sock，保留的引用仍能解除响应体等待。
- JSON 响应上限 4 MiB，结束时关闭 response/connection 与观察线程；取消/到期优先于断连错误，不交付迟到结果。该 context 传输直接连接指定 http/https 地址，不跟随重定向或环境代理；无 context 的既有调用仍走原 urllib 路径。
- 音频转换接入 capture_process 的可取消进程组，最多使用 20 秒且不超出轮次预算；无 context 转换也增加 20 秒超时。转换输出使用唯一文件名，失败清除部分文件；批量 recognizer 在取消后不上传，按 keep_audio_files 设置清理本次采集。
- `a02-http-asr-verified/summary.json` 四项回归通过，包含本地假 sidecar 正常 context 请求的协议/metadata 校验；`a02-http-conversion-verified/summary.json` 三项回归通过。新增 HTTP 15 项检查覆盖响应头、响应体、Connection: close、超时、大小限制、正常 JSON 和观察线程退出；新增转换三项检查使用真实模拟转换进程，验证取消回收、源/残留清理和不上传。
- 全部证据位于 `output/architecture-implementation/`，没有使用真实录音、云 ASR 或 provider 凭证。DNS/连接尚未获得 socket 前不能靠 shutdown 立即打断，由有限预算和单识别工作名额约束；服务端已接收任务的 provider 取消仍待实现。A02/A03 保持进行中，U02 保留。

### A02/A03 直接 Doubao WebSocket 轮次预算与取消（最新）

- `DoubaoRealtimeAsrRecognizer` 把 context 传入实际 session factory；session 建连、发送、接收/partial 回调与 finish 检查同一轮次预算。连接超时取剩余预算和配置较小值；连接迟到返回时先关闭连接，不发送请求或音频。
- 有 context 的 session 独立观察取消/到期，调用 websocket-client 的 abort 解除阻塞，最终 shutdown 释放连接。finish 轮询超时不会立即截断结果，但接收时段有固定截止时间，不因持续收到消息不断续期。采集迭代器在构造/处理失败、正常结束时均显式收尾；观察线程跟随 session 关闭。
- `output/architecture-implementation/a02-doubao-cancel-verified/summary.json` 四项回归；新增 16 项检查覆盖初始发送取消、finish 取消/到期、建连迟到、预算传递、正常最终结果与关闭状态，相关实时 sidecar/采集取消回归一起运行。
- 当前虚拟环境缺少 websocket-client；接口依据官方源代码确认 abort/shutdown，验证使用受控模块和假连接，不声称真实 WebSocket/TLS/云 ASR 已通过。依据：https://websocket-client.readthedocs.io/en/latest/_modules/websocket/_core.html 。依赖安装包验证仍在 A13 范围。
- 批量 HTTP、DNS 阶段及 server 端无 context 的调用仍待统一；非协作回调依靠单识别名额保持有界。整体 A02/A03 未完成，U02 真音频验收保留。

### A02/A03 实时 sidecar ASR socket 与接收线程收尾（最新）

- `VoiceSidecarRealtimeAsrRecognizer` 使用整轮剩余预算约束连接和最终结果等待；独立取消观察在线程发现取消/到期时 shutdown socket，解除阻塞的 send/read。send 前后与 partial 回调前检查上下文，接收帧按二进制行限制为 4 MiB；移除无人消费的无界 metadata 队列。
- finally 显式关闭采集迭代器、socket、reader，等待接收/观察线程退出；异常断连保留原取消/到期原因。网络发送阻塞解除后会关闭暂停的采集生成器，触发此前实现的采集进程回收。
- 不协作的 partial 回调不能被强制杀线程：超过首次等待会标记 `receiver_shutdown_confirmed=False`，识别工作名额继续占用直到回调退出，随后置 true。live 调用方仍由 TaskContext 及时返回，不因未确认收尾放出名额造成接收线程累积。
- `output/architecture-implementation/a02-asr-socket-final-verified/summary.json` 最终四项回归；新增 18 个 socket/回调检查，覆盖最终结果静默时取消与到期、音频发送阻塞、真实 socket 关闭、采集迭代器关闭、线程退出和阻塞回调名额保留。正常本地假 sidecar 的 partial 与最终识别结果回归同时验证。初次正常测试受沙箱 bind 限制，宿主回环执行使用 fake 后端，无真实麦克风或云端。
- A02/A03 仍进行中：直接 Doubao WebSocket、批量 HTTP ASR 的网络关闭、DNS 阶段和所有回调的协作取消尚未统一；本轮只收口实时 sidecar 客户端。真实麦克风、回声和用户体验保留 U02，整体工作包未标记完成。

### A02/A03 可取消采集进程与识别执行隔离（最新）

- live voice loop 使用进程内单名额识别执行器；取消/过期时调用方及时返回，非协作后端未退出期间继续占位，不叠加新的采集任务。已有五类生产 recognizer 接收整轮 context，向本地批量/流式音频采集传递。
- 新增 POSIX capture_process：轮询 stdout/stderr 与单调 deadline，单行/聚合 JSON 上限 4 MiB，stderr 尾部上限 64 KiB。取消、到期或迭代器关闭时终止并回收本次命令的独立进程组。macOS speech 和批量 capture 在传入 context 时使用此路径；流式 capture 全部使用此路径，修复原来无 stdout 时永远到不了 wait(timeout) 的问题。
- `output/architecture-implementation/a02-capture-cancel/summary.json` 五项回归通过，新增九个检查：真实测试采集子进程取消及回收、静默流超时、stderr 排空、增量输出与生成器关闭、非协作识别等待取消/名额占用/恢复。使用 Python 子进程模拟 capture，不运行 Swift 麦克风，不连接真实云 ASR。
- 仍未证明全部资源可取消：网络 connect/send/finish 和接收线程尚需贯穿同一上下文并关闭；流式生成器暂停于阻塞网络调用期间也需主动关闭采集。AEC/口头打断和物理音频仍属于后续工作与 U02，不将本次子进程检查称为真实麦克风验收。

### A04/A02 核心最新发布驱动在途轮次取消（最新）

- 默认 `session_log.jsonl` / latest 的 voice loop 增加 `PublishedSessionProbe`，读取核心 `LatestSnapshotWriter` 原子发布的 `latest_snapshot.json`，不扫描历史日志。校验 telemetry-v1、非空 UID、非负整数 epoch、有限时间和 15 秒新鲜度；限制普通文件和最大 4 MiB。
- 比赛轮次在监听开始绑定 UID/epoch，独立线程每 50 ms 检查核心发布。切场、倒带、发布文件删除/损坏或过期会取消该轮次，即使 ASR/LLM 尚未返回。提交输出前另行检查同一发布源，减少依赖观察线程调度时机。
- 取消只影响当前客户端旧轮次，不从观察线程发送全局 stop，避免误停新场次已产生的提醒。主循环输出取消原因。待机/陪聊轮次不要求有效比赛发布；显式历史 row 或非标准日志路径不启用此 live 发布观察。
- `output/architecture-implementation/a04-published-session-cancel/summary.json` 五项回归通过，新增 11 个检查：真实原子写入、同场更新、切场/epoch、文件失效/过期、观察线程退出、提交前复查，以及实际 VoiceInputCoordinator 在慢 LLM 未结束时因新 epoch 返回 cancelled 且没有播报。
- 范围仍不等于完整生命周期广播：文件发布到服务端场次绑定不是原子事务，仍有跨进程传播窗口；服务端统一场次权威、同 epoch 决定过期和 ASR 物理中止尚待完成。此处仅证明本地发布观察与取消链，无真实比赛或音频验收。U01–U04 保留。

### A02/A03 独立停止入口与当前语音轮次取消（最新）

- `VoiceTurnInterruption` 为每次实际监听建立 TaskContext（整轮默认 60 秒）；macOS voice loop 的输入线程接收 `s + Enter`，立即设置当前轮次取消，再向共享输出发送全局 stop。手动和连续模式均使用同一个独立输入线程；q 同样先取消/请求停止再排入退出指令。
- `VoiceInputCoordinator` 接收该 context，LLM 使用剩余预算与自身超时的较小值，共享取消信号。取消/整轮过期结果返回 cancelled/expired，不走比赛模板或陪聊后备播报。识别期间停止后，迟到的 ASR 完成结果也在处理入口被拒绝。
- 输出代理在同一锁下重新检查 context 并提交；stop 在取消标志设置后取得此锁。如果停止发生在已提交调用中，先等其结束再发 stop，避免同轮旧回复在停止之后再次提交。未知停止交付显示 `stop_unconfirmed`，不宣称实际播放器已停止。
- 控制队列上限 8，停止直接处理不排普通命令队列；退出清理积压 reload 命令，避免退出丢失。
- `output/architecture-implementation/a02-voice-interrupt-verified/summary.json` 六项回归通过，新增 11 个检查覆盖独立 reader、慢 LLM 及时取消、无后备/迟到播放、迟到识别丢弃、新轮次恢复、在途输出与 stop 顺序及命令积压。使用受控 LLM 和 fake 播放器，无麦克风、云端或物理声音。
- A02/A03 仍未完成：当前取消抑制 ASR 完成结果，不能强制终止正在阻塞的 recognizer；实际同时监听/AEC、权威场次切换取消、跨客户端停止屏障和在途网络资源中止仍需继续。60 秒为整轮接受结果预算，不是麦克风物理停止保证。U01–U04 不变。

### A03 默认 live 启动与离线隔离（最新，覆盖此前“统一启动尚未完成”的入口说明）

- `--live-udp` 现在通过 `LiveSpeechService` 默认启动/附着每用户共享服务，再把客户端注入 AsuradaApp，进入已有后台提交路径。macOS voice loop 默认连接相同地址，服务缺失在状态读取/麦克风监听前返回 2，不构造本地播放器。
- 显式 `ASURADA_SPEECH_SOCKET` 仅附着外部服务；未配置使用私有 700 目录下的固定 socket。创建者退出请求关闭自己创建的服务，附着者不关闭服务。关闭超时保留进程，报告未确认，不强杀可能仍持有播放器的所有者。
- demo/CSV/capture CLI 明确 `shared_speech=False`，不因继承 live 环境地址把历史提示送进比赛语音队列；直接 Python API 仍允许显式配置/注入输出。需要 sidecar 后端或独立常驻生命周期时使用外部服务模式。
- 真实服务子进程 + null 后端验证启动、复用、附着退出、创建者退出、外部服务缺失不回退、voice 预检、默认 CLI 接线及离线隔离。游戏循环被替换，无真实 UDP 比赛/麦克风/云服务。默认沙箱禁止 Unix bind 的失败保存在 `a03-live-startup`；宿主验证证据为 `output/architecture-implementation/a03-live-startup-verified/summary.json`。
- A03 仍进行中：权威场次广播、在途 ASR/LLM 取消与输入打断、持久回执、服务异常恢复仍须完成。服务进程退出不等同于物理音频停止验收；U01–U04 保留。

### A03/A06 共享服务与实时 IPC 隔离（最新）

- `speech_service.py` / `speech_client.py` 提供 Unix JSON IPC：唯一服务锁、独立队列时钟、128 项成功请求幂等缓存；停止未确认时保留所有权。客户端退出仅脱离，不停止其他客户端。`app.py` 与 voice loop 通过 `ASURADA_SPEECH_SOCKET` 接入，配置后服务不可用则启动失败，不回退第二播放器。
- 已核对 `output/architecture-implementation/a03-shared-speech-final/summary.json`：共享服务阶段四项回归通过，其中 17 项服务检查包括两个独立客户端、幂等、独立时钟、停止锁和独立进程启动退出；fake/null 后端，无真实音频。
- 本轮将 `LiveSpeechSubmission` 接入 live 共享服务路径。一个工作线程、一个在途请求、一个可替换待处理决定；默认待处理 500 ms 到期。复制状态与决定，后台不能修改已经记录的数据。拥塞仅保留最新策略状态，不补播历史提醒。
- IPC 失败记为 `delivery_unknown`，不重试不明交付，不回退本地播放；后续新决定仍可提交。关闭丢弃待处理内容并有界等待在途；未停止返回 false，不宣称取消完成。
- `submission_accepted` 与实际 start 分开统计。debug 中记录提交 ID、健康和收取的回执；尾部回执输出到关闭日志。回执环上限 128，溢出有计数，尚不是完整持久事件账本。
- `output/architecture-implementation/a03-async-speech-verified/summary.json` 四项回归通过，新增 16 个行为检查：阻塞时主链连续处理并记录 22 帧、断连后继续、有界队列、过期、冻结、未知交付不重试、恢复和关闭。生产入口接线使用真实 app/pipeline 与受控后端，无云端或设备调用。
- 原独立时钟回归存在句柄创建早于事件入队的观察竞态，已等待两者，保留原 500 ms 截止时间。失败记录留在 `a03-async-speech-final`，最终通过记录为 verified 目录。
- A03/A06 仍进行中：本地未配置共享服务的路径仍同步；默认统一启动、场次权威广播、输入打断、在途取消、完整持久回执仍需完成。U01–U04 保留。

- 已建立完整工作包和用户验收任务。
- 已有评估材料：`doc/ASURADA_ARCHITECTURE_REVIEW_2026-09-15_CN.md`；原始复现：`output/architecture-review-2026-09-15/probes.json`。
- 开始 A01：首先统一燃油领域判断，并建立可扩展的事实与决定契约。

### A02 首批实现与验证

- 新增 `task_runtime.py`：单调 deadline、取消信号、无等待队列的有界执行器。LLM 执行默认使用进程共享的 2 个并发名额；超时未结束的工作继续占位，避免后台线程无限增长。
- `LlmExplainer.run` 已使用执行边界，返回 timeout/cancelled/overloaded；过期或取消的结果不交付。不可中止的后端仍可能在后台运行，不将取消返回视为后端停止。
- 删除陪聊超时后重新发放 3200 ms 的重试；Doubao API 后备调用接收剩余预算。
- 新增行为回归 5 个检查：实际返回时限、超时占位、取消不交付、后备预算、过期不提交。40 ms 测试实际约 40.6 ms 返回。
- `output/architecture-implementation/a02-verified/summary.json`：4 项回归通过。`output/architecture-implementation/a02-http/summary.json`：1 项本地 HTTP 假后端回归通过。初次 HTTP 测试被沙箱禁止绑定端口，获准执行后通过；未调用真实云端服务。
- A02 尚未完成：取消上下文仍需从用户输入/停止通道贯穿生产调用，并与 A03 的音频取消及 A10 持久任务关联。其他工作包与 U01–U04 保持原范围。

### A01 领域事实首批接入

- 新增 `assessment.py / FuelAssessment`，统一覆盖圈数、剩余赛程、余量差、油箱比例、来源、质量及规则版本。核心燃油状态和候选理由、燃油查询/建议、主要风险及 LLM 实时摘要已接入。
- 无推导覆盖数据时，只依据有效油箱比例描述局部风险，并明确无法判断终盘覆盖；缺失、NaN、无效容量不按零处理。真实零油量仍是 critical。
- `output/architecture-implementation/a01-first/summary.json`：5 项回归通过，新增同快照跨核心/回答/摘要一致性及缺失/零/NaN 行为检查。
- A01 尚未完成：轮胎、攻防及其他资源判断仍需汇聚；全局 AssessmentResult/DecisionRecord、快照绑定与日志/跨端契约继续实施。现有燃油推导公式的精度不由此回归证明。

### A05 缺失分数修复

- 仲裁器模型分数使用 Optional 值；缺失、null、非有限分数或明确 disabled 不加减分。真实零分保持有效；部分模型输出不再隐式构造其他低风险结果。
- 修复 entry/apex 为零时被当作缺失，确保有效极低驾驶质量分数能够参与贡献。
- `output/architecture-implementation/a05-missing/summary.json`：5 项回归通过；含缺失/部分/零/禁用/非有限数据以及既有准入、长期规划、进站和攻防回归。
- A05 尚未完成：长期规划独立准入、贡献版本/TTL、模型资产证据绑定和迁移仍待实现。A01/A05 的本轮变更已改变过去有缺陷的边界行为，最终需要综合捕获回放评估影响。

### A04 场次生命周期首批接入

- 新增 SessionLifecycle：切场隔离；overall frame 前进且游戏 frame 回退时增加 epoch；拒绝较旧 overall frame。缺少可靠计数器时不凭时间戳推断倒带。
- UnifiedStateStore 按场次/epoch 清理窗口，提供 recent_seconds；UDP/capture pipeline、标准化 replay 和 CSV 入口遵守快照接受结果。epoch 已写入回放并由 decode 恢复；战术前态按 UID + epoch 隔离，策略调用额外过滤跨场历史。
- ConversationContext 在切场/epoch 变化时清理；非比赛 LLM 摘要不再携带旧策略和比赛问答，仅保留有 companion 标记的记录。语音归一化前清除过期比赛上下文。
- 新增 lifecycle 行为回归覆盖同场、切场、乱序、倒带、时间窗口、上下文清理及陪聊保留。相关证据：`output/architecture-implementation/a04-verified/summary.json`。
- 旧 LLM 回归夹具时间已固定，仅冻结赛况 freshness 时钟，不冻结任务超时。
- A04 尚未完成：组包缓存的生命周期与逐字段年龄、断流事件/时钟注入、辅助模式和在途声音/任务的失效传播、计数器缺失及重启/回绕策略仍需实现与综合回放。新增 recent_seconds 尚未替换全部固定帧窗口。

### A08 LLM 依据校验首批接入

- 新增 `llm_evidence.py`：从本次状态和策略快照提取可用引用，排除 null/非有限值；支持完整字段路径及唯一无歧义短名。
- LlmExplainer 实际返回路径校验比赛回答的引用、非空依据及 request_id；纯文本降级包装不能作为比赛回答通过，陪聊保留纯文本能力。拒绝结果返回 llm_invalid_evidence 和原因。
- 请求事实复制后交给后端，依据验证保留独立副本，后端不能通过修改请求增加虚构依据。provider 输入已提供可用引用清单和选择要求。
- schema 拒绝 NaN/Infinity/布尔 confidence，以及被错误转为空列表的 reason_fields=false。结果交付前再次检查 deadline/取消。
- `output/architecture-implementation/a08-first/summary.json`：6 项回归通过，新增 12 项依据行为检查。既有成功夹具改为引用真实路径，而非没有对应事实的 rear_pressure/penalty_window。
- A08 尚未完成：自由文本中的数字/单位与事实一致性、DecisionRecord 版本绑定、过期决定及动作权限需要后续契约配合。本轮只证明可机器检查的引用和格式边界，不证明全部自然语言结论正确，也未做真实云端评估。

### A03 声音调度首批修复

- ConsoleVoiceOutput 消费仲裁 interrupt 标志；高优先级且当前内容可取消时请求停止，只有后端确认不活跃才开始新内容。未确认时保留 active，防止双重播放。
- 添加排队 TTL：策略提示 3 秒，其他响应 15 秒；开始前检查到期。补充 tick 接口，无需新遥测提交即可推进完成/过期/下一条。公共输出操作通过 RLock 串行化。
- 完成时优先考虑新到的更高优先级内容，不再先启动低优先级 pending。停止/取消请求未获后端确认时发出 cancel_requested；确认后为 cancel，不写成正常完成，也不将取消内容保存为可重复的完成回答。
- `output/architecture-implementation/a03-first/summary.json`：4 项相关回归通过；`a03-stop/summary.json`：3 项通过；`a03-stop-ack/summary.json`：补充停止确认用例通过。测试均使用假播放器。
- A03 尚未完成：tick 的生产独立驱动、跨进程唯一 SpeechScheduler、sidecar 的真实可取消播放、ASR 打断入口、场次/决定有效性传播及 voice loop 旁路移除。当前未宣称真实音频停止已验证；TTL 数值也需要最终驾驶体验验收。

### A06 实时文件写入隔离

- 新增 AsyncRuntimeSink，并接入 `AsuradaApp.run_live_udp`：日志与 dashboard 各有独立后台消费者；日志待写容量 128，满时计数丢弃；dashboard 仅保留最新待写快照，计数合并。
- 提交时复制数据所有权，写入失败、待写数量、占用状态和写入耗时可查询；pipeline debug 带前一刻 sink health。退出 finally 排空并关闭，超时明确报告 worker 仍活跃，不伪称全部落盘。
- `output/architecture-implementation/a06-sinks/summary.json`：3 项回归通过；新增慢写入、容量上限、丢弃、数据复制、关闭超时与恢复、最新值合并、磁盘失败检查。
- `output/architecture-implementation/a06-integration/summary.json`：应用入口集成回归通过，假输入驱动真实 ReplayLogger 和 DashboardFeedWriter，在临时目录核实退出已写入且消费者终止。没有开启真实 UDP。
- A06 尚未完成：观察模型有界后台、事件触发规划、最新状态查询接口及完整端到端延迟轨迹。数据 deepcopy 仍在提交线程执行，CPU 成本需综合回放测量；过载丢弃需要作为回放质量缺口处理，不能把日志当作无损记录。

### A01 统一评估与决定记录

- 新增 AssessmentResult/DecisionRecord 正式类型。领域评估集中生成燃油、轮胎、ERS、赛道管制、攻防和车辆姿态标签；策略已调用统一入口。
- AssessmentResult 保存阈值、规则版本和内容指纹。问答复用本次自定义阈值；快照内容变化时重新评估，避免缓存旧结论。
- StrategyEngine 生成绑定 snapshot_id 的决定记录，保存最终动作、候选和仲裁输出的独立副本；ReplayLogger 已持久化记录。LLM 摘要仅包含与当前快照指纹一致的决定。
- 轮胎查询/管理/相关风险分支及 ERS 低量查询已接入领域阈值。`a01-contracts/summary.json` 六项回归通过；`a01-binding/summary.json` 补充自定义阈值、变更失效、决定副本与绑定检查通过。
- A01 仍未完成：部分综合回答的攻防/风险优先级仍有领域逻辑分支；记录需要由 replay/voice loop 读取恢复，并接入 HUD、工具及能力 handler；哈希和复制开销需要性能验证。DecisionRecord 的 contract_version 目前是初始内部契约，尚未证明所有端侧兼容。

### A01/A06/A09 决定读取与最新快照接口

- 新增 telemetry-v1 序列化入口，ReplayLogger 与 LatestSnapshotWriter 共用；decode_snapshot 恢复绑定的 AssessmentResult/DecisionRecord，并拒绝版本或快照/场次/epoch 不匹配的记录。旧格式可读取，但不伪造绑定决定。
- Live UDP 增加独立有界 latest-only 消费者，原子写 latest_snapshot.json。voice loop 的 latest 查询优先读该文件；显式历史行仍读日志。新的日志会话 reset 清除旧 latest，避免读到上一轮运行内容。
- 语音侧恢复决定中的权威动作；ASR 完成后再刷新最新状态。历史行查询保持显式选择。
- `output/architecture-implementation/a09-record-reader/summary.json`：3 项回归通过，含记录 JSON 往返、绑定拒绝、voice loop 无需解析历史日志及应用退出排空三个消费者。
- 仍待完成：端侧版本契约全部接入、记录完整性/版本迁移策略、断流统一事件、voice loop 的异步响应失效校验。当前快照匹配校验不代表已实现可信签名或对日志篡改的全面校验；ASR 刷新入口尚需完整语音流程验证。

### 综合契约验证与兼容性修复

- `contracts-integration-1/summary.json`：57 passed / 6 failed。六项失败均为 LLM 假后端引用请求中不存在的 rear_pressure/penalty_window；未放宽生产校验，补齐测试事实并改用真实路径。
- `contracts-integration-2/summary.json`：63 passed / 0 failed / 0 skipped，涵盖当前 contracts 集合（不含 phase1_regression 的完整捕获回放）。使用本地假 HTTP/音频后端，未作为云端或设备验收。
- 额外复现并修复 snapshot_id 对整数/浮点表示敏感：247 与 247.0 现在一致，接近 uint64 上限的相邻整数保持不同。`snapshot-canonicalization/summary.json` 四项相关回归通过。此修复发生在 63 项综合回归之后，未将较早结果表述为最后修改后的全量重跑。
- 数字规范化改变了开发中的内容指纹算法；已有旧实验记录可能因绑定不匹配被拒绝，发布前需明确契约迁移策略。本轮未宣称 A01–A13 全部完成。

### A05 模型资产迁移与完整性

- 24 份已有模型报告改为与报告同目录的相对模型路径；增加 model-asset-v1、模型 SHA256 和有序特征 schema SHA256。历史缺少 feature_columns 的报告从模型实际特征顺序补齐。
- 两类运行时加载器统一解析相对报告位置，校验已有清单与 Booster 特征顺序；active 必须具有清单。缺失、JSON 损坏、模型损坏或 schema 不匹配转为明确 disabled_reason，不使可选模型拖垮核心启动。
- 训练脚本新输出使用相对路径。新增 `asurada-core/scripts/package_model_assets.py <report.json> ...`，在训练后读取实际模型并写完整性清单；此步骤不代替模型质量评估和准入证据。
- `a05-assets/summary.json` 四项相关回归通过（含实际模型编码验证）；`a05-packager/summary.json` 补充从 Booster 获取缺失特征契约通过。迁移测试将模型和报告复制到临时目录并用 active 模式加载。
- 尚待完成：准入证据与评估集版本/资产摘要的强绑定、长期规划 contributor 独立权限、干净环境依赖声明及完整发布包验收。训练输出需先运行打包命令才可 active；未默认提升任何模型权限。

### A12 场次隔离训练首批接入

- 新增 session_partitions：以完整 session_uid 为单位保留 exported test/val；没有 val 时按稳定哈希选完整训练场次；场次跨集合或场次数不足明确失败，不回退到按行随机切分。
- 资源风险和驾驶质量两个训练入口实际改用该分割器，报告保存场次与样本数清单。CSV 的 session_uid 强制字符串读取，避免大整数被转为浮点失去精度。
- LABEL_COLUMNS 和 build_label_row 新增 rule_pseudo_label 来源及规则版本；资源训练报告明确 rule_imitation_only_not_human_validated。
- `a12-partition/summary.json` 分割行为回归通过。实际使用 phase2_dataset_v2_extended 跑通 ers_risk 和 entry_quality，产物分别在 `a12-resource-training`、`a12-driving-training`，train/val/test 各为不同 UID、各 500 行。未替换已有运行时模型。
- A12 尚未完成：其他模型训练入口与 strategy-action/trend 导出分割迁移、预测目标窗口的 embargo、共享特征契约、完整场次/赛道/驾驶员泛化及真实标签基线。现有三个场次只证明执行链和互斥分割可用，不能代表泛化质量已验证。

### A07 能力定义与 handler 接入

- 新增 capability_definitions.py 作为能力名、lane、handler、权限与策略元数据入口；原 control/structured/explainer 集合从定义生成，CapabilityRegistry.evaluate 不再维护三套独立允许分支。
- compose_structured_query_response 的 40 个查询分支拆为各自 handler，主入口通过 CapabilitySpec.invoke 调用；保留已有表达与领域辅助函数以降低迁移风险。
- Registry 提供结构化 tool_catalog；控制类能力不进入模型工具目录。策略元数据与输入/输出 schema 已可发现，运行时 enforcement 将在后续任务执行器接入。
- `a07-handlers/summary.json` 5 项相关回归通过；`a07-catalog/summary.json` 遍历全部能力，验证路由、每个查询 handler 的返回结构与工具目录完整性。
- A07 尚未完成：关键词/同义句路由和其他重复能力集合仍需迁移；领域 handler 尚在 response_composer 模块中，需按领域拆文件；统一 required_facts、时效/预算/权限执行和 UI 目录仍待完成。工具目录存在不代表 Agent 已能安全执行全部工具。

### A07 领域模块与受限工具执行

- 40 个查询 handler 分入 capabilities/resources、damage、pit、rivals、session 五个模块，主回答入口仅负责注册查找。共享表达辅助函数暂保留在 response_composer。
- 新增 CapabilityExecutor：校验只读工具白名单、权限、空参数 schema、调用次数、TaskContext deadline、状态年龄及可选最新快照绑定检查。历史访问需显式 read_session_history；控制能力不开放给模型工具。
- 新增 query_snapshot_tool.py CLI，已实际使用历史快照执行 fuel_status/tyre_status，结果保存在 `a07-executor/cli_result.json`；结果携带任务、场次、epoch、快照绑定及评估依据。
- `a07-domains/summary.json` 三项回归通过；`a07-executor/summary.json` 两项通过，含未知工具/参数、权限、次数、过期及 superseded 拒绝用例。
- 尚待完成：语义关键词统一、复杂工具输入与 required_facts 定义、所有生产回答入口的执行策略统一；A10 的持久状态、工具规划/恢复和赛后多步分析仍未实现。CLI 的两个查询仅是执行入口验证，不代表完整 Agent 流程完成。

### A10 持久工作流首批接入

- 新增 SQLite WorkflowStore：固定步骤定义与输入绑定，逐步提交结果，持久 status/error/attempts/总到期时间；进程级非阻塞文件锁避免并发重复执行。已提交只读步骤恢复时跳过，中断的未提交只读步骤可以重放，不承诺外部副作用 exactly-once。
- 新增 session_review_workflow 与 run_session_review.py CLI：官方已完成圈索引 → 最近圈比较 → 证据报告。按 UID/epoch 隔离；冲突官方圈时拒绝；缺少弯道依据时不生成训练重点。
- `a10-workflow/summary.json` 覆盖检查点恢复、已完成幂等、输入冲突、取消、过期和三圈合成数据流程，全部通过。
- 实际读取归档 session_log.20260413_061359.jsonl，数据库为 `a10-workflow/review.db`，结果为 `a10-workflow/archived_review.json`。三个步骤完成，但只有一圈有效官方计时，未生成比较结论；此结果不证明三圈弯道分析已完成。
- A10 尚未完成：工具执行器与持久任务预算统一、多步 Agent 规划、弯道比较/进站依据工具、训练报告完整流程、在途取消传播与重启故障注入。当前流程为固定的只读会话分析，不替代完整目标。

### A03 sidecar 播放取消资源接入

- 新增每次播放独立的 PlaybackControl；VoiceSidecarSpeechBackend.stop 现在发送取消，实际控制对象传入流式/缓冲播放。
- 控制对象登记 HTTP 响应和播放器 Popen；取消时终止播放器，必要时升级 kill，并关闭响应流。HTTP buffered close 可能等待读锁，清理放在独立线程，输出调度仍依据播放线程真实结束确认取消。
- 流式/缓冲播放检查取消信号；异常/退出清理残留播放器；音量显示工作线程可提前终止，不再继续回放已取消的音量队列。
- `a03-playback/summary.json` 四项现有本地播放回归通过。`a03-cancel-resources/summary.json` 使用真实睡眠子进程和阻塞假响应验证进程退出、取消及时返回及关闭流结束线程；未测试真实扬声器或远端 TTS 中止计费。
- 尚待完成：跨进程唯一调度、voice loop 直接播放旁路移除、独立 tick 驱动、ASR 打断/声学回声、播放总 deadline 和网络连接建立阶段取消。当前取消不等于远端生成已经停止。

### A03 独立调度时钟与 voice loop 旁路移除

- 新增 SpeechOutputDriver，在 Live UDP 和 macOS voice loop 生命周期内独立 tick，记录近期非 idle 生命周期事件。没有新遥测/用户输入也能完成当前任务、检查 pending 到期并启动下一条。
- voice loop 的 --use-sidecar-tts 改为使用 VoiceSidecarSpeechBackend；删除 _play_sidecar_tts 直接播放旁路，问答统一经过 ConsoleVoiceOutput。监听前检查实际后端活动与音量状态，保留结束后的回声冷却。
- 输出 shutdown 丢弃 pending，请求停止 active，并等待后端确认；驱动线程退出可验证。声音未确认停止时返回 false，不伪称已关闭。
- `a03-driver/summary.json` 四项相关回归通过；`a03-driver-live/summary.json` 三项通过，含无新输入情况下独立启动下一条、事件留存、退出清理线程与播放。
- 尚待完成：多个进程之间唯一声音调度所有权、全部独立 tick 事件持久化、driver 错误健康状态接入、ASR 播放中打断及真实声学验收。当前两个进程各自的队列仍不能当作跨进程唯一调度者。

### A05 长期规划独立准入

- 新增 ContributorPolicy，分别管理 pit_window_support / long_horizon_strategy 的 disabled、observe、active；active 需要证据引用，长期策略 active 还要求进站支持 active。
- 默认两项为 observe：规划诊断仍生成，但不再改变仲裁。此项有意改变旧实现的默认行为，需在综合捕获回放中对比影响。disabled 不计算对应规划；未准入结果不会通过诊断文本附加再次出现在 admitted sidecar 字段。
- `a05-planners/summary.json` 四项既有回归通过；`a05-contributor-gate/summary.json` 两项通过；`a05-contributor-effect/summary.json` 验证 disabled 跳过计算、observe 高低结果不改决定、active 真实改变决定、依赖及证据要求。
- 尚待完成：贡献 TTL/事件缓存、规则/模型/规划统一贡献记录、证据文件与评估集及代码/资产版本绑定。当前非空证据引用是权限入口要求，不能视作已自动验证其内容。

### A06 观察模型后台执行与重启隔离

- Live UDP 的策略入口启用 ObservationLane：observe 模型从同步评分组移至单名额后台，默认每 200 ms 至多提交一次；active 预测仍由同步决策链执行，disabled 不提交。诊断结果独立携带快照、场次、epoch 和时间绑定，不进入仲裁分数。
- 任务繁忙时不排队、不准备新副本；结果按提交时刻计算 TTL（默认 2 秒），旧 epoch 或过期结果不展示。准备与推理失败记录计数和原因，避免观察故障终止主链。
- 关闭和切场取消任务上下文，模型调用之间检查剩余预算。重启复用同一执行名额；无法中断的在途模型继续占位直至实际结束，不能通过新建 lane 叠加推理。close 返回是否真正结束，未确认结束不会伪称已关闭。
- 首轮新增测试失败：慢模型注入选中了默认 disabled 的 fuel_risk，未进入后台；更正为 observe 的 ers_risk 后验证实际 StrategyEngine.evaluate 在模型仍阻塞时及时返回，连续帧只保留一个观察任务，并与离线基线动作一致。
- `output/architecture-implementation/a06-observation-verified/summary.json`：4 项回归通过；新增 15 个检查覆盖提交非阻塞、忙时无队列/无准备、取消/重启占位、恢复、结果副本、epoch/TTL、准备异常、实际策略入口和 active 同步预测。既有模型准入、规划准入及 Live 日志入口回归通过。
- A06 仍待完成：事件触发规划与贡献 TTL、接收链隔离、完整阶段时延及真实模型/捕获回放性能验证。Python 后台线程不能强杀正在执行的推理；超时丢弃与协作取消不代表模型已在期限内停止。U01–U04 保留不变。

### A05/A06 事件触发规划与有效期准入

- 新增 PlanningLane 并接入 Live UDP：进站支持与长期规划组成一个有界后台任务，默认每秒刷新，结果从提交时刻起最多有效 2 秒。标准化 replay/capture 保持逐帧同步规划，便于现有离线比较；Live 性能和时序行为须另行测量。
- 新圈、UID/epoch、赛道、天气/安全车、轮胎/位置、对手进站、领域状态标签、预测天气与相关历史/轮胎集合变化产生事件键；事件变化立即隐藏旧结果并取消旧任务。连续变量通过低频兜底刷新，不承诺规划逐帧更新。
- Live 仲裁只消费事件键匹配且 TTL 内的最近结果；结果带原始快照/场次绑定。pending/过期/变更事件时提供 unavailable 诊断，不贡献分数；仍遵守 ContributorPolicy，observe 不影响动作，active 才允许有效结果参与。
- 后台关闭/重启保留执行名额，推理不协作时不会叠加线程。步骤间检查取消与预算；异常保留可查询原因，旧缓存超时后失效。任务准备中的 deepcopy/事件键计算仍在提交线程执行。
- `output/architecture-implementation/a06-planning-admission/summary.json`：5 项相关回归通过。新增检查覆盖同事件复用、低频刷新、事件失效、慢规划非阻塞、无排队、关闭/重启、TTL、实际 StrategyEngine 入口、observe 动作一致，以及 active 的 pending 拒绝/有效绑定/天气变化撤销贡献。
- A06 尚未完成：独立接收链、有界积压策略、全部阶段单调耗时追踪、真实模型及完整捕获回放性能/行为差分。A05 尚需准入证据与代码/模型/评估资产强绑定及统一贡献契约；此处 TTL 和事件绑定仅覆盖 Live 规划路径。U01–U04 保留。

### A06 UDP 接收隔离与单调阶段耗时

- Live UDP 使用 BufferedPacketSource，接收线程只读取原始包并提交有界队列，解码、策略和输出在消费者执行。默认容量 512，可由 UdpConfig.receive_queue_capacity 调整；满时丢弃最旧包，保持剩余最新包的顺序。
- 每包附 ingress_queue_ms、接收单调时刻和累计 received/delivered/dropped_oldest/max_depth；快照日志记录这些接入指标，原始 capture 行也保存接入健康与排队时间，避免过载录制被误认为无损捕获。
- UdpPacketSource 支持协作关闭，接收轮询上限 200 ms；应用 finally 关闭接收器并报告实际退出状态。启动/接收错误传回消费者；非协作输入未退出时 close 返回 false。
- runtime_pipeline 阶段耗时改用 monotonic_ns，墙钟展示由单次锚点投影；新增 receive_to_output_submission_ms。该指标包含本进程接收后的排队与处理，只计到输出提交，不代表 TTS 或扬声器真正发声，也不包含游戏到网卡的传输时延。
- `a06-ingress/summary.json` 四项相关回归通过；`a06-ingress-timing/summary.json` 三项通过。新增慢消费者下持续接收、容量/丢弃、最新顺序、接收故障传递、退出阻塞接收，以及实际 pipeline 的耗时与落日志检查。未绑定真实 UDP 或使用游戏数据。
- A06 尚待完成：真实包突发/掉包的组帧差分验收、原始 capture 写入独立隔离、完整模型及捕获回放性能验证、输出后续阶段追踪。按原始包丢弃可能造成不完整帧或低频上下文缺失，当前以显式数据缺口报告，不宣称过载下所有业务字段仍连续有效；A04 字段年龄与组帧生命周期仍需完成。U01–U04 保留。

### A06 原始 capture 写入隔离与完整性声明

- 新增 AsyncPacketRecorder，Live UDP 的原始包录制通过独立 AsyncRuntimeSink 写入，默认队列容量 1024，满时拒绝新录制项并计数；策略消费者不等待磁盘写入。提交前分配 capture_submission_id，与实际写入行序号分开，保留录制缺口线索。
- 录制启动时写 `<capture>.health.json`，标记未完成；退出排空后原子更新 sink 与 ingress 健康。只有后台真正结束、无写入失败/录制丢弃/接收队列丢弃或残留、提交全部落盘，才声明 local_capture_complete。该声明仅针对应用收到的包，不证明网络或游戏端无丢包。
- CaptureJsonlSource 保留录制序号与原接收健康；capture_summary.json 增加 reported_capture_health，旧录制缺少清单标记 legacy_unknown，损坏清单标记 unreadable。清单是生产者报告，不作为防篡改完整性证明。
- `a06-capture/summary.json` 四项相关回归通过；`a06-capture-live/summary.json` 两项通过。覆盖慢磁盘、队列满、未结束关闭、排空、接收丢弃、磁盘失败及回读；应用真实 run_live_udp 装配路径通过假输入写真实临时 capture，核实退出已排空且后台终止。
- 仍待完成：组帧缓存年龄与 epoch、突发真实包的完整回放差分及综合时延。当前录制位于接收队列之后，接收过载时无法恢复此前丢弃包，但清单明确标记不完整。用户真实比赛/语音/设备验收 U01–U04 保留。

### A04 组帧缓存年龄与过期移除

- 新增 PacketFreshness，按包接收时间管理跨帧缓存，不使用回放运行时墙钟。Session 默认 5 秒、Event 2 秒、LapPositions 5 秒、SessionHistory 10 秒，其余身份/设置/最终分类缓存 30 秒；这些是当前工程保守值，仍需长会话与实际发送频率验证。
- CaptureSnapshotAssembler 在消费每包时移除过期缓存，Session 过期会暂停组帧直到有效 Session 恢复；辅助缓存过期不再复用旧 body。输出 raw.cache_quality 保存 source/observed_at_ms/age_ms/ttl_ms/quality。
- 无效接收时间和相对本 UID 已处理时间倒退的包被拒绝，不能覆盖较新缓存；该规则依据接收时间处理输入顺序，不冒充游戏 frame 的 rewind 检测。不同 UID 的缓存年龄相互独立。
- `output/architecture-implementation/a04-cache-age/summary.json`：3 项回归通过，含当前/过期/恢复/乱序/跨 UID/NaN 时间用例及既有全赛道合成包与真实历史抓包语义检查。上海、铃鹿、奥地利真实历史 capture 各处理到 40 个有效快照；并非完整会话回放或本轮真实游戏验收。
- A04 尚待完成：组帧器 epoch/倒带清理、跨 UID 缓存淘汰、字段缺失向全部消费端传播、断流事件与在途任务取消。旧录制时间不单调时本实现会拒绝较旧包，完整回放须统计这类拒绝与行为差异；U01–U04 保留。

### A04 包级 epoch 与缓存淘汰

- 新增 PacketEpoch：overall frame 前进而 frame 回退时增加 epoch；同 epoch 的普通计数器乱序不会触发倒带，倒带前 overall 边界之前的迟到包拒绝进入缓存。缺少合法计数器时不推断倒带。
- 组帧器确认倒带后清理该 UID 的待组帧、Session/事件/身份等缓存、缓存年龄与燃油起始基准；等待新 Session 后恢复组帧。标准化快照携带 session_epoch，下游状态仓收到显式新 epoch 后清理历史，不重复加一。
- 组帧层最多保存四个近期 UID，淘汰时清理该 UID 的全部缓存和帧，限制长时间运行的缓存增长。已淘汰 UID 再次出现会作为重新接入处理，不宣称已实现无限历史 UID 的迟到拒绝。
- 首轮测试暴露 PacketEpoch 缺少 postponed annotations，Python 3.9 加载失败；修复后 `a04-epoch-roundtrip/summary.json` 四项回归通过。使用真实包结构 fixture 修改包头模拟倒带，实际经过 decoder → assembler → decode_snapshot → UnifiedStateStore，验证快照 epoch 为 0/1，历史清理且不重复递增；既有赛道回放与缓存年龄检查通过。
- A04 尚待完成：计数器 uint32 回绕/同 UID 重启判定、跨进程场次事件和声音/任务取消、字段缺失向所有消费者传播、完整长会话回放。当前包级判断不替代实际 F1 倒带和设备验收；U01–U04 保留。

### A03/A04 输出场次绑定与旧播报取消

- ConsoleVoiceOutput 增加 bind_session，核心 emit、结构化问答、语音问答和控制入口绑定 UID/epoch。场次变化清理 pending、repeat-last 记录以及本场制动/挡位/攻击辅助控制状态；active 标记 cancel_requested 并请求后端停止，确认结束前继续保留播放所有权。
- macOS voice loop 在自动刷新状态后、检查当前播放状态之前调用 bind_session，因此无需等待下一条问答即可在下一次循环处理切场。关闭自动刷新或阻塞在识别/模型调用时的变化尚不能及时传播。
- 新提交 SpeechJob 带 session_scope；输出调试与生命周期 payload 保存最近 32 条 session-event-v1 切换记录，包括丢弃的 pending ID 和请求停止的 active ID。记录本身不证明音频已停，停止确认仍由后端状态决定。
- `a03-scope-production/summary.json` 五项回归通过。新增倒带清理待播、停止未确认不交接、新场提示等待并在确认后启动、scope 绑定、同场不重复重置；既有语音控制/调度/driver/快照读取通过。
- A03/A04 尚待完成：跨进程唯一播报服务、单一权威场次事件广播、在途 ASR/LLM 取消与晚到旧请求拒绝、断流超时事件。当前两个进程仍各自拥有输出队列；bind_session 依赖调用者提供最新权威状态，不能将其称为跨进程完整生命周期治理。U01–U04 保留。

### A02/A10 持久工作流在途取消与有界执行

- WorkflowStore 的实际步骤执行接入进程共享的双名额 BoundedTaskExecutor；等待使用任务剩余 deadline，并每至多 25 ms 检查持久 cancelled 状态。取消/超时设置步骤 TaskContext 的 cancellation；非协作阻塞工作保留执行名额，调用方不等待其结束。
- 步骤接收独立输入/已完成结果副本，只有协调器能够提交检查点。超时、取消或晚到返回不会把步骤结果写回数据库；步骤自主抛 TaskCancelled 也会保存终止状态。
- 执行锁改为数据库名加 task_id 摘要的独立文件锁，同任务排除重复协调器，不同任务可在有界容量内并行。数据库事务保持短提交。
- `a10-cancellation-verified/summary.json` 三项回归通过：阻塞步骤超时及时返回、取消上下文传播、超时占位/过载、晚到不落盘、另一 store 实例取消在途工作、不同任务并行与同任务锁排斥；原持久恢复和任务预算回归通过。
- 仍待完成：全产品用户停止/场次事件接入、ASR/LLM/TTS 跨进程取消与唯一声音服务、真实多步骤训练分析，以及进程重启故障注入。当前步骤约定只读，取消不撤销已发生的外部副作用，也不强杀线程；SQLite 锁争用/磁盘故障下的控制操作时延需另外验证。U01–U04 保留。

### A13 综合契约复核及 TTS 空内容拒绝

- `contracts-integration-3/summary.json` 执行当时全部 80 项 contracts：68 passed / 12 failed。逐项检查失败：11 项受沙箱回环端口绑定限制，1 项 macOS say 导出 WAV 无音频帧。
- `contracts-integration-3-host/summary.json` 在获准主机环境仅重跑这 12 项，全部通过；使用本地 HTTP 假服务和音频文件导出，未调用云端或物理播放。两份报告合起来覆盖当时 80 项契约，不表示一次完整无失败运行，也不包含 phase1_regression 的完整长会话回放。
- 空 WAV 揭示生产校验缺口：MacOSSaySidecarTtsRenderer 过去仅根据转换命令成功返回 completed。新增 WAV 格式/采样率/通道/位宽和有效帧长度检查；空、截断和非法音频明确失败，不再包装为成功。
- `a03-tts-validity/summary.json` 两项回归通过，新增 7 个检查覆盖空/截断/错误采样率/非法头、有效音频，以及实际 buffered/stream renderer 对空转换结果的拒绝。此修改发生在综合 80 项验证之后，不能把先前结果表述为最后修改后的全量重跑。
- A13 仍未完成：干净环境依赖安装、完整捕获回放/故障报告、跨端契约和全任务轨迹仍需继续；其他工作包和 U01–U04 保持原范围。
- 新增校验后的主机兼容复验：`a03-tts-validity-host/summary.json` 两项通过，覆盖真实 macOS TTS 文件导出及本地假 sidecar 播放协议链；仍未作为扬声器验收。

### A13 完整抓包缓存差分与全量策略回放启动

- 新增 audit_capture_freshness.py：完整逐包对照当前组帧器与仅关闭缓存 TTL 清理的对照组；epoch/接收顺序逻辑保持相同。此工具只量化 TTL 对快照数量的影响，不把诊断对照路径用于生产。
- `a13-full-replay/freshness-audit.json`：完整读取 666,921 包、7 个 UID，当前与对照均为 31,726 个快照，各场次 ttl_suppressed=0；接收时间拒绝和倒带边界拒绝均为 0。本数据中未观察到 TTL 清理导致快照数量减少，不证明真实掉包时所有字段有效。
- 启动完整 phase1_regression，参数 --snapshot-limit 0 --sample-snapshot-limit 0；结果目标 `a13-full-replay/report.json`，stdout/stderr 同目录。取消了原总抓包 1,200 快照限制，逐场样本同样全部处理。此条记录写入时进程仍在运行、日志持续写入、尚无最终报告；不得将其记为通过或重新启动来替代等待。
- 本轮不更改回放期间的生产实现。后续必须读取同一运行的最终退出状态、报告与逐场断言，确认完整策略结果；完整回放仍不能替代 Live UDP、云端及用户设备验收。

### A13 基础 Python 安装包与依赖分组

- pyproject.toml 增加 models/training/http-voice/local-asr 可选依赖，直接版本来自当前已验证环境；基础规则内核不强制安装 ML/音频库。尚未形成传递依赖锁文件，WebSocket 与系统原生依赖仍待补齐。
- 构建 `a13-package/asurada-0.1.0-py3-none-any.whl`，在新建独立 Python 3.9 venv 中使用 --no-index --no-deps 安装；使用 -I 导入包，确认模块来自新 venv 的 site-packages。CLI --help 和显式指定 sample_session.jsonl 的完整规则回放退出码为 0，ASURADA_TTS_BACKEND=null。
- build.txt/install.txt/import.txt/help.txt/replay.txt 保存在 `output/architecture-implementation/a13-package/`。隔离环境路径另存 environment-path.txt；未修改原 .venv，未安装云端依赖或播放音频。
- 此验证只覆盖基础 wheel 与无模型降级路径。赛道/策略/模型仍在仓库外层，wheel 未包含，默认 demo 数据路径仍需修正；README 明确此边界，不将其称为完整可部署包。
- 上一轮完整历史策略回放仍沿用同一运行，尚未生成最终报告；没有因等待而重启或缩小其测试范围。

### A13 wheel 资产与可写状态目录分离

- 新增 paths.py：源码沿用原 data/training/runtime_logs；安装包读取 asurada/_assets，默认状态目录 ~/.local/state/asurada。ASURADA_ASSET_ROOT / ASURADA_RUNTIME_DIR 可显式覆盖。核心配置、赛道、三个辅助控制器、voice meter 与三个 macOS Swift 入口使用统一路径。
- setup.py 的 build_py 仅复制明确选择的运行资产，MANIFEST.in 声明 sdist 输入；wheel 包含 90 个资产及 SHA256 清单。默认 CLI replay/demo 使用资产内 sample_session.jsonl，不再依赖当前目录。
- `a13-assets-package/verification.json`：独立 venv 安装新 wheel，90 个资产哈希一致、赛道/策略加载、24 份模型报告 manifest 与相对模型路径验证通过；--demo 退出 0。运行状态显式写入临时目录，未写用户默认状态目录。
- `a13-paths-regressions/summary.json` 六项源代码相关回归通过，覆盖赛道、三个驾驶辅助控制、模型准入和快照接口。隔离包未安装 ML 依赖，本轮不宣称其模型推理已通过；sdist 重建链与多平台原生依赖也尚待验证。
- 完整长回放继续原进程；它在开始时已载入改动前模块，因此最终报告需标明其源码阶段。本轮路径重构保持源码目录的资产位置不变，但最终仍需适当综合复验。A13 与其他工作包尚未整体完成，U01–U04 保留。

### A09 网页慢消费者隔离

- WebSocket 改为每连接一个有界发送者，最多 16 个连接，每连接最多一个正在发送帧加一个待发最新帧；拥塞合并计数，socket 发送等待上限 500 ms，发送错误断开并计数。广播线程只提交不可变 bytes，不等待各客户端 sendall。
- 新连接握手后立即提交当前状态，避免没有状态变化时一直空白；监听端口启动失败同步返回；增加服务关闭并接入 main finally。HTTP 回退接口限制 16 个并发处理者，每连接设置读写超时，避免一个慢请求独占接受循环。静态文件检查改用路径父目录关系。
- `a09-dashboard-loopback/summary.json` 两项回归通过：阻塞客户端与快速客户端隔离、单 pending 合并/最新顺序、发送失败计数与退出；真实 127.0.0.1 随机端口 WebSocket 握手、初始状态、后续帧与服务关闭验证通过。未改变仪表页面结构，也未运行真实设备显示。
- A09 尚待完成：跨端版本契约、iOS 权威数据接入/职责拆分、断流统一事件、浏览器与设备长连接验收。现有手写 WebSocket 仍需完整控制帧/关闭协议处理，HTTP 服务整体优雅关闭与慢静态文件处理也需继续验证。

### A13 完整策略回放最终结果

- 前述同一完整 phase1_regression 运行已结束，退出码 0，`a13-full-replay/report.json` 的 passed=true，七个顶层检查全部通过。
- 总抓包 snapshot_limit=null，实际处理 666,921 包和 31,726 个标准化快照，所有 full_capture 检查通过。四个完整场次样本（QualifyingLike/ShortResultLike/SprintRaceLike/FeatureRaceLike）均通过，仲裁/战术状态机/长期规划契约通过；未缩小原启动参数。
- 该报告针对启动时载入的核心模块，早于后续 paths.py 与网页传输变更。后续变更已有各自针对性回归，但不得将此报告宣称为所有最后改动后的统一发布验收；Live 后台规划/观察与接收队列行为也不能由同步离线回放替代。
- A01–A13 仍未全部完成。跨进程唯一声音服务、任务/证据/训练闭环、跨端契约与完整发布检查继续推进，U01–U04 保留。

### A11 作用域训练记忆与复盘接入

- 新增 TrainingMemory（SQLite）：session_fact / verified_performance / user_preference 分开查询；按驾驶员隔离，本场事实强制 UID/epoch；要求来源、有效期，过期不返回并提供清理接口。稳定身份重试不重复写入、不延长 TTL；同身份不同内容拒绝覆盖。
- verified_performance 首个验证方法仅支持 official_lap_delta_v1，必须引用同驾驶员的两条有效圈速事实、赛道一致且数值可重算；验证结果嵌入来源快照，使原事实按 TTL 清理后仍有依据。此方法只验证圈速差计算，不推断驾驶能力或训练因果。偏好要求 explicit_user_input 来源，本轮未自动写入任何用户偏好。
- session-review-v2 增加 persist_session_facts 步骤，CLI 支持 driver-id，默认 local-driver 仅代表当前本地档案，不能自动识别实际驾驶员。原 v1 同 task_id 请求会因定义变化拒绝复用，迁移需新 task_id。该持久步骤为幂等写入，可在检查点中断后重试；取消不回滚此前已写入事实。
- `a11-memory-verified/summary.json` 三项回归通过；隔离、TTL、幂等、不实差值/推测偏好拒绝，以及复盘实际保存/重复执行均验证。归档 CLI `archived-review.json` 四步 completed，实际仅保存一条可用官方圈事实，不生成弯道或训练结论。
- A11 状态改为进行中。仍待完成：训练建议实体与后续圈关联、真实弯道证据和表现比较、记忆消费入口、偏好编辑/撤销、身份选择与迁移。结构化记忆存在不代表训练闭环完成，U01–U04 保留。

### A10 距离对齐区段证据与复盘接入

- 新增 corner_review.py，按 UID/epoch/已完成圈筛选遥测，在赛道语义区段固定距离边界插值圈内计时；记录区段耗时、最低速度、来源哈希/行号及边界。只比较同场次/epoch/赛道/区段且天气、胎种和安全车条件一致的最近最多三圈。
- 区段必须有两端覆盖、至少三个内部样本；默认相邻时间间隔不超过 500 ms、距离间隔不超过 50 m。时间/距离回退、无效圈、进站或圈内条件变化拒绝；缺数据报告 insufficient_comparable_evidence，不补造时间轴。
- session-review-v3 增加 analyze_segments，报告包含 segment_review；五步持久执行仍使用源文件哈希绑定。不同工作流版本使用新 task_id，不覆盖 v1/v2 检查点。
- `a10-segment-review-verified/summary.json` 三项回归通过，合成三圈验证同距离耗时差、缺样/非单调拒绝、天气隔离和实际复盘流程。真实归档 `archived-review.json` 五步 completed，但缺少已完成圈对应的过程遥测，区段与比较均为零，明确记为证据不足。
- 尚待完成：真实完整多圈的区段分析验收、入弯/制动/出弯动作依据、训练重点与下一圈效果关联、Agent 工具调用和查询入口。当前区段边界来自本地语义图，耗时是插值估计；未控制交通/油量/磨损，不作动作因果判断或训练效果承诺。U01–U04 保留。


### A10 原始抓包投影、完赛圈归属与真实区段复盘

- 新增 review_capture.py / review_raw_capture.py，复用 F125PacketDecoder → CaptureSnapshotAssembler → decode_snapshot → UnifiedStateStore，将原始 JSONL 抓包转为复盘所需的圈计时、距离和条件投影。每行记录原抓包 SHA256、包序号与投影版本；发布前复核源哈希，临时文件原子替换。投影 manifest 记录包/快照数及接收时间、倒带边界拒绝；该精简投影不冒充完整 telemetry-v1 快照。
- 第一轮真实正赛复盘暴露 conflicting_official_lap_time：第 5 圈完赛时 currentLapNum 仍为 5，lastLapTime 已更新为第 5 圈成绩，旧逻辑统一减一误判为第 4 圈冲突。依据仓内 F1 25 包协议 resultStatus=3（finished），session-review-v4 将此状态的成绩归属当前圈，并在区段轨迹处理中跳过完赛后重置的圈内时钟。不同成绩仍归属同圈时继续明确拒绝。
- `a10-real-segments-v4/projection.json`：完整上海 FeatureRaceLike 样本 106,103 包、5,071 个快照；接收时间和倒带边界拒绝均为 0。`review.json` 的持久任务 completed，五步全部落盘，索引 5 圈官方成绩并保存 5 条本场事实；第 5 圈为 101,529 ms。
- 同一真实报告生成 72 个区段记录、18 组比较；有效区段来自第 2–5 圈，首圈因条件变化或无效状态被排除。各区段最近三圈使用第 3/4/5 圈。例如 T14 入弯/弯心/出弯的第 5 圈相对第 3 圈变化分别为 -14.730 / -35.568 / +49.551 ms，仅为固定距离区段插值观测。
- `a10-finish-verified/summary.json` 四项回归通过：投影、区段复盘、训练记忆与持久工作流。新增完赛后圈号不增仍正确记录终圈、计时重置不丢终圈区段、真正同圈成绩冲突仍失败，以及 result_status 投影检查。先前 `a10-real-segments/` 的失败保留作修复证据；未覆盖或删除原抓包。
- 报告限制文字已明确区段观测与驾驶动作因果/训练闭环的区别。真实 v4 报告生成于此次文字更新之前，其数据结果不变。A10/A11 仍需驾驶动作证据、训练建议及后续圈关联和产品查询入口；原始投影阶段尚未持久检查点化。A13 表格修正为进行中，与已完成的发布包和回放工作保持一致。U01–U04 保留，历史抓包复盘不替代真实游戏或设备验收。

### A11 训练草稿、显式启用与后续圈观测

- 新增 TrainingPlanStore，训练草稿独立于已验证驾驶表现和用户偏好存储，避免把练习意图写成能力事实。基线要求同 UID/epoch/赛道/区段边界/天气胎种管制条件的三圈有效区段，选择耗时极差最大的区段，极差至少 50 ms；该阈值为工程筛选，不代表驾驶收益阈值。
- 首个任务为 segment-consistency-v1：重复自身驾驶动作并观察区段稳定性，不建议改变制动点，也不推断慢圈原因。保留三圈原始区段及来源行号/哈希、耗时中位数与极差；稳定身份重试不重复创建或延长七天有效期。
- 草稿通过 training_plan.py 明确 activate，并要求 after-lap（当前已完成圈），不得早于基线最后一圈。仅同驾驶员/UID/epoch/赛道/区段/条件且圈号大于启用边界的首个有效区段可形成 outcome；切场、倒带和条件不符继续等待。outcome 持久保存后不被后来圈覆盖，标记 subsequent_lap_observation_not_causal_effect；提供 list/cancel 与过期检查。
- session-review-v5 的 training_followup 步骤实际消费区段报告，生成草稿、更新已启用任务的观测，最终报告包含 training_recommendation / training_outcomes。六步检查点与幂等写入衔接；旧版本 task_id 不能混用，新版本使用新 task_id。
- `a11-training-plans/summary.json` 四项回归通过，新增 16 项训练计划检查，涵盖三圈证据、幂等、隔离、启用边界、条件匹配、持久重开、过期、实际工作流从基线到下一圈观测及恢复。合成数据验证完整关联，不作为实际训练收益证明。
- `a11-real-training/review.json`：完整上海正赛投影执行六步 completed，生成 T11-T13 Load Carry 稳定性草稿，基线第 3/4/5 圈，耗时极差 453.162 ms、中位数 5,207.546 ms。`plans.json` 由实际 CLI 读取，状态 draft，outcomes 为空；没有代隼人启用真实练习，也没有补造第 6 圈。
- A11 仍进行中：后续需要驾驶操作证据及更具体练习、跨场训练连续性和产品内交互、明确驾驶员身份、偏好编辑/撤销与记忆消费；当前启用圈号由本地调用者提供，不宣称已与实时最新状态自动核对。用户训练价值验收 U04 仍保留，A01–A13 未整体完成。

### A10 复盘命令终态与投影恢复

- 新增 review_command，两个复盘 CLI 统一区分 completed、cancelled/expired 与 invocation_failed。只有完整 review_report 检查点且状态 completed 才返回退出码 0；取消/过期返回 2，调用错误返回 1。输入冲突即使引用已完成旧任务，也不能显示为本次成功。
- 修复 review_raw_capture.py 对空/中间检查点直接索引最终报告的问题；错误结果写入 review.json 并输出机器可读摘要。新增 review_task.py status/cancel，可由另一进程查看和取消已创建的工作流；原始投影阶段尚不属于该持久任务的取消范围。
- 原始投影增加 manifest 缓存恢复：复用前检查投影版本、源路径/哈希、目标路径/哈希；已提交输入变化或目标损坏明确拒绝，不覆盖证据。manifest 最后以临时文件原子提交；只有投影而没有 manifest 时视作未提交，可重建。用 manifest 对应的非阻塞文件锁排除并发发布。
- 新 manifest 声明 review-projection-v1；旧 manifest 缺少版本时不默认兼容，需要新输出目录重新投影，旧文件保持不变。缓存校验仍需读取文件计算哈希，但不重复解码和组帧。
- `a10-command-final/summary.json` 四项回归通过：投影、复盘命令、训练计划、在途取消。实际子进程覆盖完整/取消复盘退出码、原始抓包 CLI 成功与缓存重试、取消后零检查点、输入冲突与旧任务成功状态区分、缺失抓包结构化错误；同时覆盖损坏/版本/输入变化拒绝和未提交投影恢复。
- A10 仍需将原始投影本身纳入持久任务 deadline/取消及产品工具入口；当前工作流的取消不撤销已提交记忆或训练结果。A01–A13 未整体完成，U01–U04 保留。

### A10 原始投影纳入同一持久复盘任务

- session-review-v6 支持 capture_directory：project_capture 为原始抓包流程的第一个持久步骤，随后六步使用具名检查点结果，避免插入阶段后位置索引错位。标准化投影直接复盘仍为六步。
- 投影沿用受限工作执行器、同一个 TaskContext 和持久 expires；取消从 review_task.py 传播到投影读包/哈希/发布检查，超时工作不交付晚到结果。原始命令 --timeout 定义全任务预算，默认 300 秒；旧 --projection-timeout 作为同一参数别名保留，不再额外为后续复盘发放预算。
- 投影成功后其原始 SHA/投影 SHA/路径/计数进入检查点及最终 capture_provenance。分析失败重试跳过已提交投影，保留最初 expires，不重复解码或延长预算。任务创建前的源文件哈希用于绑定输入，按总预算计时；此短暂准备阶段尚没有可取消的持久记录。
- 修正真实在途超时被 execute_review 归类为普通调用失败的问题：当 TimeoutError 对应持久 expired 状态时，返回 expired 与退出码 2。输入冲突仍是独立 invocation_failed，不能沿用旧任务状态。
- `a10-durable-projection-final/summary.json` 七项相关回归全部通过；新增故障注入验证投影中取消、受同一 deadline 约束、取消/过期无检查点或投影发布、分析失败后恢复、保留原 deadline，以及报告绑定原始与投影哈希。阻塞读包使用假输入暂停，释放后确认工作结束；不是强制杀死线程。
- `a10-raw-v6/review.json` 与 verification.json：完整上海正赛原始抓包 106,103 包、5,071 快照，七步 completed，5 圈官方成绩、18 组区段比较，生成 T11-T13 草稿，无后续圈效果。使用同一实际 CLI 再次运行退出 0，attempts 仍为 7，没有重复执行步骤。
- 这项实现替代前两节“投影阶段尚未接入持久取消”的限制。A10 仍需产品能力注册/Agent 工具与查询入口、跨进程故障恢复完整验收；A01–A13 与真实 U01–U04 未整体完成。

### A12 完整场次导出分组与六个训练入口治理

- 导出前按 metadata 的完整 session UID 固定样本分组，拒绝同 UID 在不同样本中被配置到不同集合、重复样本名对应不同 UID、未知分组和未知配置样本名。处理实际快照时核对 metadata UID，拒绝来源冒配；被 UnifiedStateStore 拒绝的旧状态不再进入训练导出。
- tactical / attack / strategy-action 全部继承主特征的场次分组，移除按圈号、帧号取模和已算标签重分配 val/test 的逻辑。保留 ShortResultLike 的 LOW_FUEL 业务过滤；过滤可减少某集合样本，但不能把它们重新分配以改善指标。manifest 增加 export-session-split-v1、完整 UID→集合映射与 label_independent 标记。
- attack_opportunity、front_attack_commit、rear_threat、yield_vs_defend、event_impact、counterattack_window 六个训练入口使用 session_partitions，删除随机逐行 train_test_split 回退。缺 val 时只从 train 中选择完整场次；缺少必要场次或存在跨集合 UID 时失败。test 不再因正类不足被替换成训练行抽样。CSV 显式按字符串读 UID，避免 uint64 精度丢失；报告记录实际分组 manifest。
- `a12-partitions-release-check/summary.json` 三项回归通过：导出分组、统一分组、六个真实训练 CLI。覆盖圈/帧/标签变化不能改集合、别名样本冲突、实际 fixture 生成六张 CSV 的分组与 metadata 校验；六个训练入口拒绝跨集合 UID。另外使用三个独立 UID 的合成数据实际训练攻击模型并核对报告的完整 UID 清单，该训练仅验证入口，不证明赛车模型质量。
- 六场真实抓包导出已启动，输出 `a12-real-export/`，stdout `/tmp/asurada-a12-real-export.stdout.json`。该命令的 --sample-limit 120 只控制主表保留行数，内部仍处理完整场次，领域表保留其过滤后的全量行。此节写入时运行句柄 89257 仍在执行，尚无最终 manifest；不得标记为通过或以重启替代等待。
- A12 尚待完成：driver_style、tyre_degradation_trend、short_horizon_risk_forecast、rival_pressure、defence_cost、strategy_action 的其他分组路径继续审计；预测窗口间隔、真实标签/跨驾驶员评价与统一特征契约尚未全部覆盖。原导出和已部署模型资产未被替换，U01–U04 保留。

### A12 剩余训练入口的场次隔离与聚合前校验

- driver_style、tyre_degradation_trend、short_horizon_risk_forecast、rival_pressure、defence_cost、strategy_action 六个入口全部接入完整场次分组。删除基于 session_type 和第二圈重设 val/test 的策略，原有 assign/derive 函数仅保留原始分组；策略动作保留类别覆盖检查。
- 新增 validate_session_frame：在窗口聚合、目标构造或业务过滤前核对 UID 与分组，避免聚合 first 值掩盖同 UID 的不同 split。六个入口显式按字符串读 UID；session_partitions 共用该校验。
- 驾驶风格聚合增加 split_first，并恢复完整 session_uid，三个模型消费同一场次隔离分区，父报告记录 manifest。轮胎趋势和短期预测在构造目标后先确定完整场次分区，再生成各模型报告，使总行数与模型分区一致；各单模型报告记录实际 manifest。
- `a12-remaining-partitions/summary.json` 三项回归通过：新增剩余六个真实 CLI 的变换前泄漏拒绝、圈号/场次类型不改分组；实际驾驶风格 main 执行窗口聚合，用假学习器检查三个模型收到正确的三个独立 uint64 UID 和报告分区。既有六个入口拒绝及实际合成攻击模型训练验证也通过。
- 当前 train_*baseline*.py 与导出脚本搜索未发现 train_test_split、lap_number==2 分组或 frame_identifier 取模分组路径。该静态结果与入口回归共同证明本轮分组迁移，不证明模型泛化或真实目标质量。
- 上一轮真实导出继续同一会话 89257；本轮查询仍在运行，未返回退出状态，最终 manifest 尚待获取。没有重新启动或缩小已启动的导出工作。
- A12 仍进行中：未来标签时间窗口完整覆盖、倒带/轮胎更换等边界、必要的时间间隔策略、全部特征契约统一，以及跨驾驶员/赛道的真实质量评估证据仍需补齐。分组正确不把伪标签拟合升级为真实驾驶收益。U01–U04 保留。

### A12 未来标签完整窗口与连续性证据

- 新增 training_windows.py，保持原始行顺序，按完整 UID 及连续运行片段选择未来窗口。时间倒退/重复、超过 1 秒的采样间隔、无效时间及显式 epoch 变化会截断窗口；不再先按 session_time 排序而掩盖倒带。窗口必须有观测覆盖到目标时刻，场次尾部不足时长不生成标签。
- 轮胎趋势增加胎种一致、胎龄/磨损不回退的片段约束，阻止跨换胎或磨损重置推导趋势。终点为目标时刻之后第一个有效观测，实际起止时刻被记录；不宣称它恰好等于名义预测时长。1 秒最大间隔是当前工程门限，尚未作为数据质量最优阈值验收。
- 短期风险只统计名义窗口内的观测；没有真实下一赛段样本时 next_zone 保持缺失，不再用窗口最大值代填。各模型按自身目标缺失筛选，3 秒风险可用行不会仅因下一赛段目标缺失被排除。
- target_window 保存窗口版本、UID/可用 epoch、连续片段号、起止时间/record_id、名义时长和间隔门限。两个训练入口把实际目标窗口与标签写入 target_windows.csv，父报告保存文件 SHA、行数、源特征/标签文件路径与 SHA；子模型报告记录窗口策略版本和场次分组。
- `a12-future-windows-release-check/summary.json` 三项回归通过，包括 20 个窗口检查：真实两个 main 执行数据读取/标签构造/窗口文件保存，假学习器核对输入；覆盖不足时长、缺口、倒带、epoch、换胎/磨损重置、缺值、无下一赛段及非法 horizon。该验证不包含真实模型质量或跨场次未来预测收益。
- 前述真实六场导出仍在同一运行 89257 中，当前未返回终态；没有把已落盘部分 CSV 视作完整导出验收。
- A12 尚待完成：其他派生未来标签的窗口约束、字段/特征版本统一、稀疏样本下的数据可用率和真实跨驾驶员/赛道评估。当前完整 UID 分组已避免同场窗口跨 train/val/test，但不能据此声称全部时间相关泄漏或领域混杂已解决。U01–U04 保留。

### A12 特征标签一对一合并与记录身份

- 新增 join_training_labels，资源风险、防守成本、对手压力和短期预测四个入口接入。要求两表 record_id 非空且唯一、记录集合完全一致，并核对 UID/split；双方都提供的 epoch/frame/sample_name 也必须匹配。重复记录、静默丢行、外场标签或已有同名目标列明确失败，不再做未检查的 inner join。
- 合并保留特征原顺序，报告记录 training-join-v1、目标列、身份列、行数和身份清单哈希。旧标签文件若缺少 UID/split，需使用规范导出重新生成，不能凭 record_id 猜测标签归属。
- 导出新增 session_epoch；主特征和标签共用 training_record_id，标识由 UID、epoch、overall frame 和 frame 组成，缺 overall 时使用接收时间作为替代字段。manifest 声明 session-epoch-overall-frame-v1，避免倒带后同游戏帧号碰撞。
- 真实导出审计发现攻击表不同车辆视角复用了同一 record_id。现在攻击样本 ID 加 actor_view，source_record_id 保留对应主快照身份；不改变同场分组，避免把两个视角误当成重复或一条样本。
- `a12-label-join/summary.json` 四项回归通过；实际四个 CLI 拒绝外场标签，覆盖重复/缺失记录与重排匹配。后续身份回归验证 epoch/overall 区分、实际 fixture 导出 epoch，以及两个 actor 的唯一 ID 和共享来源；最终证据见 `a12-record-identity-verified/summary.json`。

### A12 六场真实导出最终结果

- 原运行 89257 已正常结束，退出码 0；不再等待或重启。`a12-real-export/manifest.json` 已生成，`partition-audit.json` 对六张实际 CSV 逐行核对。
- 主特征和标签各 720 行（每场最终保留 120），6 个 UID，train/val/test 为 480/120/120；一一对应且无重复 ID。领域表为 tactical 72,166、event 1,512、attack 144,566、strategy-action 73,178 行，所有表行数与 manifest 一致、所有 UID 分组错配为 0。
- 攻击表原始导出有 72,143 个重复 ID，对应车辆视角问题；partition-audit 的分组检查通过，但 record_identity_audit_passed=false，不能将该旧表视为身份完整性验收通过。该运行在 epoch/actor 身份修改前已载入代码，新身份规则仅有针对性回归，未声称旧导出自动更新。
- tactical/attack 未导出 val 行是业务样本过滤后的真实数据分布，训练入口只能按完整训练场次选择验证场次，不能恢复逐行抽样。数据不足或类别缺失仍须明确报告。
- 额外核对 pit_rejoin_traffic_baseline：当前只是字段/候选采样就绪检查，没有实际模型训练；其 ready_for_sampling 不属于训练质量通过。A12 的特征版本、其他未来标签边界及真实质量评估仍未全部完成，A01–A13 与 U01–U04 保持原范围。

### A03/A04 拒绝显式旧 epoch 和已离开场次回流

- SessionState 增加内部 session_epoch_explicit 标记，decode_snapshot 区分明确提供 epoch 的快照和缺省 epoch 的旧格式；明确 epoch 只接受非负整数，拒绝布尔、负数、小数和字符串。序列化仍沿用 telemetry-v1 的明确 session_epoch，内部标记不参与领域事实指纹。
- SessionLifecycle 不再把明确旧 epoch 的快照提升为当前 epoch；旧格式仍可按原计数器规则推断倒带。保留最近 16 个已离开 UID，拒绝迟到旧场重新打开历史。缺失/非法计数器不再清除同 epoch 已有水位；计数器仅接受合法 uint32 整数值。
- ConsoleVoiceOutput.bind_session 返回是否接受，拒绝较低 epoch 和最近已离开的 UID。主动提示、直接查询、语音问答及场次相关控制入口在拒绝时发出 suppress，不更换 scope、不排入旧回答或清除当前队列。全局 stop/cancel 直接作用于当前队列，遥测陈旧不能阻止用户停止。
- `a04-stale-scope-final/summary.json` 八项回归通过。新增 12 个检查覆盖显式旧 epoch 即使 overall 更新仍拒绝、缺计数器不抹水位、退场 UID、非法 epoch、主动/问答旧状态不发声，以及陈旧遥测仍可停止。既有 packet epoch 往返、快照绑定、语音控制、复盘和实际导出 fixture 验证通过。
- 当前退休 UID 清单为每对象内最多 16 个，不是跨进程永久身份账本；重新播放同一历史场次应使用新的运行实例。计数器回绕、同 epoch 的回复新鲜度、权威跨进程场次事件和在途 ASR/LLM 取消仍未整体完成，不能宣称 A03/A04 已全部交付。
- 启动 `contracts-integration-4/` 完整 contracts 回归，覆盖当前脚本集合。此节写入时运行句柄 8574 已返回多项结果，尚未生成最终 summary；dashboard_websocket 已确认因沙箱禁止本地端口 bind 失败，需在最终清单后定向复验。后续沿用同一运行读取结果，不能提前记为通过。真实 U01–U04 保留。

### A13 当前 95 项契约复核结果

- `contracts-integration-4/summary.json` 的同一运行 8574 已结束：95 项 contracts，82 passed / 13 failed / 0 skipped。12 项失败为沙箱拒绝本地回环端口 bind；1 项为 macOS TTS 导出的空音频被生产校验正确拒绝。
- 获准在主机环境定向复验这 13 项，`contracts-integration-4-host/summary.json` 全部通过，运行 86048 已结束。测试使用回环假服务与 TTS 文件导出，未作为云端 API 或实际扬声器验收。
- `contracts-integration-4/combined-verification.json` 核对失败集合与重跑集合完全相同、重跑全部通过且无跳过。两份结果合计覆盖当前 95 项契约，不是一次干净全过运行，也不包括完整 phase1 历史回放或真实游戏/设备测试。
- 本轮完成后 A01–A13 仍有明确剩余工作，尤其唯一跨进程声音服务、统一任务/场次广播、能力与产品入口、跨端契约、模型质量与发布包复验；不据本轮测试将总目标标记完成。U01–U04 保留。

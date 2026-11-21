# 阿斯拉达代码级进度检查

检查日期：2026-09-08。范围：当前本地工作区，F1 25 基础版，不含 2026 Season Pack。

## 结论

核心遥测、规则策略、赛道语义及日志回放已构成可运行的开发机系统。模型和长周期策略已经进入运行链，接入程度比部分文档描述更深，但模型质量准入、测试时钟和交付复现仍未收口。不能用 STATUS.md 的 98% / 70% / 35% 作为验收结果。

本次只检查代码和运行测试，没有修复业务代码或改动原有状态文档。新增本报告及回归结果副本。当前 HEAD 为 e170247，最近提交日期 2026-07-17；工作区存在大量未提交实现，评估包含这些文件，不能由提交时间推断实际工作时间。

## 验证口径

- 找到并执行 52 个回归脚本：阶段一 17 个，阶段三 35 个。
- 51 个专题脚本使用项目虚拟环境；主回归另做无 LightGBM 的完整会话验证及启用模型的有界抽查。
- 允许本机测试所需权限后，专题脚本 41 个通过、10 个失败。主回归在规则降级环境通过，因此按这套混合口径为 42/52；这不是全模型全链路通过率。
- 10 个原样失败：8 个测试时钟问题、2 个接口/路由上下文问题。仅在检查进程中注入匹配上下文后，10 个均通过；文件本身仍然失败，不能算已修复。
- 11 个本机 HTTP/流式接口测试初次被沙箱阻止监听端口，获准重跑后全部通过。
- macOS say 导出初次产生空音频，沙箱外重跑通过，生成 68,604 字节 WAV、32 个流式块。此项是本机合成验证，不是人工听感或云端实测。
- 151 个 Python 文件语法检查通过；live-dashboard/static/app.js 的 node --check 通过。
- 未进行游戏现场联机、真实麦克风问答、云服务计费调用、Pi/CM5 真机、iOS 构建或浏览器视觉验收。

## 主链回归

规则降级环境使用系统 python3；检测确认该解释器无 LightGBM，输出模型候选帧数为 0。

| 数据 | 帧数 | 结果 |
| --- | ---: | --- |
| 总抓包前段 | 400 | 通过 |
| 排位会话 uid13 | 5,163 | 通过 |
| 结果会话 uid8 | 4,879 | 通过 |
| 冲刺赛 uid15 | 3,166 | 通过 |
| 正赛 uid16 | 5,071 | 通过 |

四个完整会话共 18,279 帧；加总抓包前段为 18,679 帧。仲裁、战术状态机及长周期契约检查通过。

项目 .venv 可实际加载 14 个模型组件。全模型抽查上述五组各 200 帧，共 1,000 帧，全部完成 generic health 验证，每组均出现 200 个模型候选帧；仲裁、战术状态机和长周期契约通过。但截断会话未到 FinalClassification，排位前段的主导后车 gap 来源也与完整会话不同，所以原报告 passed=false，不能宣称完整全模型验收通过。最初启动的完整全模型会话回归因成本改为此有界检查，已中断，未形成通过报告。

独立性能抽查：OMP_NUM_THREADS=1，合成正赛状态，预热 3 帧后连续 100 次 StrategyEngine.evaluate，14 个模型启用；P50=44.37ms，P95=53.16ms，最大=57.29ms，超过 100ms 的帧为 0。该结果仅覆盖策略函数，不能代替 UDP 到播报的端到端延迟及长时间稳定性验收。并发运行其他回归时曾观察到明显更高耗时，不用该竞争条件下的数据给出实时性结论。

## 模块状态

| 模块 | 代码级事实 | 当前判定与缺口 |
| --- | --- | --- |
| 输入和组帧 | CLI 接入 Replay、CSV、raw capture、live UDP；live/capture 复用 StrategyRuntimePipeline | 主链存在且回放可验证；现场 UDP 长跑未测 |
| 协议 | pdu_decoder 有 0-15 包族分派及相应正文解析，包括 LobbyInfo、LapPositions | 不能从有解析函数推导所有字段和异常场景完成；稀有事件/联机仍缺本次实测 |
| 赛道 | 27 个布局可加载、分段和预视，刹车点/档位目标可生成 | 基础版范围完整；27 个真实现场逐一跑圈未做 |
| 规则策略 | SessionModeRouter、状态评估、风险、候选、状态机、置信度、fallback、arbiter 均被 evaluate 调用 | 已进入运行主链，完整规则回放通过 |
| 模型 | 14 个模型加载成功并参与逐帧推理 | 已集成但质量不齐，没有统一质量准入与运行模式开关 |
| 长周期 | PitWindowSupport.evaluate 和 LongHorizonStrategyBaseline.plan 被逐帧调用；结果送仲裁 | 确定性启发式规划已接入；不是经过实战收益验证的全场模拟器 |
| 语音 | ASR、语义归一化、路由、回答、TTS、队列、唤醒词、刹车点、档位、进攻模式均有实现 | 本机契约多数可测；旧时间戳使多项原样回归失败，云端/麦克风现场未验收 |
| 看板 | live runtime 写原子 feed；HTTP/WS 看板读取；离线看板从日志重建 | 数据路径已实现，离线生成检查通过；本次未做浏览器视觉检查 |
| iOS | AppState 实现 USB NDJSON/CSV、TCP/Bonjour 接入、圈数据、回放、损伤 Live Activity；CompareView 消费真实圈记录 | 超过纯页面骨架，但本次仅代码检查，尚不能认定交付就绪 |
| 工程交付 | 现有 venv 和本机绝对路径能运行；大量代码、报告未提交 | 干净安装、统一测试失败退出、模型资产发布、设备部署仍缺闭环 |

## 需要纠正的既有判断

### 1. 前后车摘要并非缺少实现

state_summary_for_llm.py:31 先按名次寻找前后车，:82-83 构建摘要，:87 在非比赛模式下掩码。runtime_context.py:32 按当前墙钟和 source_timestamp_ms 计算年龄，超过 15 秒切到 companion。

原测试使用固定历史时间戳，因此前后车、损伤等内容被正确掩码。仅将检测时钟对齐到测试状态时间，相关检查全部通过。上次把它表述成“摘要字段没有正确生成”不够准确，应改为“测试时钟没有匹配状态新鲜度契约”。

真实回放另有产品边界：packet_snapshot.py:273 保留抓包 received_at_ms；capture_runtime.py 的 session-paced 只按游戏时间等待，没有建立查询用的回放时钟。因此直接把历史快照交给现有语音/LLM 路由仍会进入过期模式。需要显式区分实时和回放上下文，同时保留实时数据过期保护。

### 2. 长周期策略已进入主链

strategy.py:936 传入真实 session_route 调用进站支持，:944 调用 plan；arbiter.py:375 起读取其分数并影响动作排序。两个失败测试漏传 session_route；它们的 fixture 同时缺 timing_mode/timing_support_level，直接让默认路由解析会落到非比赛分支。

检查进程中为 fixture 注入正赛路由后，天气/历史 5 项与对手进站/DRS/损伤 7 项检查全部通过。应修测试调用和 fixture，而非根据 TypeError 判定运行主链没有长周期能力。

该模块使用固定胎寿命、经验权重和未来数圈候选打分。可以输出进站圈、胎种、可用胎组、交通代价和攻击倾向，仍需要真实比赛结果标定。

### 3. 训练模型不等于运行模型

实际运行的 14 个组件：strategy_action；fuel/ers/tyre/dynamics risk；front/rear/combined rival pressure；entry/apex/exit quality；两种 tyre trend；defence_cost。

rear_threat、attack_opportunity、front_attack_commit 存在训练脚本/产物，但当前 StrategyEngine/model_runtime 没有加载这三份 booster。strategy.py:436 的攻击机会是规则公式。不能将三份离线训练报告算作已上线攻击模型链。

### 4. “仅旁路观察”与当前行为不符

arbiter.py:378-455 使用燃油、动态、后车压力、驾驶质量、轮胎趋势和防守成本调整 LOW_FUEL、DYNAMICS_UNSTABLE、DEFEND_WINDOW、ATTACK_WINDOW 等动作排序。因此其中多个模型已经影响最终输出。

model_runtime.py:363 的加载器主要验证报告、依赖和模型文件存在，没有按测试质量决定 observe/active/disabled。

- fuel risk 当前报告 MAE=20.80，RMSE=39.26，测试目标全部为 20，R2=0；模型仍启用，且燃油分数影响仲裁与进站支持。
- front pressure 报告 R2=0、ranking accuracy=0，仍被加载计算；本次所查仲裁主要消费 rear pressure，不能宣称前车压力直接影响所有决策。
- strategy_action 总体准确率 99.67%，但仅覆盖 NONE/LOW_FUEL/DEFEND_WINDOW/DYNAMICS_UNSTABLE 四类；DYNAMICS_UNSTABLE precision=52.34%、recall=69.14%，不能用总体准确率代表各类可用度。
- counterattack 正样本 train=1、val=1、test=0；pit rejoin 仅 11 条候选记录。两者不具备成熟模型验收证据。

## 原样失败的 10 个专题脚本

以下 8 个按实际测试状态对齐时钟后全部通过，原文件未修改：

1. phase1_rival_state_mainline_regression.py
2. phase1_llm_summary_auxiliary_fields_regression.py
3. phase3_llm_boundary_regression.py
4. phase3_companion_mode_regression.py
5. phase3_llm_sidecar_integration_regression.py
6. phase3_semantic_voice_regression.py
7. phase3_voice_input_regression.py
8. phase3_wake_word_regression.py

以下 2 个补齐正赛路由契约后全部通过，原文件未修改：

9. phase1_long_horizon_forecast_history_regression.py
10. phase1_rival_pit_window_support_regression.py

部分脚本即使输出 passed=false，仍以退出码 0 结束（例如 rival_state_mainline）。测试汇总必须解析顶层 passed 或正确失败退出，不能仅看进程退出码；也不能递归把 requires_confirmation=false 一类业务字段当失败断言。

## 其他交付缺口

- pyproject.toml 未声明 pandas/LightGBM 等运行依赖或模型可选依赖；模型报告指向本机绝对路径。当前环境成功不等于新机器安装即可复现。
- 未找到仓库 .github 工作流或 iOS/看板专用自动化测试目录；应补统一运行和验收入口。
- 语音有下行暂停/冷却和 partial 预览机制，不能等同 AEC；未见本次可验收的回声消除、Pi/CM5 设备恢复完整链。
- iOS CompareView.swift:24 按数组下标配对两圈，缺少按圈距/时间插值对齐。不同采样率或丢包时，速度/踏板对比可能比较不同位置，属于分析正确性待补。
- 看板 feed 文件最后修改时间为 2026-04-13，仅说明检查时没有新鲜 feed 证据，不能据此认定实时服务正在工作或一定没有运行。

## 下一步顺序与验收标准

1. 收口回归契约：修 8 个时钟 fixture、2 个路由 fixture，统一失败退出码，区分单元模拟、回放、模型和设备测试。验收：支持的环境中原样跑全部回归，无需检查进程临时补上下文。
2. 模型准入：引入 disabled/observe/active，先处理燃油等不合格模型参与排序的问题；固定模型资产与依赖。验收：每个最终动作可追溯到启用模型版本及依据，observe 模式不改变排序。
3. 全模型实战验证：固定数据、全部会话完整回放，对比规则基线；记录端到端 P95、过期帧、丢包、误报与抖动。当前 1,000 帧抽查不替代此项。
4. 完善长期策略：根据真实进站损失、轮胎衰退和比赛结果标定权重，覆盖安全车、天气变化、可用胎组和回场交通；以收益/误判指标验收。
5. 产品交付：实时/回放查询时钟分离、语音 AEC 与断线恢复、看板断流提示；iOS 圈距对齐和真机验证；再推进 Pi/CM5 封装。

## 证据文件

- phase1-rules.json：原主回归报告，passed=true，规则降级环境。
- phase1-models-bounded.json：原主回归报告，passed=false，截断会话导致末尾成绩等断言不满足；五组基础健康检查通过。
- 其余专题回归、临时契约注入和性能测试结果见本次任务工具记录；这些检查未修改源脚本。

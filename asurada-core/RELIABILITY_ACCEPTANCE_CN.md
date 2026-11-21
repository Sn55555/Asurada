# F1 25 核心链路可靠性验收

范围：F1 25 基础版，不包含 2026 赛季包。本文记录代码变更的验收边界，不代表所有赛道或真实游戏已经验收。

## 已实施

- 8 个历史时间戳测试使用局部运行时钟，生产环境的 15 秒遥测过期保护保持不变。
- 2 个长周期规划测试补齐 session_route 契约。
- 回归脚本通过 emit_result 返回失败退出码；统一入口同时检查进程退出码和 JSON 判定。
- ModelAdmissionPolicy 管理 disabled / observe / active；未列出的模型默认为 disabled。
- 默认 12 个模型 observe，fuel_risk 和 front_pressure disabled。观察预测保留在调试数据中，不进入模型候选、仲裁分数或长周期规划。
- active 必须提供非空 evidence 引用。当前代码只校验引用非空，不自动核验报告真实性、模型哈希或效果指标；这不是自动质量认证系统。
- 策略入口允许用 model_policy 显式注入策略；当前没有新增用户界面的开关或 CLI 准入文件入口。

## 可复现入口

在仓库根目录运行，使用已安装模型依赖的项目虚拟环境：

```sh
asurada-core/.venv/bin/python asurada-core/scripts/run_regressions.py --suite contracts --output output/reliability-2026-09-08/contracts-final
```

测试包含本机 HTTP 假服务和系统语音后端，需允许本机端口绑定和系统语音调用。通过假服务测试不等于已连接真实云服务。

完整会话对照（四个 sample 分别运行）：

```sh
OMP_NUM_THREADS=1 asurada-core/.venv/bin/python asurada-core/scripts/compare_model_replay.py --sample shanghai_qualifying_like_uid13 --output output/reliability-2026-09-08/replay/shanghai_qualifying_like_uid13.json
```

另外三个 sample 为 shanghai_short_result_like_uid8、shanghai_sprint_race_like_uid15、shanghai_feature_race_like_uid16。

对照实验使用全部 14 个模型 observe 与全部 disabled，相同状态历史逐帧比较最终消息和长周期规划，同时检查解码错误、路由越界、最终成绩包及模型加载情况。

## 验收边界

### 2026-09-08 实测结果

- 最终契约回归：53 通过、0 失败、0 跳过。证据：`../output/reliability-2026-09-08/contracts-final/summary.json`。
- 四个完整会话共 18,279 帧；每组全部 14 个模型加载成功、最终成绩包已出现。解码错误、路由越界及观察模式相对禁用模型基线的不同帧均为 0。
- 完整报告位于 `../output/reliability-2026-09-08/replay/`，文件名对应 sample 名。

| 会话 | 帧数 | 主动作切换次数（两组相同） | disabled P95 ms | observe P95 ms |
| --- | ---: | ---: | ---: | ---: |
| qualifying uid13 | 5163 | 256 | 1.462 | 256.162 |
| short result uid8 | 4879 | 0 | 1.501 | 257.447 |
| sprint uid15 | 3166 | 45 | 4.078 | 276.189 |
| feature race uid16 | 5071 | 19 | 3.765 | 256.275 |

四组并发运行，含 CPU 竞争；这些耗时不是单路实时验收结果。观察模型仍在同步推理，隔离决策影响不等于隔离计算开销。性能优化需要另做单路测量和调度验证。

short result 全程 NONE，只覆盖静默路径；其他样本覆盖车辆不稳定、前轮负载、防守、攻击窗口和 ERS 提示，但不代表全部动作、全部驾驶情境均已覆盖。排位样本的 256 次动作切换值得进一步按时间和事件检查，不能直接判为误报。

- 完整回放证明历史样本上的隔离与稳定性，不证明模型建议优于规则。
- 动作切换次数只是抖动观测指标，缺少逐帧人工真值时不能称为误报率。
- 延迟仅计策略 evaluate，不包含音频、日志、UDP 收包和端到端播报。并发跑多个会话时，数据含 CPU 竞争，不应用于实时吞吐承诺。
- 27 个基础赛道布局的语义结构覆盖，与所有赛道实车跑通是两种验收；已有真实采集只覆盖少数赛道。
- 当前历史抓包路径和训练报告中的模型路径仍依赖本机资产；跨机器可复现性尚需资产清单、路径可移植性及依赖锁定。
- 2026-09-08 游戏联调未收到 UDP；用户报告游戏闪退并要求先推进其他工作。现场收包、实时策略和实际听感验收暂停，不计为通过。

## 模型输入编码优化（同日后续）

- 已定位并移除每次推理重复构造 Pandas 表及类别转换的主要开销。RuntimeFeatureEncoder 按模型保存的类别词表编码，未知类别为 NaN；缺失类别沿用 UNKNOWN 处理；数值转换仍使用 Pandas 的 coercion 语义。
- 14 个现有模型使用数值矩阵快速路径；元数据或特征类型不兼容时保留原 DataFrame 路径。单行模型推理明确使用 1 个线程，未跳帧、未降低模型调用频率，也未放宽准入规则。
- 54 项契约测试全部通过，0 失败、0 跳过：`../output/reliability-2026-09-08/contracts-encoding/summary.json`。
- 70 组边界输入预测差异为 0（绝对容差 1e-12），四个会话的 141 个抽样帧最终消息及全部 debug 数据完全一致。该测试比较旧 DataFrame 路径与新编码路径，不是模型质量验收。
- 未并发启动其他回归的单进程配对复测：旧路径 P50/P95 为 101.154/174.905ms，新路径为 2.692/4.516ms，P95 降低约 97%。按帧交替测量顺序，模型预测线程数为 1。两项兼容回退断言也通过；证据：`../output/reliability-2026-09-08/encoding-isolated/model_encoding_regression.stdout.txt`。这是本机抽样测量，受机器状态影响，不是跨设备性能承诺。
- 四组完整回放再验证 18,279 帧全部通过，解码错误、路由越界及观察模式相对禁用基线的决策差异均为 0；各会话动作计数与优化前报告一致。证据：`../output/reliability-2026-09-08/replay-encoding/`。

| 完整会话 | 优化后 observe P95 ms | 超过 100ms 的帧数 |
| --- | ---: | ---: |
| qualifying uid13 | 2.989 | 0 |
| short result uid8 | 2.614 | 1 |
| sprint uid15 | 5.327 | 2 |
| feature race uid16 | 4.714 | 0 |

完整回放测量期间部分测试并发，仍有少量耗时尖峰；只统计策略 evaluate，不含收包、日志和音频。不能据此宣称全链路延迟达标。

## 后续顺序

1. 对代表性驾驶事件进行人工标注，建立误报、漏报、提前量和建议持续时间的基线。
2. 分模型比较规则基线与 active 实验组，覆盖独立赛道、会话和驾驶风格；禁止仅凭训练集精度放行。
3. 将准入证据绑定模型文件哈希、数据切分和报告版本；补齐可移植资产与依赖安装流程。
4. 游戏恢复后验证 UDP 20777 的真实数据，再验收断流恢复、连续驾驶稳定性及语音打断/时效。
5. 扩充未实测赛道抓包，逐赛道检查区段定位、刹车点和弯道提示；继续排除 2026 赛季包。

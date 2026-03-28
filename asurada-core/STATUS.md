# Asurada Core 项目状态总看板

## 文档用途

这份文档是 Asurada Core 的统一状态总看板，用来回答四个问题：

- 现在做到了什么程度
- 哪些已经完成
- 哪些还没完成
- 下一步最该做什么

本文件优先面向项目推进，不是协议细节文档。协议覆盖、未完成字段、模型输入等细节分别见：

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](STAGE2_MODEL_INPUT_SCHEMA.md)

## 当前总进度

- 阶段一总体进度：`90%`
- 阶段一排除实时闭环后的进度：`95%+`
- 阶段二准备工作进度：`30%`
- 阶段三产品化进度：`0%`

当前结论：

- 离线真实抓包策略主链已经打通
- 调试面板已经具备工程级检查能力
- 阶段二模型数据准备已经开始成型
- 当前最大未完成项是实时 UDP 全闭环

## 阶段总览

### 阶段一：核心开发闭环

目标：

- 在开发机上打通完整核心链路
- 完成真实包解析、状态标准化、策略推理、日志回放、调试面板
- 形成可继续扩展的策略脑骨架

当前状态：

- `基本完成`

当前完成度：

- `90%`

当前主要未完成项：

- `live UDP` 完整实时闭环
- 部分协议字段的精修与命名收口

### 阶段二：模型与边缘化准备

目标：

- 为后续模型训练、特征工程、边缘部署做数据和结构准备

当前状态：

- `已启动`

当前完成度：

- `35%`

当前已启动工作：

- 真实包高价值字段覆盖
- 未完成字段清单
- 模型输入 schema
- debug 链路解释能力
- 赛周分会话样本切分与命名归类
- 阶段二训练目录与数据集配置
- 第一版 `features / labels / tactical_features_v1` 导出
- `rear_threat_model` baseline 训练入口
- `rear_threat_model` 第一版 baseline 已跑通
  - 当前结论：已得到第一版可用 baseline
  - 当前指标：`accuracy=0.9799`、`positive precision=1.0000`、`positive recall=0.8182`
  - 当前阈值：验证集自动扫描选择 `threshold=0.4`
- `yield_vs_defend_model` baseline 已尝试
  - 当前结论：训练链路已打通，但标签稳定性不足，暂不作为阶段二当前推进主线
  - 当前状态：`暂停`
  - 重启条件：拿到更稳定的后验 `yield_vs_fight` 标签，或补到更完整的攻防专题样本
- `event_impact_model` baseline 已尝试
  - 当前结论：事件专题导出与训练链路已打通，但当前样本量和标签信号不足，baseline 不稳定
  - 当前状态：`暂停`
  - 当前症状：
    - 全事件集合训练存在跨 session 分布偏移
    - 收紧到 race-like + 高信号事件后，样本量过小，泛化失败
  - 重启条件：
    - 补更多 race-like 事件样本
    - 或重做更稳定的事件后验标签
- `front_attack_commit_model` baseline 已跑通
  - 当前结论：第一版 baseline 可用
  - 当前指标：`accuracy=0.9996`、`positive precision=0.7647`、`positive recall=1.0000`
  - 当前验证：
    - 已通过 `player + rear_rival` 双视角攻击样本导出打通跨 session 外部 test
    - 已通过 `uid15` 第 2 圈显式切出 exported val，不再依赖 `train_holdout_split`
    - 当前训练主样本来自 `uid15` 第 1/3 圈
    - 当前 exported val 主样本来自 `uid15` 第 2 圈
    - 当前外部 test 主样本来自 `uid16`
  - 下一步收口方向：
    - 继续收紧 `attack_commit_proxy_label`，降低剩余误报并增强 DRS/持续逼近信号
    - 补更多 race-like 攻击样本，验证跨 session 稳定性是否可持续
- `attack_opportunity_model` baseline 已跑通
  - 当前结论：第一版 baseline 可用
  - 当前指标：`accuracy=0.9994`、`positive precision=1.0000`、`positive recall=0.7931`
  - 当前验证：
    - 已通过 `player + rear_rival` 双视角攻击样本导出打通跨 session 外部 test
    - 已通过 `uid15` 第 2 圈显式切出 exported val，不再依赖 `train_holdout_split`
    - 当前训练主样本来自 `uid15` 第 1/3 圈
    - 当前 exported val 主样本来自 `uid15` 第 2 圈
    - 当前外部 test 主样本来自 `uid16`
  - 当前意义：
    - `front_attack_commit_model` 已有可训练上游，不再只依赖规则型 `attack_opportunity_label`
  - 下一步收口方向：
    - 继续扩展 race-like 攻击样本，验证 `attack_opportunity -> front_attack_commit` 是否在更多 session 中稳定
    - 继续观察 exported val 与外部 test 的 recall 差异
- `strategy_action_model` baseline 已跑通
  - 当前结论：第一版干净 baseline 可用，但只覆盖高频动作子集
  - 当前动作范围：
    - `NONE`
    - `LOW_FUEL`
    - `DEFEND_WINDOW`
    - `DYNAMICS_UNSTABLE`
  - 当前指标：
    - `top1_accuracy=0.7052`
    - `top2_accuracy=0.9998`
  - 当前验证：
    - `validation_source=exported_val_split`
    - `test_source=exported_test_split`
    - 当前训练文件：`strategy_action_features_v1.csv`
    - 当前 test 主样本来自 `uid16`
  - 当前意义：
    - 已可为 `strategy_arbiter_v2` 提供 `top-k` 候选
    - 当前 exported `val/test` 条件下，`top-1` 明显弱于 `top-2`
    - 当前不适合直接 top-1 直出
  - 下一步收口方向：
    - 继续改善 `NONE` 与 `LOW_FUEL` 的分界
    - 按 `top-k 候选 + 仲裁` 方式接入，而不是直接 top-1 直出
- `strategy_arbiter_v2` 代码骨架已落地
  - 当前文件：
    - `/Users/sn5/Asurada/asurada-core/src/asurada/arbiter.py`
  - 当前结论：
    - 输入/输出契约已代码化
    - 最小仲裁逻辑已可运行
    - 当前已以 sidecar 形式接入 `StrategyEngine.evaluate()` 的 debug 输出
    - 当前已真实消费 `strategy_action_model` 的 `top-k` 候选
    - 当前已接管 `StrategyEngine` 最终 `messages` 排序
    - 当前已完成 priority 校准，避免模型分数直接映射导致播报阈值失真
  - 当前能力：
    - 接收 `rule_candidates`
    - 接收 `model_candidates`
    - 结合 `tactical_context`
    - 结合 `confidence_context`
    - 结合 `fallback_context`
    - 输出 HUD / voice / stack / suppressed actions
    - 已接入自动回归断言：
      - `priority_floor_calibrated`
      - `cooldown_suppresses_last_action`
      - `duplicate_codes_deduped`
  - 下一步收口方向：
    - 继续补更细的 priority / cooldown 标定

### 阶段三：产品化与平台化

目标：

- 迁移到可部署、可交付、可扩展的产品平台

当前状态：

- `未开始`

当前完成度：

- `0%`

## 阶段一详细状态

---

## 1. 项目基础环境

状态：`已完成`  
完成度：`100%`

已完成：

- [x] 建立独立虚拟环境
- [x] 建立可编辑安装方式
- [x] 规范 `asurada-core` 目录结构
- [x] 建立 README / 架构 / 验收 / 状态文档基础体系

相关文件：

- [pyproject.toml](pyproject.toml)
- [README.md](README.md)

未完成：

- [ ] 无阶段一阻塞项

优化空间：

- [ ] 增加开发脚本集合
- [ ] 增加统一命令入口

---

## 2. 输入路径

状态：`部分完成`  
完成度：`85%`

已完成：

- [x] 标准化 replay 输入
- [x] 单圈 CSV 输入
- [x] 抓包 JSONL 回放输入
- [x] live UDP 监听壳

相关文件：

- [ingest.py](src/asurada/ingest.py)
- [csv_ingest.py](src/asurada/csv_ingest.py)
- [capture_ingest.py](src/asurada/capture_ingest.py)
- [udp_ingest.py](src/asurada/udp_ingest.py)

未完成：

- [ ] live UDP 完整主链接入
- [ ] live 与 capture replay 完全共路径

优化空间：

- [ ] 增加统一输入源抽象层状态监控
- [ ] 增加实时输入异常统计

---

## 3. 真实包解析

状态：`大体完成`  
完成度：`94%`

已完成：

- [x] `Session`
- [x] `LapData`
- [x] `Participants`
- [x] `CarSetups`
- [x] `CarTelemetry`
- [x] `CarStatus`
- [x] `FinalClassification`
- [x] `CarDamage`
- [x] `SessionHistory`
- [x] `TyreSets`
- [x] `Motion`
- [x] `MotionEx`
- [x] `Event`
- [x] `TimeTrial`
- [x] `LapPositions` 正式命名与正文解析

相关文件：

- [pdu_decoder.py](src/asurada/pdu_decoder.py)
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)

未完成：

- [x] `packet 15` 正式命名为 `LapPositions`
- [x] `LobbyInfo` 正文解析
  - 后续项：真实联机样本验证
  - 不阻塞阶段一封板
- [x] 标准 `Event` union detail 结构化
- [ ] 基于剩余未知 session code 与 `session_type 8` 的 timing 最终验证

优化空间：

- [ ] 为每类 packet 增加更系统的样本断言
- [ ] 对单位、偏移、取值范围做协议注释化
- [ ] 继续补充更多赛周样本的 session type 对照表

本轮新增进展：

- [x] `LapData` delta 字段已接入标准化秒级字段
- [x] player / rival gap 已改为 `LapData delta 优先，估算回退`
- [x] gap 来源已写入 `raw` 与 debug 链路
- [x] timing mode / support level / confidence tier 已写入 `raw` 与 debug 链路
- [x] 当前抓包里的 race-like `session_type 15 / 16` 已完成 timing 样本验证
- [x] 当前抓包里的 qualifying-like `session_type 13` 已完成 timing 样本验证
- [x] `Session` 固定尾部设置字段已从 trailer 拆成正式命名结构
- [x] `session_type 8 / 13 / 15 / 16` 已建立项目内稳定归类
- [x] 比赛后半段样本已按 `session_uid` 切分为阶段二可复用数据集

---

## 4. 组帧与标准化快照

状态：`离线链已完成`  
完成度：`92%`

已完成：

- [x] 按 `session_uid + frame_identifier` 组帧
- [x] 跨帧缓存 `Session / Participants / Event / Setup / History`
- [x] 标准化 snapshot 输出
- [x] `raw` 高价值特征展开
- [x] 多车 rival 基础状态接入

相关文件：

- [packet_snapshot.py](src/asurada/packet_snapshot.py)
- [decode.py](src/asurada/decode.py)
- [models.py](src/asurada/models.py)

未完成：

- [ ] live UDP 共享同一套完整组帧主链

优化空间：

- [ ] 增加组帧失败原因统计
- [ ] 增加跨帧缺包诊断输出

---

## 5. 统一状态仓

状态：`已完成`  
完成度：`100%`

已完成：

- [x] `SessionState` 结构稳定化
- [x] 最新状态缓存
- [x] 短窗口历史缓存
- [x] 提供策略层上下文窗口

相关文件：

- [state.py](src/asurada/state.py)

未完成：

- [ ] 无阶段一阻塞项

优化空间：

- [ ] 增加窗口统计工具方法
- [ ] 增加状态仓调试快照导出

---

## 6. 赛道语义模型

状态：`上海站已完成`  
完成度：`95%`

已完成：

- [x] 上海站分段模型
- [x] 细化区段语义
- [x] usage 标签
- [x] usage hooks 配置化
- [x] 区段顺序接入 dashboard

相关文件：

- [track_model.py](src/asurada/track_model.py)
- [shanghai_segments.json](data/tracks/shanghai_segments.json)
- [usage_hooks.json](data/strategy/usage_hooks.json)

未完成：

- [ ] 多赛道语义库

优化空间：

- [ ] 不同赛道共享 usage 语义规范
- [ ] 区段级特征模板复用

---

## 7. 策略引擎

状态：`阶段一范围内完成`  
完成度：`93%`

已完成：

- [x] 分层策略管线
- [x] `StateAssessment`
- [x] 上下文风险评分
- [x] 候选策略生成
- [x] 仲裁输出
- [x] usage hook 配置化
- [x] `risk_explain`
- [x] `usage_bias`

相关文件：

- [strategy.py](src/asurada/strategy.py)
- [config.py](src/asurada/config.py)

未完成：

- [ ] 进站收益模拟
- [ ] undercut / overcut 推理
- [ ] 更完整对手策略推断
- [ ] 实时操作员控制层

优化空间：

- [ ] 风险评分参数再抽象成版本化配置
- [ ] 候选策略冲突解释再细化
- [ ] 不同赛道 usage bias 自动加载

---

## 8. 驾驶动态分析

状态：`原型完成`  
完成度：`80%`

已完成：

- [x] 动态标签
- [x] unstable / front overload 判断
- [x] 单圈 phase summary
- [x] driver style summary
- [x] 赛道区段复盘摘要

相关文件：

- [analysis.py](src/asurada/analysis.py)
- [output.py](src/asurada/output.py)

未完成：

- [ ] braking quality score
- [ ] rotation quality score
- [ ] traction quality score
- [ ] 长会话驾驶画像

优化空间：

- [ ] 区段级评分统一口径
- [ ] 动态标签置信度输出

---

## 9. 日志、回放、报告

状态：`已完成`  
完成度：`96%`

已完成：

- [x] `session_log.jsonl`
- [x] `capture_summary.json`
- [x] lap report JSON
- [x] dashboard 基于日志重建
- [x] 固定样本自动回归脚本
- [x] 分 session 语义断言回归矩阵

相关文件：

- [replay.py](src/asurada/replay.py)
- [reports.py](src/asurada/reports.py)
- [runtime_logs/session_log.jsonl](runtime_logs/session_log.jsonl)
- [runtime_logs/capture_summary.json](runtime_logs/capture_summary.json)

优化空间：

- [ ] 回放结果自动比对
- [ ] 日志版本标记
- [ ] 结构化数据导出模板

---

## 10. 调试面板 / HUD 原型

状态：`阶段一工程原型完成`  
完成度：`94%`

已完成：

- [x] 最新状态展示
- [x] 趋势图
- [x] 帧浏览器
- [x] 区段热力图
- [x] rival 概览
- [x] 协议覆盖概览
- [x] 解析到策略链路展示
- [x] packet 级过滤
- [x] trigger highlights
- [x] frame diff
- [x] field source + field trace
- [x] 双时间轴展示
- [x] 页面中文说明
- [x] 中断日志容错

相关文件：

- [dashboard.py](src/asurada/dashboard.py)
- [debug_dashboard.html](runtime_logs/dashboard/debug_dashboard.html)

未完成：

- [ ] 可交互赛道地图叠加
- [ ] 更强图表交互
- [ ] 真正的前端应用化

优化空间：

- [ ] 风险因子可折叠视图
- [ ] 字段差异高亮着色
- [ ] dashboard 快照校验脚本

---

## 11. 文档与维护说明

状态：`已完成`  
完成度：`95%`

已完成：

- [x] README
- [x] 架构文档
- [x] 阶段一验收文档
- [x] 阶段一封板文档
- [x] 字段覆盖文档
- [x] 未完成字段文档
- [x] 阶段二模型 schema 文档
- [x] 状态总看板
- [x] 注释与 docstring 统一

相关文件：

- [README.md](README.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [PHASE1_ACCEPTANCE.md](PHASE1_ACCEPTANCE.md)
- [PHASE1_CLOSEOUT.md](PHASE1_CLOSEOUT.md)
- [PACKET_FIELD_COVERAGE.md](PACKET_FIELD_COVERAGE.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](STAGE2_MODEL_INPUT_SCHEMA.md)
- [STATUS.md](STATUS.md)

未完成：

- [ ] 一页式路线图图示

优化空间：

- [ ] 文档版本号和更新时间
- [ ] 阶段二任务拆分文档

## 阶段一未完成总表

这部分是阶段一真正剩余的收口项。

### 核心未完成项

- [ ] `live UDP` 完整实时闭环
- [ ] `live` 与 `capture replay` 完全共路径

### 协议精修项

- [ ] `LapData` 前车 / 领跑 delta 语义最终校准
- [ ] rival gap 官方时差口径
- [x] `LapPositions` 命名
- [x] `LobbyInfo` 正文解析
  - 后续项：真实联机样本验证
  - 当前已移出阶段一必收口范围
- [x] `Session` trailer 未命名字段拆解
- [ ] 稀有 `Event` detail 样本验证补齐

## 阶段二当前状态

状态：`已启动`

当前完成：

- [x] 阶段二模型输入 schema
- [x] 字段覆盖文档
- [x] 未完成字段清单
- [x] `raw` 高价值字段已暴露
- [x] 策略解释字段已进入日志和 dashboard

当前未完成：

- [ ] 固定数据集导出流程
- [ ] 模型任务定义
- [ ] 标签体系定义
- [ ] 特征版本管理
- [ ] 回归验证体系进一步扩展
- [ ] 多赛道泛化语义库

## 阶段三当前状态

状态：`未开始`

待启动项：

- [ ] CM5 迁移
- [ ] 存储可靠性
- [ ] 散热 / 电源设计
- [ ] 冗余策略
- [ ] 远程控制层
- [ ] 产品级交互
- [ ] 机械副驾机头硬件整合

## 当前最值得继续做的事

### 如果目标是把阶段一彻底收口

1. [ ] 完成 `live UDP` 全闭环
2. [ ] 打通 `live` 与 `capture replay` 共路径
3. [ ] 收掉协议精修项

### 如果目标是推进阶段二模型工作

1. [x] 定义首批模型任务和目标
2. [x] 建立阶段二训练目录与数据集配置
3. [x] 从分 session 样本导出第一版稳定训练视图
4. [x] 锁定特征版本 `v1` 的首轮导出骨架
5. [x] 建立第一版伪标签导出骨架
6. [x] 建立固定抓包回归检查
7. [x] 收紧 `tactical_features_v1` 攻防专题特征表
8. [x] 建立 `rear_threat_model` baseline 训练入口
9. [x] 在 `.venv` 安装训练依赖并跑通第一版 baseline
10. [x] 收紧 `rear_threat_binary_label` 与专题样本过滤，消除首轮 baseline 的单边预测退化
11. [x] 为 `rear_threat_model` 增加验证集阈值扫描，得到第一版可用平衡阈值
12. [x] 建立 `event_features_v1` 导出与 `event_impact_model` baseline 训练入口
13. [x] 试跑 `event_impact_model` baseline，确认当前样本与标签不足以支持稳定模型
14. [ ] 暂停 `event_impact_model`，等待更完整的事件样本或更强后验标签
15. [x] 建立 `attack_features_v1` 导出与 `front_attack_commit_model` baseline 训练入口
16. [x] 得到 `front_attack_commit_model` 第一版可用 baseline
17. [x] 建立 `attack_opportunity_model` baseline 训练入口并得到第一版可用 baseline
18. [x] 为 `attack_opportunity_model / front_attack_commit_model` 补跨 session 外部 test 样本
19. [x] 为攻击链补独立 `val` 样本，降低对 `train_holdout_split` 的依赖
20. [x] 收紧 `attack_commit_proxy_label`，将 `front_attack_commit_model` 外部 test 误报从 `79` 压到 `4`
21. [ ] 继续增强 `attack_commit_proxy_label` 的 DRS 和持续逼近信号，进一步提高泛化稳定性
22. [x] 建立 `strategy_action_model` 第一版干净 baseline（高频动作子集）
23. [x] 为 `strategy_action_model` 补独立 exported `val`，降低对 `train_holdout_split` 的依赖
24. [x] 设计并实现 `strategy_arbiter_v2` 输入/输出契约与最小代码骨架
25. [x] 将 `strategy_arbiter_v2` 以 sidecar 方式接入现有 `StrategyEngine` debug
26. [x] 将 `strategy_arbiter_v2` 接入真实 `strategy_action_model top-k` 候选
27. [x] 将 `strategy_arbiter_v2` 的仲裁结果接入最终动作主链
28. [x] 为模型驱动动作增加 priority 校准，避免低于现有播报阈值
29. [x] 增加仲裁层 priority / cooldown 回归断言
12. [x] 试跑 `yield_vs_defend_model` baseline，确认链路可行
13. [ ] 暂停 `yield_vs_defend_model`，等待更稳定的后验标签与样本覆盖后再重启

### 如果目标是提高工程质量

1. [x] 增加自动回归测试
2. [x] 增加 parser 样本断言
3. [x] 增加 dashboard 健康检查
4. [ ] 增加协议完成度跟踪表

## 当前一句话判断

Asurada Core 已经完成了“离线真实抓包策略脑”的核心建设，阶段一剩余工作主要集中在实时闭环和协议精修；阶段二已经具备开始模型化工作的基础。

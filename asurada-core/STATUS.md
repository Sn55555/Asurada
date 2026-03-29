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
- 阶段二准备工作进度：`65%`
- 阶段三产品化进度：`0%`

当前结论：

- 离线真实抓包策略主链已经打通
- 调试面板已经具备工程级检查能力
- 阶段二已从“数据准备”推进到“baseline + 控制层 + runtime sidecar + 扩展样本接入”并行阶段
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

- `65%`

当前已启动工作：

- 真实包高价值字段覆盖
- 未完成字段清单
- 模型输入 schema
- debug 链路解释能力
- 赛周分会话样本切分与命名归类
- 阶段二训练目录与数据集配置
- 第一版 `features / labels / tactical_features_v1` 导出
- 第一版资源风险 baseline：
  - `fuel_risk_model`
  - `ers_risk_model`
  - `tyre_risk_model`
  - `dynamics_risk_model`
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
- `fuel_risk_model / ers_risk_model / tyre_risk_model / dynamics_risk_model` baseline 已跑通
  - 当前训练口径：
    - 使用 `features.csv + labels.csv`
    - 仅保留 `timing_support_level = official_preferred`
    - `train = exported train`
    - `val = train_holdout_split`
    - `test = exported_test_split (uid16)`
  - `fuel_risk_model`
    - 当前结论：已按新燃油边际口径重训，第一版 baseline 可用
    - 当前指标：`mae=20.7958`、`rmse=39.2586`、`r2=0.0000`
    - 当前收口：
      - 已把 `derived_fuel_laps_remaining / fuel_margin_laps / fuel_laps_remaining_source` 纳入训练表
      - 已去掉 `derived fuel` 可用时由 `tank_ratio <= 0.08` 直接触发 `critical` 的旧口径
      - 当前 `uid16` exported test 标签范围已收敛到 `20.0 ~ 20.0`
  - `ers_risk_model`
    - 当前结论：第一版 baseline 可用
    - 当前指标：`mae=0.2329`、`rmse=1.3906`、`r2=0.9609`
  - `tyre_risk_model`
    - 当前结论：第一版 baseline 可用
    - 当前指标：`mae=0.0305`、`rmse=0.0699`、`r2=0.9998`
  - `dynamics_risk_model`
    - 当前结论：第一版 baseline 可用
    - 当前指标：`mae=0.1149`、`rmse=1.2109`、`r2=0.9541`
  - 当前意义：
    - 阶段二基础资源模型组已从“计划项”进入“可训练、可评估、可继续接主链”的状态
    - `attack_opportunity / front_attack_commit / strategy_action` 这条线已有正式上游资源特征模型
  - 下一步收口方向：
    - 为资源模型补 exported `val` 口径，降低对 `train_holdout_split` 的依赖
    - 开始决定哪些资源模型先旁路接入 runtime debug
- `entry_quality_model / apex_quality_model / exit_traction_model` baseline 已跑通并旁路接入 runtime debug
  - 当前结论：三条链都已证明可训练、可回放观察
  - 当前指标：
    - `entry_quality_model`：`mae=0.3427`、`rmse=0.6511`、`r2=0.9961`
    - `apex_quality_model`：`mae=0.3826`、`rmse=0.5764`、`r2=0.9892`
    - `exit_traction_model`：`mae=0.4541`、`rmse=0.6593`、`r2=0.9968`
  - 当前边界：
    - 当前仍是 `proxy_distillation_from_features` baseline
    - 更适合作为趋势/运行时观察分数，不是最终精细驾驶评分
- `counterattack_window_model` 已完成训练入口与可训练性检查
  - 当前结论：阻塞，暂不能继续训练
  - 当前阻塞原因：
    - `counterattack_candidate_label` 正类样本极少
    - 当前 split 分布：
      - `train=2025`，正类 `1`
      - `val=1012`，正类 `1`
      - `test=4970`，正类 `0`
    - 在此分布下继续训练只会得到假模型，不应接 runtime 或主链
  - 当前意义：
    - 训练入口已补齐
    - 阻塞条件已固化为可复现报告
  - 下一步收口方向：
    - 设计 `counterattack` 专题样本集
    - 评估 `player + rear_rival` 双视角 counterattack 导出
    - 扩大 `position_lost -> drs_recovery -> regain_position` 的 lookahead 窗口
- `tyre_degradation_trend_model` baseline 已跑通
  - 当前结论：第一版趋势基线成立
  - 当前训练口径：
    - 使用 `features.csv`
    - 仅保留 `official_preferred + race-like` 样本
    - 未来窗口：`15.0s`
    - split：
      - `uid15 lap 1/3 -> train`
      - `uid15 lap 2 -> val`
      - `uid16 -> test`
  - 当前指标：
    - `future_tyre_wear_delta`：`mae=0.1159`、`rmse=0.1806`、`r2=0.6131`
    - `future_grip_drop_score`：`mae=0.8203`、`rmse=1.2437`、`r2=0.5770`
  - 当前边界：
    - 当前仍是基于未来窗口后验标签的 `LightGBM baseline`
    - 已旁路接入 runtime debug
    - 当前不进入主链，只作为趋势观察分数
- `short_horizon_risk_forecast_model` 已完成 baseline 试跑
  - 当前结论：暂不推进
  - 当前训练口径：
    - 使用 `features.csv + labels.csv`
    - 仅保留 `official_preferred + race-like` 样本
    - 目标：
      - `risk_forecast_3s`
      - `risk_forecast_next_zone`
  - 当前指标：
    - `risk_forecast_3s`：`mae=25.14`、`rmse=26.94`、`r2=-3.16`
    - `risk_forecast_next_zone`：`mae=16.21`、`rmse=17.16`、`r2=-0.81`
  - 当前阻塞原因：
    - 目标定义过粗，容易被未来极端帧支配
    - 当前快照特征不足以支撑未来 3 秒风险演化预测
    - 现阶段继续训练不会得到可信模型
  - 下一步收口方向：
    - 后续若重启，需要先重做时序标签定义
    - 需要显式短窗序列特征，再决定是否上 `LSTM / Temporal CNN`
- `driver_style_model` 已完成 baseline 试跑
  - 当前结论：暂不推进
  - 当前训练口径：
    - 使用 `features.csv`
    - 仅保留 `official_preferred + race-like` 样本
    - 按 `20s` 长窗口聚合成长时段风格样本
    - 代理输出：
      - `aggression_score`
      - `consistency_score`
      - `driver_style_tag`
  - 当前指标：
    - `aggression_score`：`mae=2.3228`、`rmse=3.2112`、`r2=-0.7460`
    - `consistency_score`：`mae=3.8883`、`rmse=4.6502`、`r2=-0.3926`
    - `driver_style_tag`：当前 test 基本塌成单类，分类结果不可信
  - 当前阻塞原因：
    - 长窗口样本仅 `42` 条
    - `val/test` 分布过小且类别塌缩
    - 当前继续训练不会得到可信风格模型
  - 下一步收口方向：
    - 后续若重启，需要更多长赛程窗口样本
    - 需要重新设计风格标签，而不是只靠代理分数
- `pit_rejoin_traffic_model` 已完成可训练性检查
  - 当前结论：阻塞，暂不能训练
  - 当前阻塞原因：
    - `pit_status` 与进站状态转移字段已导出
    - 当前 `pit_exit + rejoin_window` 候选样本仅 `11` 条，且全部在 `train`
    - 当前交通分布只有 `light`，没有足够的回场车流带宽变化
  - 当前意义：
    - 阻塞条件已固化为可复现报告
    - 这条线当前问题已从“缺字段”推进到“样本仍稀缺”
  - 下一步收口方向：
    - 继续扩 `rejoin_window` 样本
    - 补更多进站/回场样本和交通带宽变化
    - 再设计 `pit_rejoin` 样本与标签
- 扩展样本集已接入阶段二训练链
  - 当前新增样本：
    - `suzuka_sprint_race_like_uid15`
    - `shanghai_feature_race_like_uid16_20lap`
  - 当前新增基础设施：
    - `track_id 13 -> Suzuka` 赛道映射已补齐
    - `phase2_metadata_combined.json` 已建立
    - `phase2_dataset_v2_extended.json` 已建立
  - 当前结论：
    - 新样本已拆分为单 session `.jsonl`
    - smoke export 已通过
    - 已可进入现有阶段二训练链
- `strategy_action_model` 扩展数据集 split 已修复
  - 当前结论：exported `val` 已稳定包含 `DEFEND_WINDOW`
  - 当前处理：
    - 保留 `uid13 lap1 -> val`
    - 保留 race-like 固定 `val`
    - 对 `SprintRaceLike lap1` 的 `DEFEND_WINDOW` 做 deterministic 抽样进入 `val`
  - 当前意义：
    - 扩展数据集下 `strategy_action_model` 不再因 `val` 缺类而阻塞
- `attack_opportunity_model` 扩展数据集口径已收口
  - 当前问题已修：
    - 新样本接入后 exported `val` 缺失，训练回退到 holdout
    - 伪标签过宽导致 test 误报显著增多
  - 当前处理：
    - 已为攻击链补 deterministic exported `val`
    - 已收紧 `attack_opportunity` 伪标签
    - 已把阈值选择改成偏高 precision 的保守策略
  - 当前最新结果（扩展数据集受控导出）：
    - `accuracy=0.9994`
    - `positive precision=0.9444`
    - `positive recall=1.0000`
    - `FP=1`
- `defence_cost_model` baseline 已跑通
  - 当前结论：第一版 proxy-distillation baseline 可用
  - 当前训练口径：
    - 使用 `features.csv + labels.csv`
    - 过滤 `official_preferred + race-like tactical rows`
    - deterministic split：
      - `uid15` 第 1/3 圈 -> `train`
      - `uid15` 第 2 圈 -> `val`
      - `uid16` -> `test`
  - 当前指标：
    - `mae=2.7160`
    - `rmse=4.4729`
    - `r2=0.3031`
    - `tactical_cost_correlation=0.7154`
  - 当前边界：
    - 当前目标仍是从现有字段重算的 `defence_cost_proxy`
    - 不是后验损失标签模型
  - 当前意义：
    - `yield_vs_defend_model` 现在有了正式上游代价分数，不必继续直接依赖手工 proxy
    - 已旁路接入 runtime debug，可在真实回放里查看 `defence_cost_model` 分数
  - 下一步收口方向：
    - 决定是否把 `defence_cost_model` 纳入 `yield_vs_defend` 重启前的正式上游
    - 若需要更强可信度，再重做后验损失标签
- `rival_pressure_model` baseline 已跑通
  - 当前结论：第一版 baseline 链路已成立，并已旁路接入 runtime debug
  - 当前训练口径：
    - 使用 `features.csv + labels.csv`
    - 过滤 `official_preferred + race-like rows`
    - deterministic split：
      - `uid15` 第 1/3 圈 -> `train`
      - `uid15` 第 2 圈 -> `val`
      - `uid16` -> `test`
  - 当前输出：
    - `front_pressure_model`
    - `rear_pressure_model`
    - `rival_pressure_model`
  - 当前指标：
    - `front_pressure_model`
      - `mae=11.9885`
      - `rmse=12.4644`
      - `r2=0.0000`
      - `threat_ranking_accuracy=0.0000`
      - 当前结论：race-like 外部样本不足，尚不可单独视为可用模型
    - `rear_pressure_model`
      - `mae=4.0431`
      - `rmse=5.0826`
      - `r2=0.9839`
      - `threat_ranking_accuracy=0.9484`
      - 当前结论：当前最稳，可作为旁路压力分数
    - `rival_pressure_model`
      - `mae=25.4790`
      - `rmse=29.5207`
      - `r2=0.4563`
      - `threat_ranking_accuracy=0.8439`
      - 当前结论：可用于 debug 观察综合态势，但还不适合直接接主链仲裁
  - 当前意义：
    - 攻防态势层开始具备连续压力分数，不再只剩单点 `rear_threat` 和 `attack_opportunity`
    - runtime debug 已能同时看到资源模型、`defence_cost_model` 和 `rival_pressure_model`
  - 下一步收口方向：
    - 先补更多前车压迫样本，再决定是否继续强化 `front_pressure_model`
    - `rival_pressure_model` 先维持 sidecar，不直接喂入最终动作主链
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
- 统一交互输入事件模型最小版已接入
  - 当前结论：阶段三防返工接口主线已开始落地
  - 当前实现：
    - 新增统一 `interaction_input_event` envelope
    - 已包含：
      - `interaction_session_id`
      - `turn_id`
      - `request_id`
      - `input_type`
      - `intent_type`
      - `snapshot_binding_id`
      - `snapshot_binding`
    - 当前在 `StrategyEngine.evaluate()` 中为每帧生成系统策略事件
    - 当前已写入 `decision.debug` 和 `session_log.jsonl`
  - 当前边界：
    - 当前只覆盖 `system_strategy -> strategy_broadcast`
    - 尚未正式接入 ASR / TTS / query normalization
    - 尚未实现输出层可取消 / 可中断生命周期
    - 尚未实现语音分层日志骨架
  - 当前意义：
    - 阶段三接入双向语音时，不需要再回改主链的轮次标识和快照绑定协议
    - 输出层、logger、debug dashboard 都可以复用同一事件结构
- 输出层可取消 / 可中断生命周期最小版已接入
  - 当前结论：输出层生命周期接口已定型到可复用状态
  - 当前实现：
    - `ConsoleVoiceOutput` 当前已维护 `active output`
    - 已支持事件类型：
      - `start`
      - `interrupt`
      - `suppress`
      - `cancel`
      - `idle`
    - 当前事件已写入 `decision.debug["output_lifecycle"]`
    - 当前日志里已能看到：
      - `output_session_id`
      - `output_event_id`
      - `event_type`
      - `interrupted_output_event_id`
      - `turn_id / request_id / snapshot_binding_id`
  - 当前边界：
    - 当前只覆盖 console voice 输出层
    - 尚未接入真实 TTS / 音频缓冲 / 播放器状态
    - 尚未实现正式的可抢占音频通道
  - 当前意义：
    - 阶段三接 TTS 时，不需要再回改主链的输出事件语义
    - 当前已经能用同一生命周期协议描述“开始播报 / 被打断 / 被压制 / 被取消”
- `ASR -> query normalization -> strategy -> TTS` 分层日志骨架最小版已接入
  - 当前结论：分层日志结构已定型到可复用状态
  - 当前实现：
    - 当前 `decision.debug["voice_pipeline_log"]` 已包含四层：
      - `asr`
      - `query_normalization`
      - `strategy`
      - `tts`
    - 当前系统策略场景下：
      - `asr.stage_status = not_applicable`
      - `query_normalization` 已生成标准化 query/intention 记录
      - `strategy` 已记录主动作、候选数、置信度、fallback 口径
      - `tts` 已从 `output_lifecycle` 自动派生
    - 当前日志已写入 `decision.debug` 和 `session_log.jsonl`
  - 当前边界：
    - 仍是最小骨架，不含真实 ASR transcript / TTS player 状态
    - 尚未接入结构化 query schema 与工具调用层
  - 当前意义：
    - 阶段三接入 ASR/TTS 时，不需要回改日志主结构
    - 当前已可以按同一格式对齐系统策略播报和未来语音问答链路
- 结构化语音查询 schema 与指令路由接口最小版已接入
  - 当前结论：结构化 query 层已从文档占位进入代码骨架
  - 当前实现：
    - 已新增 `structured_query`
    - 已新增 `query_route`
    - 当前系统策略场景下会生成：
      - `schema_version`
      - `query_kind`
      - `target_scope`
      - `requested_fields`
      - `response_mode`
      - `handler`
      - `response_channel`
    - 当前已写入 `decision.debug` 和 `voice_pipeline_log`
  - 当前边界：
    - 仍是最小规则版，只覆盖 `system_strategy -> strategy_broadcast`
    - 尚未接入真实语音问答意图分类
    - 尚未接入工具调用层
  - 当前意义：
    - 阶段三接结构化问答时，不需要再回改 query schema 主结构
    - 当前已把“输入事件 -> 结构化 query -> 路由 -> 策略输出”这条接口链打通
- 语音确认 / 权限分级规则最小版已接入
  - 当前结论：确认与权限策略已从文档占位进入代码骨架
  - 当前实现：
    - 已新增 `confirmation_policy`
    - 当前会输出：
      - `policy_version`
      - `decision`
      - `risk_level`
      - `requires_confirmation`
      - `permission_scope`
      - `reason`
    - 当前系统策略播报默认走：
      - `decision = auto_approve`
      - `permission_scope = broadcast`
    - 已对高风险动作码预留：
      - `confirm_before_execute`
  - 当前边界：
    - 仍是最小规则版，只覆盖结构化 query 层
    - 尚未接入真实语音问答权限、用户确认回合与工具执行确认
  - 当前意义：
    - 阶段三接入真实语音交互时，不需要回改确认策略主结构
    - 当前已经能在同一日志链里描述“是否需要确认、为什么需要确认”
- 工具与长任务取消接口最小版已接入
  - 当前结论：长任务取消协议已从文档占位进入代码骨架
  - 当前实现：
    - 已新增 `task_handle`
    - 已新增 `task_lifecycle`
    - 当前会输出：
      - `task_id`
      - `task_type`
      - `handler`
      - `status`
      - `cancel_reason`
      - `cancelled_by_request_id`
    - 输出层当前会维护：
      - `active_task`
      - `cancelled_task`
      - 当前任务生命周期事件
  - 当前边界：
    - 仍是逻辑取消接口，不会真实中断外部进程或工具执行
    - 还没有接入真实工具调用层
  - 当前意义：
    - 阶段三接入慢查询、工具调用、语音插话时，不需要回改取消协议主结构
    - 当前已能统一描述“旧任务被新请求取消”的语义
- `confidence_model / uncertainty_layer` 最小规则版已接入
  - 当前文件：
    - `/Users/sn5/Asurada/asurada-core/src/asurada/confidence.py`
  - 当前结论：
    - 已不再写死 `confidence_context=high`
    - 当前会根据 `timing_support_level`、官方 gap 可信度、模型候选可用性、当前战术态，生成真实 `confidence_context / fallback_context`
    - 已接入 `StrategyEngine` 到 `strategy_arbiter_v2` 的主链
    - 已接入自动回归断言：
      - `low_confidence_falls_back_to_rules`
  - 当前边界：
    - 仍是规则校准层，不是训练出来的轻量分类器
    - 当前仍未引入特征缺失率和 OOD 信号
  - 下一步收口方向：
    - 补特征缺失率和 OOD 信号
    - 细化 `voice_allowed / hud_only` 口径
- `session_mode_router` 最小规则版已接入
  - 当前文件：
    - `/Users/sn5/Asurada/asurada-core/src/asurada/session_router.py`
  - 当前结论：
    - 已从 `StrategyEngine` 主链生效，不再只是文档占位
    - 当前会按 `session_type + timing_mode + timing_support_level` 生成真实 `session_route`
    - 当前同时过滤：
      - 规则候选 `rule_candidates`
      - 模型候选 `model_candidates`
    - 当前路由策略：
      - `race_like + official_preferred`
        - 允许 race 资源动作和 timing 动作
      - `session_type_estimated`
        - 禁用 timing 动作，保留非 timing 资源与动态动作
      - `QualifyingLike / Time Trial / 非 race-like`
        - 仅保留 `NONE / DYNAMICS_UNSTABLE / FRONT_LOAD`
    - 当前已接入自动回归断言：
      - `session_route_present`
      - `time_trial_route_filters_race_actions`
  - 当前边界：
    - 仍是最小规则版，还没有细化到按 `Qualifying / Sprint / Feature Race` 拆出更深的动作优先级与参数模板
    - 当前只完成了和 `fallback_policy` 的最小联动
  - 下一步收口方向：
    - 细化 `QualifyingLike / SprintRaceLike / FeatureRaceLike` 的动作空间和优先级
    - 为 `strategy_action_model / arbiter_v2` 增加 session-specific priority profile
    - 与 `uncertainty layer / fallback_policy` 进一步联动
- `fallback_policy` 最小独立模块已接入
  - 当前文件：
    - `/Users/sn5/Asurada/asurada-core/src/asurada/fallback.py`
  - 当前结论：
    - 已从 `uncertainty layer` 之后、`strategy_arbiter_v2` 之前生效
    - 当前会根据 `session_route + confidence_resolution + tactical_state` 生成真实 `fallback_context / output_control`
    - 当前已能覆盖：
      - timing 动作在非 timing session 下回退 `rule_only`
      - 低置信度战术态回退 `rule_only`
      - 高不稳定战术态降级为 `hud_only`
      - 战术锁定时提高 `cooldown_hint`
  - 当前边界：
    - 仍是最小规则版
    - 还没有接真实输出历史和多轮任务状态
  - 下一步收口方向：
    - 接入真实 `last_emitted_action`
    - 细化 `suppression_window`
    - 与输出层生命周期和任务取消接口联动
- `tactical_state_machine` 最小规则版已接入
  - 当前文件：
    - `/Users/sn5/Asurada/asurada-core/src/asurada/state_machine.py`
  - 当前结论：
    - 已从 `StrategyEngine` 主链生效，不再是写死的战术态分支
    - 当前会根据前一帧位置变化、当前攻防窗口和短窗上下文生成真实：
      - `previous_tactical_state`
      - `tactical_state`
      - `state_transition`
      - `state_priority_hint`
      - `state_lock`
    - 当前结果已写入 `decision.debug["arbiter_v2"]["input"]["tactical_state_machine"]`
    - 当前已接入真实输出历史：
      - 按 `session_uid` 记住上一帧战术态
      - 按 `session_uid` 记住上一条主动作
      - 在 gap 仍处于宽松阈值内时保持 `DEFEND_WINDOW / ATTACK_WINDOW` 对应战术态，降低抖动
  - 当前边界：
    - 仍是最小规则版
    - 还没有接入 `yield_vs_defend_model / counterattack_window_model / event_impact_model` 的正式输出
  - 下一步收口方向：
    - 细化 `counterattack_active` 与 `attack_prepare` 的切换条件
    - 后续与 `yield_vs_defend_model / counterattack_window_model` 正式联动

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
- [ ] `counterattack` 专题样本集与导出策略
- [x] 面向阶段三的统一交互输入事件模型
- [x] 面向阶段三的 `turn_id / interaction_session_id` 会话轮次结构
- [x] 策略查询输入与状态快照绑定协议
- [x] 可取消 / 可中断的异步执行与输出控制（最小版）
- [x] 语音接入前的确认 / 权限分级规则（最小版）
- [x] `ASR -> query normalization -> strategy -> TTS` 分层日志骨架（最小版）
- [x] 结构化语音查询 schema 与指令路由接口（最小版）

### 阶段二补充计划：阶段三防返工接口预埋

这部分仍然归属阶段二，不等到阶段三再补。

目标：

- 让语音、文本、按钮、外部事件都能复用同一条策略入口
- 避免阶段三为了双向语音接入而重写策略主链
- 先把接口和状态机边界做对，再决定具体语音模型和部署形式

当前必须补的预埋项：

- [x] 定义统一 `InteractionInput / UserTurn` 结构，输入源不再默认等于文本
- [x] 为交互链路补 `turn_id`、`interaction_session_id`、`request_id` 三层标识
- [x] 为策略查询定义快照协议，保证“用户问到的状态”和“模型回答所依据的状态”一致
- [x] 为输出层补 `pending / committed / cancelled / interrupted` 生命周期
- [x] 为工具与长任务补取消接口（最小版），避免语音插话时旧动作继续执行
- [x] 为语音场景补确认门槛（最小版）：
  - 高风险动作必须二次确认
  - 低风险结构化查询可直接回答
- [ ] 为日志补语音接入所需分层：
- [x] 为日志补语音接入所需分层：
  - 原始输入
  - 归一化 query
  - 策略决策
  - 工具调用
  - 最终播报
- [x] 为结构化语音问答预留独立 query schema，而不是让语音文本直接进入策略层

### `counterattack` 专题样本设计

当前 `counterattack_window_model` 的主要阻塞项不是训练脚本，而是样本设计。

最小可行方案：

- 事件起点：
  - `position_lost_recently = 1`
- 正类后验条件：
  - 未来 `5.0 ~ 8.0s` 内满足至少一项：
    - `position_gain_recently = 1`
    - `drs_recovery_window = 1`
    - `official_gap_ahead_s` 缩小到攻击阈值
- split 最低目标：
  - `train >= 12` 个正类
  - `val >= 4` 个正类
  - `test >= 4` 个正类
- 设计优先级：
  1. 扩大 `lookahead_s`
  2. 评估 `player + rear_rival` 双视角 counterattack 导出
  3. 再决定是否扩到更长赛程样本

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
30. [x] 增加统一 `InteractionInput / UserTurn` 输入结构，解除策略入口对单一文本入口的耦合
31. [x] 为交互链补 `turn_id / interaction_session_id / request_id`
32. [x] 为策略查询补状态快照绑定协议
33. [x] 为输出层补 `pending / committed / cancelled / interrupted` 生命周期
34. [x] 为长任务 / 工具调用补取消接口（最小版）
35. [x] 建立 `ASR -> query normalization -> strategy -> TTS` 分层日志骨架（最小版）
36. [x] 定义结构化语音查询 schema 与指令路由接口（最小版）
37. [x] 定义语音场景下的确认 / 权限分级规则（最小版）
12. [x] 试跑 `yield_vs_defend_model` baseline，确认链路可行
13. [ ] 暂停 `yield_vs_defend_model`，等待更稳定的后验标签与样本覆盖后再重启

### 如果目标是提高工程质量

1. [x] 增加自动回归测试
2. [x] 增加 parser 样本断言
3. [x] 增加 dashboard 健康检查
4. [ ] 增加协议完成度跟踪表

## 当前一句话判断

Asurada Core 已经完成了“离线真实抓包策略脑”的核心建设，阶段一剩余工作主要集中在实时闭环和协议精修；阶段二已经具备开始模型化工作的基础。

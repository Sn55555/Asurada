# 阶段二模型总表

## 文档目的

本文档定义阶段二的正式模型与控制模块总表，用于回答以下问题：

- 阶段二到底要实现哪些模型与控制模块
- 每个模型对应什么主要功能
- 每个模型真实可用的输入字段有哪些
- 每个模型输出什么字段
- 推荐使用什么算法
- 标签从哪里来
- 用什么指标评估
- 是否允许进入实时主链

本文档只使用两类输入字段：

1. 当前项目已经稳定解析并进入标准化状态或 `raw` 的字段  
2. 可以直接由当前状态、短窗口历史和赛道模型稳定派生的字段

不使用目前项目中不存在、也没有稳定派生路径的字段。

配套文档：

- [PARSED_FIELDS_AND_MODEL_USAGE_CN.md](PARSED_FIELDS_AND_MODEL_USAGE_CN.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](STAGE2_MODEL_INPUT_SCHEMA.md)
- [SESSION_TYPE_CLASSIFICATION.md](SESSION_TYPE_CLASSIFICATION.md)
- [UNRESOLVED_PACKET_FIELDS.md](UNRESOLVED_PACKET_FIELDS.md)
- [REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md](REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md)

## 当前阶段二已完成模型概览

当前阶段二已经完成或推进到以下状态：

| 模型 / 模块 | 当前状态 | 当前结论 |
| --- | --- | --- |
| `rear_threat_model` | 已完成第一版 baseline | 当前可用 |
| `fuel_risk_model` | 已完成第一版 baseline 并按新口径重训 | 当前可用，已切到 `fuel_margin_laps` 主导口径 |
| `ers_risk_model` | 已完成第一版 baseline | 当前可用 |
| `tyre_risk_model` | 已完成第一版 baseline | 当前可用 |
| `dynamics_risk_model` | 已完成第一版 baseline | 当前可用 |
| `defence_cost_model` | 已完成第一版 baseline | 当前可用，但属于 proxy-distillation baseline，已旁路接入 runtime debug |
| `rival_pressure_model` | 已完成第一版 baseline | 已旁路接入 runtime debug；当前 `rear_pressure` 最稳，`front/rival` 仍需补更强样本与标签 |
| `entry_quality_model` | 已完成第一版 baseline | 已旁路接入 runtime debug；当前适合作为趋势/观察分数 |
| `apex_quality_model` | 已完成第一版 baseline | 已旁路接入 runtime debug；当前适合作为趋势/观察分数 |
| `exit_traction_model` | 已完成第一版 baseline | 已旁路接入 runtime debug；当前适合作为趋势/观察分数 |
| `counterattack_window_model` | 已完成训练入口与可训练性检查 | 当前阻塞：专题样本正类不足，不能继续训练 |
| `tyre_degradation_trend_model` | 已完成第一版 baseline | 当前可用，已旁路接入 runtime debug |
| `short_horizon_risk_forecast_model` | 已完成 baseline 试跑 | 当前暂不推进：未来风险标签定义和时序特征都不成立 |
| `driver_style_model` | 已完成 baseline 试跑 | 当前暂不推进：长窗口样本过少，风格标签塌缩 |
| `pit_rejoin_traffic_model` | 已完成可训练性检查 | 当前阻塞：导出特征缺少 `pit_status`，无法构造 rejoin 标签 |
| `attack_opportunity_model` | 已完成第一版 baseline | 当前可用，已具备 exported `val/test` |
| `front_attack_commit_model` | 已完成第一版 baseline | 当前可接受，已具备 exported `val/test`，后续仍需继续收紧标签 |
| `strategy_action_model` | 已完成第一版 baseline | 当前适合作为 `top-k` 候选提供器，不适合直接 `top-1` 直出 |
| `tactical_state_machine` | 已完成最小规则版 | 已生成真实 `previous/current tactical_state` 与 `state_transition`，并接入 `StrategyEngine` |
| `strategy_arbiter_v2` | 已接入主链 | 已消费真实 `strategy_action_model top-k`，并已接入自动回归断言 |
| `confidence_model / uncertainty_layer` | 已完成最小规则版 | 已生成真实 `confidence_context / fallback_context`，并接入 `arbiter_v2` |
| `session_mode_router` | 已完成最小规则版 | 已生成真实 `session_route`，并同时过滤规则候选与模型候选 |
| `fallback_policy` | 已完成最小规则版 | 已生成真实 `fallback_context / output_control`，并在 `arbiter_v2` 前生效 |
| `interaction_input_event model` | 已完成最小版 | 已生成真实 `interaction_session_id / turn_id / request_id / snapshot_binding`，并写入 debug 与日志 |
| `output_lifecycle model` | 已完成最小版 | 已生成真实 `start / interrupt / suppress / cancel / idle` 输出生命周期事件，并写入 debug 与日志 |
| `voice_pipeline_log skeleton` | 已完成最小版 | 已生成 `asr / query_normalization / strategy / tts` 四层日志骨架，并写入 debug 与日志 |
| `structured_query / query_route` | 已完成最小版 | 已生成独立 `structured_query schema` 与 `query_route`，并写入 debug 与分层日志 |
| `confirmation_policy` | 已完成最小版 | 已生成独立确认/权限策略，当前系统播报走 `auto_approve`，高风险动作预留 `confirm_before_execute` |
| `task_handle / task_lifecycle` | 已完成最小版 | 已生成独立任务句柄与取消生命周期，当前输出层可记录 `active_task / cancelled_task` 逻辑取消语义 |
| `yield_vs_defend_model` | 已试跑 baseline | 当前暂停，等待更稳定标签与样本 |
| `event_impact_model` | 已试跑 baseline | 当前暂停，等待更多事件样本与更强后验标签 |

完整推进状态、暂停原因和 checklist 以 [STATUS.md](STATUS.md) 为准。

## 总体原则

- 阶段二前半以 `LightGBM / XGBoost` 为主，先建立可解释、可回归、可旁路接入的基线模型。
- `position_change_event_detector`、`tactical_state_machine`、`strategy_arbiter_v2`、`session_mode_router`、`fallback_policy` 属于控制模块，不属于首批监督学习模型，但必须在阶段二内实现。
- 所有进入实时主链的模型或控制模块都必须输出统一结构：
  - `score`
  - `level`
  - `confidence`
  - `recommended_action`
  - `state_hint`
  - `cooldown_hint`
- 所有依赖 timing 的模型都必须显式读取：
  - `timing_mode`
  - `timing_support_level`
  - `gap_source_*`
  - `gap_confidence_*`

## 字段中文注释速查

下文各模型继续使用统一英文字段名，避免运行时字段名和文档字段名脱节。这里集中给出反复出现字段的中文含义。

### 通用状态字段

| 字段 | 中文含义 |
| --- | --- |
| `session_time_s` | 当前会话时间，单位秒 |
| `speed_kph` | 当前车速，单位公里每小时 |
| `position` | 当前名次 |
| `lap_number` | 当前圈数 |
| `track_segment` | 当前赛道分段名称 |
| `track_usage` | 当前赛道分段用途，例如进攻区、防守区、牵引区 |
| `driving_mode` | 当前驾驶模式或驾驶状态标签 |
| `status_tags` | 当前车辆状态标签集合，例如不稳、前轴过载等 |

### timing / gap 字段

| 字段 | 中文含义 |
| --- | --- |
| `timing_mode` | 当前 timing 解释模式，例如 `race_like`、`qualifying_like`、`time_trial_disabled` |
| `timing_support_level` | 当前 timing 可用等级，决定能否进入正式主链 |
| `official_gap_ahead_s` | 与前车的官方秒差，单位秒，仅官方来源可填 |
| `official_gap_behind_s` | 与后车的官方秒差，单位秒，仅官方来源可填 |
| `official_gap_confidence_ahead` | 前车官方秒差可信度 |
| `official_gap_confidence_behind` | 后车官方秒差可信度 |
| `gap_source_*` | gap 来源标记，例如官方 `LapData` 或调试估算来源 |
| `gap_confidence_*` | gap 可信度等级 |
| `gap_closing_rate` | gap 变化速度，表示前后车是在接近还是远离 |

### 资源与车辆状态字段

| 字段 | 中文含义 |
| --- | --- |
| `fuel_in_tank` | 当前油箱剩余燃油 |
| `fuel_laps_remaining` | 当前剩余燃油还能跑的圈数估计 |
| `ers_store_energy` | 当前 ERS 储能 |
| `ers_pct` | 当前 ERS 百分比 |
| `drs_available` | 当前是否可用 DRS |
| `tyre.wear_pct` | 当前轮胎平均磨损百分比 |
| `tyre.age_laps` | 当前轮胎已经使用的圈数 |
| `recent_front_overload_ratio` | 最近窗口内前轴过载占比 |
| `recent_unstable_ratio` | 最近窗口内车辆不稳定占比 |

### 动态与姿态字段

| 字段 | 中文含义 |
| --- | --- |
| `throttle` | 油门开度 |
| `brake` | 刹车开度 |
| `steer` | 转向输入 |
| `g_force_longitudinal` | 纵向 G 值 |
| `g_force_lateral` | 横向 G 值 |
| `yaw` | 偏航角或偏航状态 |
| `pitch` | 俯仰角或俯仰状态 |
| `roll` | 侧倾角或侧倾状态 |
| `wheel_slip_ratio` | 车轮滑移率 |
| `wheel_lat_force` | 车轮横向力 |
| `wheel_long_force` | 车轮纵向力 |

### 对手相关字段

| 字段 | 中文含义 |
| --- | --- |
| `rivals[].speed_kph` | 对手车速 |
| `rivals[].ers_pct` | 对手 ERS 百分比 |
| `rivals[].drs_available` | 对手是否可用 DRS |
| `rear_rival_speed_delta` | 后车相对本车的速度差 |
| `front_rival_speed_delta` | 本车相对前车的速度差 |
| `rear_rival_ers_pct` | 后车 ERS 百分比派生值 |
| `rear_rival_drs_available` | 后车 DRS 可用状态派生值 |
| `front_rival_ers_pct` | 前车 ERS 百分比派生值 |

### 赛道预视与战术上下文字段

| 字段 | 中文含义 |
| --- | --- |
| `next_track_segment` | 下一赛道分段名称 |
| `next_track_usage` | 下一赛道分段用途 |
| `next_two_segments` | 后续两个分段的组合预视信息 |
| `player_exit_quality_proxy` | 本车出弯质量代理分数 |
| `position_lost_recently` | 最近是否刚刚失位 |
| `current_tactical_state` | 当前战术状态机状态 |
| `previous_tactical_state` | 前一战术状态 |

### 常见输出字段

| 字段 | 中文含义 |
| --- | --- |
| `*_score` | 某类风险、机会或动作倾向的连续分值 |
| `*_level` | 某类状态的离散等级 |
| `confidence_score` | 结果可信度分数 |
| `recommended_action` | 推荐动作代码 |
| `state_hint` | 对状态机或仲裁层的状态提示 |
| `cooldown_hint` | 对仲裁层的冷却建议 |

## 当前可稳定派生的字段

以下字段虽然不是当前快照里的直接列，但可以由现有数据稳定派生，因此允许用于阶段二模型。

| 派生字段 | 派生方式 | 说明 |
| --- | --- | --- |
| `gap_closing_rate` | 最近窗口 `gap_*_s` 对 `session_time_s` 的差分 | 用于识别前后车逼近速度 |
| `rear_rival_speed_delta` | 最近后车 `speed_kph - player.speed_kph` | 用于判断后车压迫强度 |
| `front_rival_speed_delta` | 最近前车 `player.speed_kph - rival.speed_kph` | 用于判断攻击动量 |
| `rear_rival_ers_pct` | 最近后车 `ers_pct` | 当前 `rivals` 中已稳定可用 |
| `rear_rival_drs_available` | 最近后车 `drs_available` | 当前 `rivals` 中已稳定可用 |
| `next_track_segment` | 基于 `track_profile.classify(lap_distance_m + offset)` | 可用赛道语义模型预视下一段 |
| `next_track_usage` | 同上 | 用于反击与部署预判 |
| `next_two_segments` | 连续对两个 offset 做 `classify` | 用于反击窗口与动作规划 |
| `player_exit_quality_proxy` | 由 `exit_traction_model` 输出或当前 `throttle + wheel_slip_ratio + speed_kph` 规则代理 | 阶段二前半可先用规则代理 |
| `position_lost_recently` | `position_change_event_detector` 输出 | 作为战术状态触发条件 |
| `current_tactical_state` | `tactical_state_machine` 当前状态 | 作为动作模型上下文 |
| `previous_tactical_state` | 状态机前一状态 | 用于避免战术抖动 |

## 模型依赖与实现时序

本文档中的 `P0 / P1 / P2 / P3` 表示业务优先级与最终系统地位，不完全等同于编码和训练顺序。

阶段二实际推进必须遵守依赖顺序，原则如下：

1. 先完成数据与控制前置层  
   先有样本、特征、事件检测、路由和统一输出协议，后续模型才有稳定输入与消费方。

2. 再完成基础资源与状态模型  
   `fuel_risk_model`、`ers_risk_model`、`tyre_risk_model`、`dynamics_risk_model` 是上游模型。  
   攻防和动作决策模型会直接引用它们的输出，因此实现时必须早于相关攻防模型。

3. 再完成威胁、机会与代价模型  
   `rear_threat_model`、`attack_opportunity_model`、`defence_cost_model` 提供战术动作判断所需的中间评分。

4. 再完成动作决策模型  
   `yield_vs_defend_model`、`front_attack_commit_model`、`counterattack_window_model` 基于上游风险、机会和代价结果做动作选择。

5. 最后接入状态机、仲裁与回退  
   `tactical_state_machine`、`strategy_arbiter_v2`、`confidence_model / uncertainty_layer`、`fallback_policy` 负责把前面所有输出变成稳定可执行的主链动作。

### 关键依赖关系

| 下游模型/模块 | 关键前置依赖 | 说明 |
| --- | --- | --- |
| `rear_threat_model` | `position_change_event_detector`, 攻防专题样本, `gap_closing_rate` 特征 | 没有事件与 closing-rate，后车威胁只能停留在单帧 gap 提醒 |
| `attack_opportunity_model` | `ers_risk_model`, `tyre_risk_model` | 攻击机会不只看 gap，还要看资源与轮胎承受能力 |
| `defence_cost_model` | `ers_risk_model`, `tyre_risk_model`, `dynamics_risk_model` | 防守代价必须引用资源、轮胎和姿态风险 |
| `front_attack_commit_model` | `attack_opportunity_model`, `ers_risk_model`, `tyre_risk_model`, `dynamics_risk_model` | 判断是否真投入进攻，必须基于机会和资源状态 |
| `yield_vs_defend_model` | `rear_threat_model`, `defence_cost_model`, `ers_risk_model`, `tyre_risk_model`, `dynamics_risk_model` | 防守/让位判断本质上是威胁收益与代价权衡 |
| `counterattack_window_model` | `position_change_event_detector`, `rear_threat_model`, `ers_risk_model`, `track` 预视特征 | 失位后反击必须知道“刚失位”且要看下一段 |
| `event_impact_model` | `position_change_event_detector`, `session_mode_router` | 事件影响要结合会话模式和关键事件节点 |
| `tactical_state_machine` | `rear_threat_model`, `yield_vs_defend_model`, `counterattack_window_model`, `front_attack_commit_model`, `event_impact_model`, `position_change_event_detector` | 状态机是所有战术评分与事件的汇总层 |
| `strategy_arbiter_v2` | `tactical_state_machine`, `strategy_action_model`, `confidence_model / uncertainty_layer`, `fallback_policy`, `model_output_contract` | 仲裁层只消费统一输出，不直接处理模型细节 |
| `confidence_model / uncertainty_layer` | `session_mode_router`, `model_output_contract`, 各上游模型输出 | 置信度层负责判断主链是否可用 |

### 实现时序总结

阶段二实现顺序压缩为以下 5 层：

1. 数据与控制前置层  
   攻防专题样本集、`closing_rate / next_segment / tactical_context` 特征、`session_mode_router`、`model_output_contract`、`position_change_event_detector`

2. 基础资源与状态模型层  
   `fuel_risk_model`、`ers_risk_model`、`tyre_risk_model`、`dynamics_risk_model`

3. 威胁、机会与代价模型层  
   `rear_threat_model`、`attack_opportunity_model`、`defence_cost_model`、`event_impact_model`

4. 动作决策模型层  
   `front_attack_commit_model`、`yield_vs_defend_model`、`counterattack_window_model`、`strategy_action_model`

5. 主链控制与回退层  
   `confidence_model / uncertainty_layer`、`tactical_state_machine`、`strategy_arbiter_v2`、`fallback_policy`

后续增强继续放在上述 5 层之后：

- 第二批增强：`rival_pressure_model`、`entry_quality_model`、`apex_quality_model`、`exit_traction_model`
- 后段模型：`tyre_degradation_trend_model`、`short_horizon_risk_forecast_model`、`driver_style_model`、`pit_rejoin_traffic_model`

## P0 核心主线

这组模型和控制模块直接服务于以下主目标：

- 后车逼近识别
- 防守策略选择
- 失守后反击
- 连续战术控制
- 主链置信度与回退控制

### `rear_threat_model`

主要功能：
- 识别后车是否正在形成真实超车威胁
- 判断当前区段是否进入高风险防守窗口

输入字段：
- `official_gap_behind_s`
- `official_gap_confidence_behind`
- `timing_support_level`
- `speed_kph`
- `rivals[].speed_kph`
- `rivals[].ers_pct`
- `rivals[].drs_available`
- `track_segment`
- `track_usage`
- `driving_mode`
- `recent_unstable_ratio`
- 派生字段：
  - `gap_closing_rate`
  - `rear_rival_speed_delta`
  - `rear_rival_ers_pct`
  - `rear_rival_drs_available`

输出字段：
- `rear_threat_score`
- `rear_threat_level`
- `overtake_risk_next_zone`
- `rear_threat_confidence`
- `recommended_action`

推荐算法：
- `LightGBM`
- `XGBoost`

标签来源：
- 规则伪标签
- 攻防专题样本中的“后车压迫片段”
- 失位前若干秒窗口的后验事件标签

评估指标：
- AUC
- F1
- threat recall
- false alarm rate

是否进入实时主链：
- 是

### `yield_vs_defend_model`

主要功能：
- 判断当前更适合硬防、软防，还是让位后保反击

当前状态：
- `已做 baseline 尝试`
- `当前暂停`
- 原因：现阶段 `yield_vs_fight` 后验标签与样本覆盖仍不稳定，继续强推训练会拖慢阶段二主线
- 重启条件：
  - 更稳定的后验 `yield_vs_fight` 标签
  - 更完整的攻防专题样本
  - 或可独立验证的防守/失位/反击事件序列

输入字段：
- `rear_threat_score`
- `rear_threat_level`
- `ers_pct`
- `fuel_laps_remaining`
- `tyre.wear_pct`
- `tyre.age_laps`
- `dynamics_risk_score`
- `track_segment`
- `track_usage`
- `speed_kph`
- `status_tags`
- 派生字段：
  - `player_exit_quality_proxy`

输出字段：
- `defend_hard_score`
- `defend_soft_score`
- `yield_and_counter_score`
- `recommended_defence_plan`
- `recommended_action`

推荐算法：
- `LightGBM Classifier`
- `XGBoost Classifier`

标签来源：
- 规则伪标签
- 攻防专题样本
- 小规模人工复核样本

评估指标：
- accuracy
- macro F1
- tactical cost consistency

是否进入实时主链：
- 是

### `counterattack_window_model`

主要功能：
- 在失守后识别反击窗口
- 判断下一段或下下段是否值得投入反击

当前状态：
- `已完成训练入口与可训练性检查`
- 当前结论：
  - 当前阻塞，不能继续训练
  - 当前 `counterattack_candidate_label` 正类样本远不足以支持有效 baseline
- 当前样本分布：
  - `train = 2025`，正类 `1`
  - `val = 1012`，正类 `1`
  - `test = 4970`，正类 `0`
- 当前说明：
  - 训练入口已建立
  - 阻塞报告已落地到 `training/reports/counterattack_window_baseline/`
  - 后续应先补 `counterattack` 专题样本，而不是直接调参

输入字段：
- `position_lost_recently`
- `official_gap_ahead_s`
- `official_gap_confidence_ahead`
- `timing_support_level`
- `drs_available`
- `ers_pct`
- `speed_kph`
- `track_segment`
- `track_usage`
- 派生字段：
  - `gap_closing_rate`
  - `front_rival_speed_delta`
  - `next_track_segment`
  - `next_track_usage`
  - `next_two_segments`
  - `player_exit_quality_proxy`

输出字段：
- `counterattack_window_score`
- `counterattack_window_segment`
- `ers_counter_commit_score`
- `counterattack_arm`
- `recommended_action`

推荐算法：
- `LightGBM`
- `XGBoost`

标签来源：
- 失位后反击专题样本
- 规则脚本标签
- DRS 保持 / 重新接近成功的后验标签

评估指标：
- Recall@window
- counter success rate
- miss rate
- next-zone hit rate

是否进入实时主链：
- 是

专题样本设计建议：
- 事件起点：
  - `position_lost_recently = 1`
- 正类后验条件：
  - 未来 `5.0 ~ 8.0s` 内满足至少一项：
    - `position_gain_recently = 1`
    - `drs_recovery_window = 1`
    - `official_gap_ahead_s` 缩小到攻击阈值
- 在正类数量未达最小阈值前，不接 runtime，不接主链

### `front_attack_commit_model`

主要功能：
- 在“存在攻击机会”的前提下，判断是否值得真正投入资源去超车

当前状态：
- `已做 baseline 尝试`
- `当前可用`
- 当前验证：
  - 已通过 `player + rear_rival` 双视角攻击样本导出打通跨 session 外部 test
  - 已通过 `uid15` 第 2 圈显式切出 exported val，不再依赖 `train_holdout_split`
  - 当前训练主样本来自 `uid15` 第 1/3 圈
  - 当前 exported val 主样本来自 `uid15` 第 2 圈
  - 当前外部 test 主样本来自 `uid16`
- 当前指标：
  - `accuracy=0.9996`
  - `positive precision=0.7647`
  - `positive recall=1.0000`
- 下一步收口条件：
  - 继续增强 `attack_commit_proxy_label` 的 DRS 和持续逼近信号
  - 补更多有官方前车 gap 的 race-like 样本，验证稳定性是否可持续

输入字段：
- `attack_opportunity_score`
- `ers_pct`
- `fuel_laps_remaining`
- `tyre.wear_pct`
- `dynamics_risk_score`
- `track_segment`
- `track_usage`
- 派生字段：
  - `next_track_segment`
  - `next_track_usage`
  - `player_exit_quality_proxy`

输出字段：
- `attack_commit_score`
- `attack_commit_action`
- `ers_commit_value`
- `confidence`

推荐算法：
- `LightGBM`
- `XGBoost`

标签来源：
- 超车成功/失败样本
- 规则伪标签
- 专题复盘标签

评估指标：
- commit precision
- top-1 action accuracy
- cost-benefit score

是否进入实时主链：
- 是

### `event_impact_model`

主要功能：
- 评估碰撞、处罚、起步、最快圈、安全车等事件对当前与后续策略的影响

当前状态：
- `已做 baseline 尝试`
- `当前暂停`
- 原因：当前事件样本量偏小，且跨 `session` 分布差异明显；在全事件集合与 race-like 子集上都未得到稳定 baseline
- 重启条件：
  - 补更多 race-like 事件样本
  - 或重做更稳定的事件后验影响标签

输入字段：
- `event_code`
- `event_detail`
- `lap_number`
- `position`
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `track_segment`
- `track_usage`
- `safety_car`
- `weather`
- `result_status`

输出字段：
- `event_impact_score`
- `event_strategy_shift`
- `event_risk_delta`
- `recommended_action`

推荐算法：
- `LightGBM`
- `XGBoost`

标签来源：
- 事件流后验标签
- 规则脚本标签
- 关键事件前后窗口对比标签

评估指标：
- event impact accuracy
- shift precision
- recall

是否进入实时主链：
- 是

### `position_change_event_detector`

主要功能：
- 识别刚刚被超、刚刚完成超车、发生重叠、switchback 成功/失败等关键战术事件

输入字段：
- `position`
- `lap_distance_m`
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `frame_identifier`
- `session_time_s`
- `lap_positions`
- `rivals`
- `event_code`
- `event_detail`

输出字段：
- `position_lost_event`
- `position_gain_event`
- `overlap_state`
- `switchback_event`
- `event_confidence`

推荐实现：
- 规则检测
- 事件脚本

标签来源：
- 回放事件后验校验
- 攻防专题样本人工复核

评估指标：
- event precision
- event recall
- detection latency

是否进入实时主链：
- 是

### `tactical_state_machine`

主要功能：
- 将后车威胁、防守、失守、反击串成连续战术过程
- 防止每帧输出抖动和战术跳变

输入字段：
- `rear_threat_model` 输出
- `yield_vs_defend_model` 输出
- `counterattack_window_model` 输出
- `front_attack_commit_model` 输出
- `position_change_event_detector` 输出
- `event_impact_model` 输出
- `current_tactical_state`
- `previous_tactical_state`

输出字段：
- `tactical_state`
- `state_transition`
- `state_priority_hint`
- `state_lock`
- `recommended_action`

推荐实现：
- 规则状态机
- 后续可加模型评分辅助状态迁移

标签来源：
- 工程定义
- 回放对齐校验

评估指标：
- state jitter rate
- transition correctness
- tactical continuity

是否进入实时主链：
- 是

当前状态：
- 已完成最小规则版并接入 `StrategyEngine`
- 当前会根据前一帧位置变化、当前攻防窗口和短窗上下文生成：
  - `previous_tactical_state`
  - `tactical_state`
  - `state_transition`
  - `state_priority_hint`
  - `state_lock`
- 当前已按 `session_uid` 记住上一帧战术态和上一条主动作
- 当 gap 仍处于宽松阈值内时，会保持 `DEFEND_WINDOW / ATTACK_WINDOW` 对应战术态，降低抖动
- 当前仍未接入 `yield_vs_defend_model / counterattack_window_model / event_impact_model` 的正式输出

### `strategy_arbiter_v2`

主要功能：
- 统一仲裁规则链、模型链和战术状态机输出

输入字段：
- 规则候选消息
- 模型候选动作
- `tactical_state`
- `confidence_score`
- `cooldown_hint`
- `fallback_mode`

输入结构建议：
- `rule_candidates`
  - `code`
  - `priority`
  - `source`
  - `expires_in_frames`
- `model_candidates`
  - `code`
  - `score`
  - `rank`
  - `source_model`
- `tactical_context`
  - `tactical_state`
  - `state_priority_hint`
  - `state_lock`
  - `state_transition`
- `confidence_context`
  - `confidence_score`
  - `confidence_level`
  - `mainline_allowed`
- `fallback_context`
  - `fallback_mode`
  - `voice_allowed`
  - `hud_only`
- `output_control`
  - `cooldown_hint`
  - `last_emitted_action`
  - `suppression_window`

输出字段：
- `final_hud_action`
- `final_voice_action`
- `final_strategy_stack`
- `suppressed_actions`

输出结构建议：
- `final_hud_action`
  - `code`
  - `reason`
  - `source`
- `final_voice_action`
  - `code`
  - `speak_text`
  - `priority`
  - `interrupt`
- `final_strategy_stack`
  - `primary`
  - `secondary`
  - `tactical_state`
  - `confidence_level`
- `suppressed_actions`
  - `code`
  - `suppression_reason`

推荐实现：
- 规则仲裁层
- 当前实现状态：
  - 代码骨架已落地：`/Users/sn5/Asurada/asurada-core/src/asurada/arbiter.py`
  - 当前已实现独立 `ArbiterInput / ArbiterOutput` 契约
  - 当前已实现最小仲裁逻辑：
    - `rule_only` fallback
    - `cooldown_window` suppression
    - `tactical_state` 优先级偏置
    - HUD / voice / strategy stack 输出
  - 当前已接入：
    - 已以 sidecar 方式接入 `StrategyEngine.evaluate()` 的 debug 输出
    - 已真实消费 `strategy_action_model` 的 `top-k` 候选
    - 已将仲裁结果接入最终动作主链
    - 已为模型驱动动作增加 priority 校准层
    - 已接入自动回归断言：
      - `priority_floor_calibrated`
      - `cooldown_suppresses_last_action`
      - `duplicate_codes_deduped`

标签来源：
- 工程定义

评估指标：
- arbitration consistency
- suppression correctness
- top-k selection correctness
- cooldown stability
- tactical-state alignment

是否进入实时主链：
- 是

### `confidence_model / uncertainty_layer`

主要功能：
- 判断模型结果能否被信任、能否进入主链、何时回退规则链

输入字段：
- 各模型输出分数
- `timing_support_level`
- `official_gap_confidence_ahead`
- `official_gap_confidence_behind`
- session type
- 特征缺失率
- OOD 检测信号
- 当前 `tactical_state`

输出字段：
- `confidence_score`
- `confidence_level`
- `mainline_allowed`
- `voice_allowed`
- `fallback_recommended`
- `fallback_reason`

推荐实现：
- 规则校准层
- 后续可用轻量分类器增强

标签来源：
- 后验误差标签
- 主链误判记录
- 工程规则

评估指标：
- calibration error
- fallback precision
- unsafe-pass rate

是否进入实时主链：
- 是

### `session_mode_router`

主要功能：
- 根据 session 类型、timing 模式和支持等级切换模型和参数

当前状态：
- 最小规则版已实现
- 已从 `StrategyEngine` 主链生效
- 已输出真实 `session_route`
- 已同时过滤：
  - `rule_candidates`
  - `model_candidates`

当前路由策略：
- `race_like + official_preferred`
  - 允许 race 资源动作和 timing 动作
- `session_type_estimated`
  - 禁用 timing 动作
  - 保留非 timing 的 race 资源与动态动作
- `QualifyingLike / Time Trial / 非 race-like`
  - 仅保留：
    - `NONE`
    - `DYNAMICS_UNSTABLE`
    - `FRONT_LOAD`

输入字段：
- `session_type`
- `timing_mode`
- `timing_support_level`
- `game_mode`
- `total_laps`

输出字段：
- `session_mode`
- `allowed_action_codes`
- `allow_timing_actions`
- `allow_race_resource_actions`
- `route_reason`

推荐实现：
- 规则路由层

标签来源：
- session 分类文档
- 样本验证结果

评估指标：
- routing correctness
- `session_route_present`
- `time_trial_route_filters_race_actions`

是否进入实时主链：
- 是

### `model_output_contract`

主要功能：
- 为所有模型定义统一输出结构，确保 dashboard、日志、HUD、语音消费一致

输入字段：
- 各模型原始输出

输出字段：
- `score`
- `level`
- `confidence`
- `recommended_action`
- `state_hint`
- `cooldown_hint`

推荐实现：
- 结构协议层

标签来源：
- 工程规范

评估指标：
- contract validation pass rate

是否进入实时主链：
- 是

### `fallback_policy`

主要功能：
- 模型低可信或输入不足时，切换回规则链或降级输出

输入字段：
- `confidence_score`
- `timing_support_level`
- 缺失字段标志
- session mode
- `tactical_state`

输出字段：
- `fallback_mode`
- `rule_only`
- `hud_only`
- `voice_suppressed`

推荐实现：
- 规则控制层

标签来源：
- 工程规则
- 错误案例复盘

评估指标：
- fallback correctness
- unsafe voice suppression rate

是否进入实时主链：
- 是

当前状态：
- 已完成最小规则版并接入 `StrategyEngine -> strategy_arbiter_v2`
- 当前会根据 `session_route + confidence_resolution + tactical_state` 输出真实 `fallback_context / output_control`
- 当前仍未接真实 `last_emitted_action` 和多轮任务状态

## P1 第一批核心模型

### `fuel_risk_model`

主要功能：
- 燃油风险评分和节奏压力判断

当前状态：
- `已完成第一版 baseline，并已按新燃油边际口径重训`
- 当前指标：
  - `mae=20.7958`
  - `rmse=39.2586`
  - `r2=0.0000`
- 当前说明：
  - 已切换到项目内派生燃油口径
  - 已去掉 `derived fuel` 可用时由 `tank_ratio <= 0.08` 直接触发 `critical` 的旧口径
  - 当前 `uid16` exported test 标签已收敛到稳定低风险范围
  - 训练表已纳入：
    - `derived_fuel_laps_remaining`
    - `fuel_margin_laps`
    - `fuel_laps_remaining_source`

输入字段：
- `fuel_in_tank`
- `fuel_capacity`
- `fuel_laps_remaining`
- `lap_number`
- `total_laps`
- `session_type`
- `track_usage`
- `safety_car`

输出字段：
- `fuel_risk_score`
- `fuel_risk_level`

推荐算法：
- `LightGBM Regressor`

标签来源：
- 规则伪标签
- 后验比赛结果

评估指标：
- MAE
- rank correlation

是否进入实时主链：
- 是

### `ers_risk_model`

主要功能：
- ERS 风险、保电价值、投入价值判断

当前状态：
- `已完成第一版 baseline`
- 当前指标：
  - `mae=0.2329`
  - `rmse=1.3906`
  - `r2=0.9609`

输入字段：
- `ers_store_energy`
- `ers_pct`
- `ers_deploy_mode`
- `track_usage`
- `driving_mode`
- `official_gap_ahead_s`
- `official_gap_behind_s`

输出字段：
- `ers_risk_score`
- `ers_hold_value`
- `ers_commit_value`

推荐算法：
- `LightGBM Regressor`

标签来源：
- 规则伪标签
- 攻防专题样本

评估指标：
- MAE
- tactical value correlation

是否进入实时主链：
- 是

### `tyre_risk_model`

主要功能：
- 轮胎风险与管理压力评分

当前状态：
- `已完成第一版 baseline`
- 当前指标：
  - `mae=0.0305`
  - `rmse=0.0699`
  - `r2=0.9998`

输入字段：
- `tyre.compound`
- `tyre.age_laps`
- `tyre.wear_pct`
- `tyres_wear_pct[4]`
- `tyres_damage_pct[4]`
- `wheel_slip_ratio`
- `track_segment`
- `track_usage`
- `recent_front_overload_ratio`

输出字段：
- `tyre_risk_score`
- `front_tyre_management_score`
- `rear_traction_risk_score`

推荐算法：
- `LightGBM`
- `XGBoost`

标签来源：
- 规则伪标签
- 后验退化标签

评估指标：
- MAE
- monotonicity
- risk recall

是否进入实时主链：
- 是

### `dynamics_risk_model`

主要功能：
- 当前姿态和动态风险评分

当前状态：
- `已完成第一版 baseline`
- 当前指标：
  - `mae=0.1149`
  - `rmse=1.2109`
  - `r2=0.9541`

输入字段：
- `g_force_lateral`
- `g_force_longitudinal`
- `g_force_vertical`
- `yaw`
- `pitch`
- `roll`
- `wheel_slip_ratio`
- `wheel_lat_force`
- `wheel_long_force`
- `recent_unstable_ratio`
- `track_zone`
- `track_usage`

输出字段：
- `dynamics_risk_score`
- `stability_score`

推荐算法：
- `LightGBM`

标签来源：
- 规则标签
- 动态专题样本

评估指标：
- AUC
- MAE
- unstable recall

是否进入实时主链：
- 是

### `attack_opportunity_model`

主要功能：
- 攻击窗口识别

当前状态：
- `已做 baseline 尝试`
- `当前可用`
- 当前验证：
  - 已通过 `player + rear_rival` 双视角攻击样本导出打通跨 session 外部 test
  - 已通过 `uid15` 第 2 圈显式切出 exported val，不再依赖 `train_holdout_split`
  - 当前训练主样本来自 `uid15` 第 1/3 圈
  - 当前 exported val 主样本来自 `uid15` 第 2 圈
  - 当前外部 test 主样本来自 `uid16`
- 当前指标：
  - `accuracy=0.9994`
  - `positive precision=1.0000`
  - `positive recall=0.7931`
- 当前意义：
  - `front_attack_commit_model` 已有可训练上游，不再只依赖规则型 `attack_opportunity_label`
- 下一步收口条件：
  - 验证 `attack_opportunity -> front_attack_commit` 在更多 race-like session 中的稳定性
  - 继续观察 exported val 与外部 test 的 recall 差异

输入字段：
- `official_gap_ahead_s`
- `official_gap_confidence_ahead`
- `timing_support_level`
- `drs_available`
- `ers_pct`
- `speed_kph`
- `track_segment`
- `track_usage`

输出字段：
- `attack_opportunity_score`
- `attack_window_level`

推荐算法：
- `LightGBM Classifier`

标签来源：
- 规则伪标签
- 超车前窗口样本

评估指标：
- precision
- recall
- top-k

是否进入实时主链：
- 是

### `strategy_action_model`

当前状态：
- `已做 baseline 尝试`
- `当前可用`
- 当前动作范围：
  - `NONE`
  - `LOW_FUEL`
  - `DEFEND_WINDOW`
  - `DYNAMICS_UNSTABLE`
- 当前指标：
  - `top1_accuracy=0.7052`
  - `top2_accuracy=0.9998`
- 当前边界：
  - 当前已改用 `strategy_action_features_v1.csv`
  - 当前 `val` 已来自 `exported_val_split`
  - 当前仍只覆盖高频动作子集，未覆盖 `ATTACK_WINDOW / ERS_LOW / FRONT_LOAD`
- 当前意义：
  - 第一版 baseline 已可为 `strategy_arbiter_v2` 提供 `top-k` 候选
  - 当前不适合直接 top-1 直出

主要功能：
- 综合风险、机会和战术状态，输出当前首要动作候选

输入字段：
- 各风险模型输出
- `rear_threat_score`
- `attack_opportunity_score`
- `track_usage`
- `safety_car`
- `tactical_state`

输出字段：
- `action_candidates`
- `action_priority_scores`
- `primary_action`

推荐算法：
- `LightGBM Ranker`
- 多分类基线

标签来源：
- 规则引擎输出
- 人工复核样本

评估指标：
- top-1
- top-2
- 候选覆盖率
- rank correlation

是否进入实时主链：
- 是

### `defence_cost_model`

主要功能：
- 量化防守动作的资源与节奏代价

输入字段：
- `rear_threat_score`
- `ers_pct`
- `tyre_risk_score`
- `dynamics_risk_score`
- `speed_kph`
- `track_segment`
- `track_usage`
- 派生字段：
  - `player_exit_quality_proxy`

输出字段：
- `defence_cost_score`
- `ers_cost_estimate`
- `tyre_cost_estimate`
- `exit_loss_score`

推荐算法：
- `LightGBM Regressor`

标签来源：
- 当前阶段一轮 baseline：
  - `features.csv + labels.csv`
  - 从现有字段重算 `defence_cost_proxy`
- 后续目标：
  - 攻防专题样本
  - 后验损失标签

评估指标：
- MAE
- tactical cost correlation

是否进入实时主链：
- 是

当前实现状态：
- 已完成第一版 baseline
- 当前训练口径：
  - 过滤 `official_preferred + race-like tactical rows`
  - deterministic split：
    - `uid15 lap 1/3 -> train`
    - `uid15 lap 2 -> val`
    - `uid16 -> test`
- 当前指标：
  - `mae=2.7160`
  - `rmse=4.4729`
  - `r2=0.3031`
  - `tactical_cost_correlation=0.7154`
- 当前边界：
  - 仍是 `proxy_distillation_baseline`
  - 不是后验损失标签模型
  - 已旁路接入 runtime debug，但尚未接入主链仲裁

## P2 第二批增强模型

### `rival_pressure_model`

主要功能：
- 综合评估前后车压迫态势

输入字段：
- `official_gap_ahead_s`
- `official_gap_behind_s`
- `timing_support_level`
- `rivals[].ers_pct`
- `rivals[].tyre.wear_pct`
- `rivals[].speed_kph`
- `track_segment`

输出字段：
- `rival_pressure_score`
- `front_pressure_score`
- `rear_pressure_score`

推荐算法：
- `LightGBM`

标签来源：
- 当前第一版为 `proxy-distillation baseline`
- 由 `features.csv` 中的前后车差距、相对速度、ERS、DRS、区段语义重算：
  - `front_pressure_proxy`
  - `rear_pressure_proxy`
  - `rival_pressure_proxy`

评估指标：
- MAE
- threat ranking accuracy

是否进入实时主链：
- 是

当前实现状态：
- 已完成第一版 baseline，并已旁路接入 runtime debug
- 当前拆成三个分数：
  - `front_pressure_model`
  - `rear_pressure_model`
  - `rival_pressure_model`
- 当前结果：
  - `front_pressure_model`
    - `mae=11.9885`
    - `rmse=12.4644`
    - `r2=0.0000`
    - `threat_ranking_accuracy=0.0000`
    - 说明：当前 race-like 样本里前车压迫信号不足，还不能单独视为可用模型
  - `rear_pressure_model`
    - `mae=4.0431`
    - `rmse=5.0826`
    - `r2=0.9839`
    - `threat_ranking_accuracy=0.9484`
    - 说明：当前最稳定，已可作为旁路压力分数
  - `rival_pressure_model`
    - `mae=25.4790`
    - `rmse=29.5207`
    - `r2=0.4563`
    - `threat_ranking_accuracy=0.8439`
    - 说明：已可用于 debug 观察综合态势，但还不适合直接接主链仲裁

当前边界：
- 当前是多输出 proxy-distillation 基线，不是后验对抗收益模型
- 当前更适合作为：
  - runtime debug sidecar
  - 后续 `rear_threat / attack_opportunity / strategy_action` 的态势观察层
- 不宜直接替代现有主链判断

### `entry_quality_model`

主要功能：
- 入弯质量评分

输入字段：
- `brake`
- `steer`
- `g_force_longitudinal`
- `wheel_slip_ratio`
- `track_segment`
- `track_usage`

输出字段：
- `entry_quality_score`

推荐算法：
- `XGBoost`
- `RandomForest`

标签来源：
- 规则评分
- 人工复核样本

评估指标：
- MAE
- score consistency

是否进入实时主链：
- 否，旁路优先

### `apex_quality_model`

主要功能：
- 弯心旋转质量评分

输入字段：
- `yaw`
- `roll`
- `steer`
- `wheel_lat_force`
- `track_segment`

输出字段：
- `apex_quality_score`

推荐算法：
- `XGBoost`

标签来源：
- 规则评分
- 人工复核样本

评估指标：
- MAE
- score consistency

是否进入实时主链：
- 否，旁路优先

### `exit_traction_model`

主要功能：
- 出弯牵引质量评分

输入字段：
- `throttle`
- `wheel_slip_ratio`
- `speed_kph`
- `tyre.wear_pct`
- `track_usage`
- 派生字段：
  - `next_track_usage`

输出字段：
- `exit_traction_score`

推荐算法：
- `LightGBM`

标签来源：
- 规则评分
- 人工复核样本

评估指标：
- MAE
- traction error rate

是否进入实时主链：
- 否，旁路优先

## P3 后段模型

### `tyre_degradation_trend_model`

主要功能：
- 预测短期胎耗和抓地下滑趋势

当前状态：
- `已完成第一版 baseline`
- 当前指标：
  - `future_tyre_wear_delta`
    - `mae=0.1159`
    - `rmse=0.1806`
    - `r2=0.6131`
  - `future_grip_drop_score`
    - `mae=0.8203`
    - `rmse=1.2437`
    - `r2=0.5770`
- 当前说明：
  - 训练口径：
    - 仅保留 `official_preferred + race-like`
    - 未来窗口 `15.0s`
    - `uid15 lap 2 -> val`
    - `uid16 -> test`
  - 当前已旁路接入 runtime debug
  - 当前不进入主链，只作为趋势观察分数

输入字段：
- `tyre.age_laps`
- `tyre.wear_pct`
- `tyres_wear_pct[4]`
- `wheel_slip_ratio`
- `wheel_lat_force`
- `wheel_long_force`
- `track_usage`
- `recent_front_overload_ratio`

输出字段：
- `future_tyre_wear_delta`
- `future_grip_drop_score`

推荐算法：
- `LightGBM` baseline
- `LSTM / Temporal CNN` 后续增强

标签来源：
- 后验时序标签

评估指标：
- MAE
- forecast stability

是否进入实时主链：
- 后续再定

当前状态：
- 已完成 baseline 试跑
- 当前指标：
  - `risk_forecast_3s`：`mae=25.14`、`rmse=26.94`、`r2=-3.16`
  - `risk_forecast_next_zone`：`mae=16.21`、`rmse=17.16`、`r2=-0.81`
- 当前结论：
  - 目标定义和时序特征都不成立，暂不推进

### `short_horizon_risk_forecast_model`

主要功能：
- 预测接下来短时间风险变化

输入字段：
- 风险模型输出
- `recent_unstable_ratio`
- `recent_front_overload_ratio`
- `track_segment`
- `track_usage`
- `rear_threat_score`
- `attack_opportunity_score`

输出字段：
- `risk_forecast_3s`
- `risk_forecast_next_zone`

推荐算法：
- `LSTM`
- `Temporal CNN`

标签来源：
- 后验时序标签

评估指标：
- MAE
- next-zone hit rate

是否进入实时主链：
- 后续再定

### `driver_style_model`

主要功能：
- 驾驶风格与一致性建模

输入字段：
- 区段级统计
- `recent_unstable_ratio`
- `recent_front_overload_ratio`
- `g_force_*`
- `wheel_slip_ratio`
- `entry_quality_score`
- `apex_quality_score`
- `exit_traction_score`

输出字段：
- `driver_style_tag`
- `aggression_score`
- `consistency_score`

推荐算法：
- `XGBoost`
- 聚类
- 轻量序列模型

标签来源：
- 长时段统计标签
- 人工归类

评估指标：
- classification F1
- stability

是否进入实时主链：
- 否

当前状态：
- 已完成 baseline 试跑
- 当前采用 `20s` 长窗口聚合构造 `aggression_score / consistency_score / driver_style_tag` 代理标签
- 当前结论：
  - 长窗口样本仅 `42` 条
  - `val/test` 类别分布塌缩
  - 当前 baseline 不成立，暂不推进

### `pit_rejoin_traffic_model`

主要功能：
- 评估进站后回场车流风险

输入字段：
- `pit_window_score`
- `position`
- `lap_positions`
- `session_type`
- `rivals`
- `track_segment`

输出字段：
- `pit_rejoin_risk_score`
- `rejoin_band`
- `traffic_penalty_score`

推荐算法：
- `LightGBM`

标签来源：
- 进站后验样本

评估指标：
- MAE
- traffic band accuracy

是否进入实时主链：
- 否，后段再定

当前状态：
- 已完成可训练性检查
- 当前阻塞：
  - 当前导出训练表缺少 `pit_status`
  - 没有显式进站进入/回场状态，无法构造 rejoin traffic 标签

## 阶段二必须建设的专题样本集

以下样本集不是可选项，而是阶段二必须项：

- 后车压迫片段
- 防守成功片段
- 防守失败片段
- 失位后反击成功片段
- 失位后反击失败片段
- switchback 片段
- 高威胁重刹区片段

## 阶段二必须建设的评估项

除常规精度指标外，必须加入：

- 状态切换抖动率
- 连续动作翻转次数
- 误切换率
- 关键事件漏检率
- 防守成功率
- 失守后反击成功率
- DRS 保持率
- 动作代价收益比

## 阶段二推荐实现顺序

### 第 0 层：数据与控制前置

1. 构建攻防专题样本集
2. 构建 `closing_rate / next_segment / tactical_context` 特征
3. 实现 `session_mode_router`
4. 实现 `model_output_contract`
5. 实现 `position_change_event_detector`

### 第 1 层：基础资源与状态模型

6. 训练 `fuel_risk_model`
7. 训练 `ers_risk_model`
8. 训练 `tyre_risk_model`
9. 训练 `dynamics_risk_model`

### 第 2 层：威胁、机会与代价模型

10. 训练 `rear_threat_model`
11. 训练 `attack_opportunity_model`
12. 训练 `defence_cost_model`
13. 实现 / 训练 `event_impact_model`

### 第 3 层：动作决策模型

14. 训练 `front_attack_commit_model`
15. 训练 `yield_vs_defend_model`
16. 训练 `counterattack_window_model`
17. 训练 `strategy_action_model`

### 第 4 层：主链控制与回退

18. 完成 `confidence_model / uncertainty_layer` 最小规则版
19. 实现 `tactical_state_machine`
20. 接入 `strategy_arbiter_v2`
21. 接入完整 `fallback_policy`
22. 完成 dashboard 模型对比与回归

### 第 5 层：阶段三防返工接口预埋

23. 定义统一 `InteractionInput / UserTurn` 输入结构
24. 增加 `turn_id / interaction_session_id / request_id`
25. 定义策略查询与状态快照绑定协议
26. 为输出层增加 `pending / committed / cancelled / interrupted` 生命周期
27. 为工具与长任务增加取消接口
28. 定义结构化语音查询 schema 与指令路由接口
29. 建立 `ASR -> query normalization -> strategy -> TTS` 分层日志骨架
30. 定义语音确认 / 权限分级最小规则版

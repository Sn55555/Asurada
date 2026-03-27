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

- [PARSED_FIELDS_AND_MODEL_USAGE_CN.md](/Users/sn5/Asurada/asurada-core/PARSED_FIELDS_AND_MODEL_USAGE_CN.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](/Users/sn5/Asurada/asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md)
- [SESSION_TYPE_CLASSIFICATION.md](/Users/sn5/Asurada/asurada-core/SESSION_TYPE_CLASSIFICATION.md)
- [UNRESOLVED_PACKET_FIELDS.md](/Users/sn5/Asurada/asurada-core/UNRESOLVED_PACKET_FIELDS.md)
- [REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md](/Users/sn5/Asurada/asurada-core/REALTIME_VOICE_AND_MODEL_ARCHITECTURE_CN.md)

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

### `front_attack_commit_model`

主要功能：
- 在“存在攻击机会”的前提下，判断是否值得真正投入资源去超车

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

输出字段：
- `final_hud_action`
- `final_voice_action`
- `final_strategy_stack`
- `suppressed_actions`

推荐实现：
- 规则仲裁层

标签来源：
- 工程定义

评估指标：
- arbitration consistency
- suppression correctness

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

输入字段：
- `session_type`
- `timing_mode`
- `timing_support_level`
- `game_mode`
- `total_laps`

输出字段：
- `model_profile_id`
- `routing_mode`
- `feature_gate_flags`

推荐实现：
- 规则路由层

标签来源：
- session 分类文档
- 样本验证结果

评估指标：
- routing correctness

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

## P1 第一批核心模型

### `fuel_risk_model`

主要功能：
- 燃油风险评分和节奏压力判断

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
- top-3
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
- 攻防专题样本
- 后验损失标签

评估指标：
- MAE
- tactical cost correlation

是否进入实时主链：
- 是

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
- 多车回放标签

评估指标：
- MAE
- threat ranking accuracy

是否进入实时主链：
- 是

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

18. 实现 `confidence_model / uncertainty_layer`
19. 实现 `tactical_state_machine`
20. 接入 `strategy_arbiter_v2`
21. 接入 `fallback_policy`
22. 完成 dashboard 模型对比与回归

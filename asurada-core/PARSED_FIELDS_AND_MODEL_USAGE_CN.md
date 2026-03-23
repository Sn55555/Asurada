# 当前可解析字段与模型用途

## 文档用途

这份文档用于回答两个问题：

- 当前 Asurada Core 已经能从真实数据里解析出哪些字段
- 这些字段后续会进入哪些模型或分析链路

本文档面向阶段二前的工程梳理，因此优先使用“字段名 + 中文含义 + 模型用途”的方式说明。

配套文档：

- [PACKET_FIELD_COVERAGE.md](/Users/sn5/Asurada/asurada-core/PACKET_FIELD_COVERAGE.md)
- [STAGE2_MODEL_INPUT_SCHEMA.md](/Users/sn5/Asurada/asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md)
- [UNRESOLVED_PACKET_FIELDS.md](/Users/sn5/Asurada/asurada-core/UNRESOLVED_PACKET_FIELDS.md)

## 当前已支持的数据来源

当前主链已支持或已具备解析能力的数据类型包括：

- `Session`
- `LapData`
- `Participants`
- `CarSetups`
- `CarTelemetry`
- `CarStatus`
- `FinalClassification`
- `CarDamage`
- `SessionHistory`
- `TyreSets`
- `Motion`
- `MotionEx`
- `Event`
- `LapPositions`
- `LobbyInfo`
- `TimeTrial`

其中：

- 当前抓包主路径里稳定出现并已验证的是前 14 类
- `LobbyInfo`、`TimeTrial` 已具备解析支持，但受样本覆盖影响，验证程度与主链抓包不完全一致

## 一、帧级元信息 Frame Meta

这些字段用于标识一帧数据在整个回放或会话中的位置。

| 字段名 | 中文含义 |
| --- | --- |
| `session_uid` | 会话唯一标识 |
| `frame_identifier` | 当前会话帧编号 |
| `overall_frame_identifier` | 全局帧编号 |
| `source_timestamp_ms` | 抓包接收时间戳 |
| `session_time_s` | 游戏内会话时间 |
| `track` | 赛道名称 |
| `lap_number` | 当前圈数 |

主要进入：

- 时序预测模型
- 回放对齐模型
- 赛段切分与样本排序
- dashboard 与回归检查

## 二、会话与环境字段 Session

这些字段描述比赛或会话的大环境、规则和天气背景。

| 字段名 | 中文含义 |
| --- | --- |
| `weather` | 当前天气 |
| `safety_car` | 安全车状态 |
| `session_type` | 会话类型 |
| `total_laps` | 总圈数 |
| `track_length_m` | 赛道长度 |
| `track_temperature_c` | 赛道温度 |
| `air_temperature_c` | 空气温度 |
| `pit_speed_limit_kph` | 维修区限速 |
| `marshal_zones` | 黄旗/管制区段信息 |
| `num_weather_forecast_samples` | 天气预测样本数 |
| `weather_forecast_samples` | 天气预测样本 |
| `forecast_accuracy` | 天气预测精度标记 |
| `ai_difficulty` | AI 难度 |
| `season_link_identifier` | 赛季链路标识 |
| `weekend_link_identifier` | 赛周链路标识 |
| `session_link_identifier` | 会话链路标识 |
| `pit_stop_window_ideal_lap` | 理想进站圈 |
| `pit_stop_window_latest_lap` | 最晚进站圈 |
| `pit_stop_rejoin_position` | 预计回场名次 |
| `game_mode` | 游戏模式 |
| `rule_set` | 规则集 |
| `time_of_day_minutes` | 游戏内时间 |
| `session_length` | 会话长度配置 |
| `num_safety_car_periods` | 安全车次数 |
| `num_virtual_safety_car_periods` | VSC 次数 |
| `num_red_flag_periods` | 红旗次数 |
| `weekend_structure` | 赛周结构 |
| `sector2_lap_distance_start_m` | 第二计时段起点距离 |
| `sector3_lap_distance_start_m` | 第三计时段起点距离 |

辅助设置字段也已可用，包括：

- 转向辅助、刹车辅助、变速箱辅助
- 进站辅助、出站辅助、ERS/DRS 辅助
- 动态赛车线
- equal performance、flashback、surface、damage、collision、corner cutting、parc ferme 等规则项

主要进入：

- 会话上下文模型
- 天气趋势模型
- 策略环境模型
- 赛周/模式分类模型

## 三、圈与时序字段 LapData

这些字段描述当前圈、时差、进站与处罚状态。

| 字段名 | 中文含义 |
| --- | --- |
| `lap_distance_m` | 当前圈内距离 |
| `total_distance_m` | 总累计行驶距离 |
| `current_lap_time_ms` | 当前圈时间 |
| `last_lap_time_ms` | 上一圈时间 |
| `sector` | 当前计时段 |
| `sector1_time_ms` | 第一段时间 |
| `sector2_time_ms` | 第二段时间 |
| `delta_to_car_in_front_minutes` | 与前车时间差分钟部分 |
| `delta_to_car_in_front_ms` | 与前车时间差 |
| `delta_to_race_leader_minutes` | 与领跑者时间差分钟部分 |
| `delta_to_race_leader_ms` | 与领跑者时间差 |
| `delta_to_car_in_front_s` | 标准化前车秒差 |
| `delta_to_race_leader_s` | 标准化领跑秒差 |
| `timing_mode` | timing 解释模式 |
| `timing_support_level` | timing 可用等级 |
| `gap_source_ahead` | 前方 gap 来源 |
| `gap_source_behind` | 后方 gap 来源 |
| `gap_confidence_ahead` | 前方 gap 可信度 |
| `gap_confidence_behind` | 后方 gap 可信度 |
| `rival_gap_sources` | 对手 gap 来源列表 |
| `pit_status` | 进站状态 |
| `num_pit_stops` | 进站次数 |
| `penalties` | 处罚数值 |
| `total_warnings` | 总警告数 |
| `corner_cutting_warnings` | 切弯警告 |
| `driver_status` | 车手状态 |
| `result_status` | 成绩状态 |

全车阵列里还可用：

- 各车圈内距离
- 各车圈数
- 各车名次
- 各车计时段
- 各车进站状态

主要进入：

- 圈时与 timing 模型
- 比赛态势模型
- 进站窗口模型
- 攻防压力模型
- 排名/结果监督模型

## 四、车手与资源状态 Driver

这些字段描述玩家当前资源、控制输入和即时节奏。

| 字段名 | 中文含义 |
| --- | --- |
| `position` | 当前名次 |
| `gap_ahead_s` | 与前车秒差 |
| `gap_behind_s` | 与后车秒差 |
| `speed_kph` | 当前速度 |
| `throttle` | 油门开度 |
| `brake` | 刹车开度 |
| `steer` | 转向输入 |
| `gear` | 挡位 |
| `rpm` | 发动机转速 |
| `fuel_in_tank` | 剩余燃油 |
| `fuel_capacity` | 油箱容量 |
| `fuel_laps_remaining` | 剩余燃油可跑圈数 |
| `ers_store_energy` | ERS 储能 |
| `ers_pct` | ERS 百分比 |
| `ers_deploy_mode` | ERS 部署模式 |
| `drs_available` | DRS 是否可用 |
| `status_tags` | 当前动态标签 |

主要进入：

- 策略风险评分模型
- 策略动作排序模型
- 资源管理模型
- 节奏识别模型

## 五、轮胎与损伤字段 Tyre / Damage

这些字段描述轮胎状态、磨损和车辆损伤。

| 字段名 | 中文含义 |
| --- | --- |
| `tyre.compound` | 当前轮胎配方 |
| `tyre.age_laps` | 当前胎龄 |
| `tyre.wear_pct` | 当前平均磨损 |
| `tyres_wear_pct[4]` | 四轮磨损 |
| `tyres_damage_pct[4]` | 四轮损伤 |
| `tyre_blisters_pct[4]` | 四轮起泡 |
| `brakes_damage_pct[4]` | 四轮刹车损伤 |
| `wing_damage_pct` | 前翼/尾翼损伤 |
| `floor_damage_pct` | 地板损伤 |
| `diffuser_damage_pct` | 扩散器损伤 |
| `sidepod_damage_pct` | 侧箱损伤 |
| `gearbox_damage_pct` | 变速箱损伤 |
| `engine_damage_pct` | 发动机损伤 |
| `engine_components_damage_pct` | 动力单元各部件损伤 |
| `engine_blown` | 发动机爆缸 |
| `engine_seized` | 发动机抱死 |

主要进入：

- 胎耗预测模型
- 胎温/抓地退化模型
- 轮胎管理策略模型
- 损伤风险模型

## 六、姿态与全局运动字段 Motion

这些字段描述车辆姿态与全局运动方向。

| 字段名 | 中文含义 |
| --- | --- |
| `g_force_lateral` | 横向 G |
| `g_force_longitudinal` | 纵向 G |
| `g_force_vertical` | 垂向 G |
| `yaw` | 偏航角 |
| `pitch` | 俯仰角 |
| `roll` | 侧倾角 |
| `world_position_x` | 世界坐标 X |
| `world_position_y` | 世界坐标 Y |
| `world_position_z` | 世界坐标 Z |
| `world_forward_dir` | 车辆前向方向向量 |
| `world_right_dir` | 车辆右向方向向量 |

主要进入：

- 驾驶动态模型
- 姿态稳定性模型
- 赛道位置与姿态联动模型

## 七、细粒度底盘与轮胎动态字段 MotionEx

这些字段描述更细粒度的轮胎、底盘和车体局部动态。

| 字段名 | 中文含义 |
| --- | --- |
| `wheel_slip_ratio` | 四轮滑移率 |
| `wheel_slip_angle` | 四轮滑角 |
| `wheel_lat_force` | 四轮横向力 |
| `wheel_long_force` | 四轮纵向力 |
| `wheel_vert_force` | 四轮垂向力 |
| `local_velocity` | 车体坐标系速度 |
| `angular_velocity` | 角速度 |
| `angular_acceleration` | 角加速度 |
| `front_wheels_angle` | 前轮转角 |
| `front_aero_height` | 前部气动高度 |
| `rear_aero_height` | 后部气动高度 |
| `front_roll_angle` | 前部侧倾角 |
| `rear_roll_angle` | 后部侧倾角 |
| `chassis_yaw` | 车身偏航 |
| `chassis_pitch` | 车身俯仰 |
| `wheel_camber` | 四轮外倾角 |
| `wheel_camber_gain` | 四轮外倾增益 |
| `height_of_cog_above_ground` | 质心离地高度 |

主要进入：

- 驾驶质量评分模型
- 入弯/弯心/出弯质量模型
- 轮胎抓地与滑移模型
- 动态风险识别模型

## 八、赛道语义字段 Track Semantic

这些字段把原始遥测转换成赛道位置语义。

| 字段名 | 中文含义 |
| --- | --- |
| `track_zone` | 赛道功能区 |
| `track_segment` | 赛道具体分段名称 |
| `track_usage` | 当前分段用途标签 |

主要进入：

- 赛道上下文模型
- 策略排序模型
- 驾驶动态分段模型
- ERS/攻防位置模型

## 九、短窗口上下文字段 Context

这些字段由最近若干帧聚合得到，用于给模型提供趋势和局部阶段信息。

| 字段名 | 中文含义 |
| --- | --- |
| `recent_unstable_ratio` | 最近窗口不稳定占比 |
| `recent_front_overload_ratio` | 最近窗口前轴过载占比 |
| `driving_mode` | 当前驾驶模式 |
| `tyre_age_factor` | 胎龄因子 |
| `brake_phase_factor` | 刹车阶段因子 |
| `throttle_phase_factor` | 油门阶段因子 |
| `steering_phase_factor` | 转向阶段因子 |

主要进入：

- 风险评分模型
- 驾驶风格模型
- 趋势预测模型

## 十、对手字段 Rival Features

这些字段描述前后车和关键对手状态。

| 字段名 | 中文含义 |
| --- | --- |
| `name` | 对手名称 |
| `position` | 对手名次 |
| `lap` | 对手圈数 |
| `gap_ahead_s` | 对手前方差值 |
| `gap_behind_s` | 对手后方差值 |
| `gap_source` | 对手 gap 来源 |
| `gap_confidence` | 对手 gap 可信度 |
| `fuel_laps_remaining` | 对手燃油剩余圈数 |
| `ers_pct` | 对手 ERS 百分比 |
| `drs_available` | 对手 DRS 状态 |
| `speed_kph` | 对手速度 |
| `tyre.compound` | 对手轮胎配方 |
| `tyre.wear_pct` | 对手轮胎磨损 |
| `tyre.age_laps` | 对手胎龄 |

主要进入：

- 对手态势模型
- 攻防目标模型
- 进站判断模型
- 排名/策略博弈模型

## 十一、策略调试与监督字段 Strategy Debug

这些字段不是原始遥测，而是现有策略引擎已经给出的解释层和监督层信息。

| 字段名 | 中文含义 |
| --- | --- |
| `assessment` | 状态评估结果 |
| `risk_profile` | 风险评分结果 |
| `risk_explain` | 风险评分解释 |
| `usage_bias` | 赛道用途权重偏置 |
| `candidates` | 候选策略列表 |
| `messages` | 最终策略输出消息 |

主要进入：

- 策略监督学习模型
- 模型蒸馏
- 可解释性调试
- 规则与模型对齐分析

## 十二、联机上下文字段 Lobby / Multiplayer

这些字段主要面向多人联机与参与者状态。

| 字段名 | 中文含义 |
| --- | --- |
| `lobby_info.num_players` | 大厅人数 |
| `lobby_info.player` | 当前玩家大厅信息 |
| `lobby_info.active_players` | 活跃玩家列表 |
| `lobby_info.all_players` | 全部大厅玩家列表 |

每个大厅玩家还包括：

- `ai_controlled`: 是否 AI 控制
- `team_id`: 车队 ID
- `nationality`: 国籍
- `platform`: 平台
- `name`: 名称
- `car_number`: 车号
- `telemetry_setting`: 遥测开放设置
- `show_online_names`: 是否显示在线名称
- `tech_level`: 技术等级
- `ready_status`: 准备状态

主要进入：

- 联机参与者模型
- 真人/AI 区分模型
- 多人比赛数据清洗

## 十三、结果与历史字段 Result / History

这些字段适合做赛后标签、监督真值和结果建模。

### `SessionHistory`

| 字段名 | 中文含义 |
| --- | --- |
| `num_laps` | 历史圈数 |
| `num_tyre_stints` | 轮胎 stint 数量 |
| `best_lap_time_lap_num` | 最快圈对应圈号 |
| `best_sector1_lap_num` | 第一段最快圈号 |
| `best_sector2_lap_num` | 第二段最快圈号 |
| `best_sector3_lap_num` | 第三段最快圈号 |
| `lap_history_data` | 每圈历史数据 |
| `tyre_stints_history_data` | 每段轮胎 stint 历史 |

### `FinalClassification`

| 字段名 | 中文含义 |
| --- | --- |
| `position` | 最终名次 |
| `num_laps` | 完成圈数 |
| `grid_position` | 发车名次 |
| `points` | 获得积分 |
| `num_pit_stops` | 总进站次数 |
| `result_status` | 最终成绩状态 |
| `best_lap_time_ms` | 最快圈时间 |
| `total_race_time_s` | 总比赛时间 |

### `LapPositions`

| 字段名 | 中文含义 |
| --- | --- |
| `num_laps` | 名次矩阵圈数 |
| `lap_start` | 起始圈 |
| `player_lap_positions` | 玩家逐圈名次 |
| `lap_positions` | 全车逐圈名次矩阵 |

主要进入：

- 结果监督模型
- 排名变化模型
- 赛后复盘模型
- 训练标签生成

## 十四、事件字段 Event

当前已结构化支持的常见事件包括：

- `BUTN`
- `FTLP`
- `PENA`
- `OVTK`
- `STLG`
- `LGOT`
- `SSTA`
- `SEND`
- `SPTP`
- `COLL`
- `DRSE`
- `CHQF`
- `RCWN`
- `RTMT`

主要进入：

- 比赛过程事件模型
- 风险事件识别模型
- 策略触发标签生成
- 比赛阶段切分

## 十五、这些字段会进入哪些模型

按模型方向归纳如下。

### 1. 会话上下文模型

使用字段：

- `Session` 全组字段
- `Frame Meta`

用途：

- 识别会话模式
- 识别赛周结构
- 建模天气和规则背景
- 给策略模型提供环境上下文

### 2. 圈时与 timing 模型

使用字段：

- `LapData`
- `Frame Meta`
- `Rival`

用途：

- 计算节奏变化
- 学习前后车 timing 关系
- 学习进站窗口和圈段差值

### 3. 策略风险评分模型

使用字段：

- `Session`
- `LapData`
- `Driver`
- `Tyre/Damage`
- `Context`
- `Track Semantic`

用途：

- 输出燃油风险
- 输出轮胎风险
- 输出 ERS 风险
- 输出赛道管制风险
- 输出攻防机会

### 4. 策略动作排序/仲裁模型

使用字段：

- `Driver`
- `Rival`
- `Track Semantic`
- `Strategy Debug`

用途：

- 选择当前最值得播报或执行的策略动作
- 对齐规则引擎与后续模型输出

### 5. 驾驶动态模型

使用字段：

- `Motion`
- `MotionEx`
- `Context`
- `Track Semantic`

用途：

- 识别姿态不稳
- 识别前轴过载
- 识别入弯/弯心/出弯质量
- 形成驾驶风格标签

### 6. 轮胎退化与抓地模型

使用字段：

- `Tyre / Damage`
- `MotionEx`
- `Track Semantic`
- `Context`

用途：

- 预测胎耗
- 预测抓地下降
- 识别高负荷区的轮胎风险

### 7. 对手态势模型

使用字段：

- `Rival`
- `LapData`
- `Driver`
- `Event`

用途：

- 识别攻击目标
- 识别防守压力源
- 识别潜在进站对手
- 识别对手节奏和资源状态

### 8. 比赛事件模型

使用字段：

- `Event`
- `Session`
- `LapData`

用途：

- 识别起步、处罚、碰撞、超车、最快圈、冠军事件
- 给策略和标签系统提供比赛过程节点

### 9. 联机参与者模型

使用字段：

- `LobbyInfo`
- `Participants`

用途：

- 区分真人和 AI
- 管理联机参与结构
- 过滤不适合训练的对象

### 10. 赛后结果与标签模型

使用字段：

- `FinalClassification`
- `SessionHistory`
- `LapPositions`

用途：

- 生成监督学习标签
- 建立名次变化与结果模型
- 做赛后复盘与结果对齐

## 十六、当前最适合直接喂模型的字段

当前已经适合直接进入阶段二特征工程的字段包括：

- 会话温度和天气预测
- 圈进度与圈段时间
- 燃油与 ERS
- 轮胎磨损与损伤
- 高价值 Motion / MotionEx 字段
- 赛道语义字段
- 短窗口上下文字段
- `risk_profile`
- `risk_explain`
- `usage_bias`

## 十七、当前需要谨慎使用的字段

以下字段当前不是不能用，而是必须结合来源和可信度使用：

- `delta_to_car_in_front_ms`
- `delta_to_race_leader_ms`
- `gap_ahead_s`
- `gap_behind_s`

原因：

- 这些 timing 字段已经具备：
  - `timing_mode`
  - `timing_support_level`
  - `gap_source_*`
  - `gap_confidence_*`
- 但它们仍然属于分会话类型逐步收口的字段
- 当前 `session_type 15 / 16` 已有高质量验证
- `8 / 13` 仍属于项目内稳定命名，但并非官方最终定名

建议：

- 训练时优先使用 `official_preferred + high`
- `medium` 作为上下文辅助特征
- `low` 作为弱特征或遮罩特征
- `none` 不进入 timing 监督任务

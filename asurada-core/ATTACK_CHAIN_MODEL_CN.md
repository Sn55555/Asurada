# Asurada 进攻链模型整理

## 1. 目标

这份文档只回答一个问题：

- `ATTACK_WINDOW / attack_opportunity / front_attack_commit / counterattack` 这条链，应该按什么赛车逻辑优化。

范围限定为：

- F1 比赛中常见的**赛道上超车进攻方式**
- 每种方式的**触发条件**
- 每种方式对**弯道类型/赛道区段**的适应性
- 如何映射到 Asurada 现有代码结构

不覆盖：

- 进站 undercut / overcut 这类纯策略超车
- 防守链的完整设计
- 纯驾驶训练建议

## 2. 当前代码里的进攻链落点

当前主链已经有这些入口：

- `assessment.attack_state`
- `risk_profile.attack_opportunity`
- `StrategyCandidate(code="ATTACK_WINDOW")`
- `front_attack_commit_model`
- `TacticalStateMachine`
  - `attack_prepare`
  - `counterattack_prepare`
  - `counterattack_active`

对应文件：

- [/Users/sn5/Asurada/asurada-core/src/asurada/strategy.py](/Users/sn5/Asurada/asurada-core/src/asurada/strategy.py)
- [/Users/sn5/Asurada/asurada-core/src/asurada/state_machine.py](/Users/sn5/Asurada/asurada-core/src/asurada/state_machine.py)
- [/Users/sn5/Asurada/asurada-core/src/asurada/models.py](/Users/sn5/Asurada/asurada-core/src/asurada/models.py)

当前问题不是“没有进攻链”，而是：

- 现在的 `ATTACK_WINDOW` 更像**单一窗口分数**
- 还没有把“哪一种进攻方式成立”拆开
- 也没有把“当前弯道是否适合这种进攻”明确建模

## 3. F1 常见超车进攻方式

建议按 7 类建模，并显式拆成两层：

- `setup / approach`
- `commit / execute`

这样可以避免把“正在铺垫机会”和“正在兑现机会”混成一个窗口分数。

### 3.1 `drs_tow`

定义：

- 在前一弯出口贴近
- 借尾流、DRS、ERS 在直道上建立闭合速度
- 为后续刹车点并排或内线超车做铺垫

这类是 F1 里最常见的默认进攻铺垫方式。

### 3.2 `pressure_build`

定义：

- 当前圈不一定已具备直接超车条件
- 通过持续贴近、试探不同线路、把自己留在对手后视镜里，制造下一拍失误或迫使对手牺牲出口

这类应被视为 `attack_prepare`，而不是直接 `commit`。

### 3.3 `inside_outbrake`

定义：

- 在直道上完成接近
- 进入重刹区后拿内线，靠更晚但仍受控的制动把车身先放进去

这是最标准、最常见的执行型超车方式。

### 3.4 `late_braking_lunge`

定义：

- 比常规内线抢刹更激进
- 通常从更靠后的位置突然晚刹去抢 apex

这类与 `inside_outbrake` 不应混在一起，因为风险和 commit 门槛都更高。

### 3.5 `outside_carry`

定义：

- 利用更高的入弯/中弯速度把车留在外线
- 依靠更高 minimum speed 在弯心后仍保持足够重叠

这类是低频方式，但在宽入口、开放式中速弯确实存在。

### 3.6 `switchback`

定义：

- 当前车明显 cover inside
- 攻击车故意不硬拼 apex，而是做更好的弯中姿态和更早的扶正给油
- 在弯后或下一小直道完成 over-under / 交叉线反切

这类本质是“利用对手守内线而牺牲出口”。

### 3.7 `traction_pass`

定义：

- 不一定在刹车点动手
- 通过更好的出口姿态、更早的全油和更高的直道初速度完成兑现

这类和 `switchback` 相近，但应单列，因为它可以在没有明显 over-under 路线切换时单独成立。

## 4. 方式对应的触发条件

建议把进攻链拆成两层：

1. **方式成立性**
- 现在更适合哪一种 `setup` 或 `commit` 方式

2. **兑现条件**
- 这圈/这段是否值得真的 `commit`

### 4.1 `drs_tow` 触发条件

应重点看：

- `gap_ahead_s` 已进入直接攻击距离
- `player.drs_available = true`
- 当前区段是 `deployment_straight -> braking_entry`
- 直线闭合速度足够
- 本车姿态稳定，不能处于 `dynamics_unstable`
- 后车压力不能高到一旦失败就立刻丢位

这类是 `setup` 首选，不应和 `inside_outbrake` 合并。

### 4.2 `pressure_build` 触发条件

应重点看：

- 还没达到直接 pass 条件
- 但前车在关键弯容错低
- 本车能持续贴近，不被 dirty air 彻底破坏节奏
- 下一关键弯或下一段直道可兑现

这类应拉高 `attack_setup_score`，但不直接拉高 `front_attack_commit_score`。

### 4.3 `inside_outbrake` 触发条件

应重点看：

- 当前区段是 `braking_entry`
- 已经建立足够接近或重叠
- 赛道入口宽度和弯道容错允许拿内线
- 本车制动稳定，且能在赛道内完成动作

### 4.4 `late_braking_lunge` 触发条件

应重点看：

- 当前区段是超重刹低速弯
- 本车制动峰值能力强
- 轮胎/温度/制动稳定性更好
- 刹车区不是明显颠簸、下坡或高锁死风险场景

这类应该要求更高 commit 门槛，因为失败代价大、合规边界也更窄。

### 4.5 `outside_carry` 触发条件

应重点看：

- 入口/中段足够宽，允许双线路并行
- 外线不会直接掉进脏路或出口收口
- 本车中高速 grip 优势明显
- 前车守内线已牺牲中弯或出口速度

### 4.6 `switchback` 触发条件

应重点看：

- 当前区段是 `exit_traction`
- `exit_traction_model` 分数高
- 前车当前防守线会牺牲出弯
- 下一段有足够直道长度兑现
- 本车 ERS 还有足够部署余量

这类不一定要求当前弯就完成超车，但要求下一段兑现概率高。

### 4.7 `traction_pass` 触发条件

应重点看：

- 当前区段是 `exit_traction`
- 当前弯出口速度和姿态比前车更好
- 弯后直道或下一短冲刺段足够长
- 本车牵引、后轴 grip、ERS 兑现能力更好

这类和 `switchback` 区别在于：它可以不依赖明显的 over-under 路线变化。

## 5. 弯道适应性模型

优化进攻链时，不应该只看 gap 和 DRS，还要看**弯道适配性**。

建议把弯道分成 5 类。

### 5.1 `heavy_braking_hairpin_or_chicane`

代表：

- 发卡
- 长直道后的大减速弯
- 终点线后 T1

适配：

- `inside_outbrake`
- `late_braking_lunge`

不适配：

- `outside_carry`

### 5.2 `medium_speed_single_apex`

代表：

- 中低速 90 度弯
- 单 apex 低速出口弯

适配：

- `switchback`
- 条件好时可 `inside_outbrake`

### 5.3 `long_exit_to_straight`

代表：

- 长出弯接长直道
- “关键不是入弯，而是出口”的 corner pair

适配：

- `switchback`
- `traction_pass`

这类对 F1 特别重要，因为很多超车不是在弯里完成，而是在**前一个关键出口决定成败**。

### 5.4 `high_speed_sweeper`

代表：

- 高速长弯
- 大负载 sweepers

适配：

- 只适合 `outside_carry`
- 而且门槛必须很高

不适配：

- 常规 `late_braking_lunge`
- 直接内线强攻

### 5.5 `sequence_or_s_bend`

代表：

- 连续变向
- S 弯
- 需要为后一个弯位做准备的组合弯

适配：

- `pressure_build`
- `switchback` 的 setup

不适合直接做：

- 单点式 `late_braking_lunge`

## 6. 和现有 `track_zone / track_usage` 的映射

你当前代码里已有：

- `track_zone`
  - `deployment_straight`
  - `braking_entry`
  - `apex_rotation`
  - `exit_traction`
  - `high_load_management`

这是对的，但还不够表达“哪种超车方式更合适”。

建议增加一层内部标签：

- `attack_style_hint`
- `corner_overtake_class`

建议映射如下：

| 当前区段 | 建议 attack style |
| --- | --- |
| `deployment_straight` | `drs_tow` / `pressure_build` |
| `braking_entry` | `inside_outbrake` / `late_braking_lunge` |
| `exit_traction` | `switchback` / `traction_pass` |
| `apex_rotation` | `outside_carry` |
| `high_load_management` | `no_direct_attack` |

这层不要直接暴露成最终 action code，而是作为：

- `attack_opportunity_model`
- `front_attack_commit_model`
- `state_machine`

的输入特征。

## 7. 推荐的进攻链拆法

建议把当前进攻链收成 4 个连续分数，而不是只押一个 `attack_opportunity`。

### 7.1 `attack_setup_score`

问题定义：

- 当前是不是在搭一个有效的超车前置窗口

应包含：

- 前车差距
- DRS 可用性
- 直线前出口质量
- 当前弯道类型
- dirty-air 下跟车可持续性

### 7.2 `attack_method_logits`

问题定义：

- 当前更适合哪一种方式

输出候选：

- `drs_tow`
- `pressure_build`
- `inside_outbrake`
- `late_braking_lunge`
- `outside_carry`
- `switchback`
- `traction_pass`

这一步是现在代码里最缺的。

### 7.3 `front_attack_commit_score`

问题定义：

- 当前这圈/这段是否值得真正发起

应包含：

- `attack_setup_score`
- 最优 `attack_method`
- 当前姿态稳定性
- 后车压力
- 轮胎/ERS 消耗代价
- 若失败时的丢位风险

### 7.4 `counterattack_window_score`

问题定义：

- 刚丢位置后，是否存在立刻回攻窗口

这条线当前在代码里已经有雏形，但样本和标签不足。

## 8. 对现有 action / state machine 的建议

### 8.1 `ATTACK_WINDOW` 不要再是“单一进攻窗口”

建议变成：

- `ATTACK_WINDOW`
  - 仍然是用户可见 action code
- 但 debug 内部必须带：
  - `attack_method`
  - `attack_setup_score`
  - `attack_commit_score`
  - `counterattack_risk`
  - `rear_threat_tradeoff`

### 8.2 `attack_prepare` 和 `counterattack_prepare` 要分开

现在状态机里两者都落到 `ATTACK_WINDOW`，这在对外 action 上可以接受，但内部逻辑不能混。

建议：

- `attack_prepare`
  - 正常进攻搭建
- `counterattack_prepare`
  - 丢位后回攻

这两者的 commit 条件不同：

- `counterattack_prepare` 允许更短时、更激进
- `attack_prepare` 应该更重视资源与后车风险

### 8.3 `why_not_attack` 的解释应引用方式失败原因

当前很多“为什么不进攻”还是 gap/DRS 的笼统说明。

建议解释层直接给出：

- 当前最优方式：`switchback`
- 未 commit 原因：
  - `exit_traction` 不足
  - 后车压力过高
  - 当前弯是 `high_load_management`
  - 失败后反制风险大

## 9. 建议新增的特征

当前若要把进攻链继续做对，建议补这些特征。

### 9.1 必补

- `closing_speed_estimate`
- `relative_top_speed_delta`
- `ers_attack_budget_now`
- `attack_method_hint`
- `corner_overtake_class`
- `straight_after_corner_length_class`
- `defender_cover_inside_likelihood`
- `commit_failure_position_loss_est`

### 9.2 建议补

- `overlap_probability_at_apex`
- `dirty_air_followability_score`
- `exit_line_advantage_score`
- `braking_stability_under_attack`

## 10. 上海赛道的直接映射

上海应围绕一条非常明确的主攻击链来建模：

- `T13` 出口：主攻击 setup
- 后直道：主部署区
- `T14`：主 commit 点
- `T6`：次级 commit 点

当前区段落法应是：

- `T13 Primary Attack Setup`
  - `zone_type = exit_traction`
  - `usage = overtake_setup`
- `Back Straight Primary Deploy`
  - `zone_type = deployment_straight`
  - `usage = primary_overtake_deploy`
- `T14 Primary Overtake Commit`
  - `zone_type = deployment_straight`
  - `usage = brake_marker_commit`
- `T6 Secondary Attack Setup`
  - `zone_type = deployment_straight`
  - `usage = overtake_setup`
- `T6 Braking`
  - `zone_type = braking_entry`
  - `usage = late_brake_control`

同时应把 `T11` 从“攻击 build”降级为更偏部署/能量准备的普通过渡段，不再给它过强攻击先验。

## 11. 最值得先做的实现顺序

### 第一步

把当前单一 `attack_opportunity` 拆成：

- `attack_setup_score`
- `attack_method_hint`

先不改 action code。

### 第二步

让 `front_attack_commit_model` 显式读取：

- `attack_method_hint`
- `corner_overtake_class`
- `rear_threat`
- `defence_cost`

### 第三步

重写 `ATTACK_WINDOW` 的 debug payload，至少输出：

- `method`
- `setup_score`
- `commit_score`
- `rear_tradeoff`
- `failure_risk`

### 第四步

再重启：

- `yield_vs_defend_model`
- `counterattack_window_model`

否则会在错误的输入空间上继续训练。

## 12. 对当前代码的直接结论

当前 Asurada 的进攻链已经具备：

- 进攻机会识别
- 进攻 commit baseline
- 基础攻防状态机

但它还缺最关键的一层：

- **“当前是哪一种超车方式成立”**

如果不补这层，后面无论是：

- `front_attack_commit_model`
- `yield_vs_defend_model`
- `counterattack_window_model`

都会继续在“窗口有/没有”的粗粒度空间里打转，难以真正优化。

## 13. 资料依据

外部依据主要来自以下几类公开材料：

- FIA 当前 F1 赛事法规（DRS 与赛道行为边界）
  - [2025 Formula One Sporting Regulations](https://www.fia.com/sites/default/files/fia_2025_formula_1_sporting_regulations_-_issue_1_-_2024-07-31.pdf)
- FIA 驾驶标准指南
  - [Formula 1 Driving Standards Guidelines PDF](https://www.fia.com/sites/default/files/doc_2_-_2025_formula_1_driving_standard_guidelines.pdf)
- F1 官方对 DRS 与超车的说明
  - [F1 Explains: How DRS works](https://www.formula1.com/en/latest/article/f1-explains-how-drs-works-why-it-was-introduced-and-what-is-the-best-way-to.6Pfv07lvZNfTvqrXpxgVV7)
- F1 车手/赛道层面对“关键出口弯决定超车”的说明
  - [F1 drivers say Miami Turn 7/11 sequence is key for overtaking](https://www.motorsport.com/f1/news/fake-marina-corner-key-miami-track/10296440/)
  - [Shanghai’s long back straight and hairpin create a major overtaking zone](https://www.formula1.com/en/latest/article/chinas-f1-circuit-turn-by-turn-guide-where-will-the-best-overtaking.42fdaD0rQ6ek4Hf3fwmtvy)
- 通用赛道驾驶技术参考
  - [Driver61 track driving techniques and overtaking fundamentals](https://driver61.com/uni/racing-line/)

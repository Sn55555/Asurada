# Session Type Classification

## 文档用途

这份文档记录当前抓包里已经出现的非 `Time Trial` `session_type` 编码、项目内稳定命名、证据来源和置信度。

文档目标不是复刻官方枚举名，而是为项目内解析、调试和阶段二样本管理提供稳定语义。

## 当前稳定归类

### `session_type = 13`

- 项目内命名：`QualifyingLike(13)`
- 置信度：`medium`
- 归类原则：
  - 这是一个有最终排名、无积分的竞争性短会话
  - 当前抓包里 `total_laps = 1`
  - 玩家最终结果为 `P8 / 0 points`
- 证据：
  - 存在 `FinalClassification`
  - 存在大量 `OVTK / SPTP / FTLP`
  - 不表现出稳定的 race-points 结果结构
- 当前用途：
  - 归入 `qualifying_like`
  - 可用于阶段二的排位类样本

### `session_type = 8`

- 项目内命名：`ShortResultLike(8)`
- 置信度：`medium`
- 归类原则：
  - 这是一个短竞争会话，存在排名和积分结果
  - 当前抓包里 `total_laps = 1`
  - 玩家最终结果为 `P1 / 7 points`
- 证据：
  - 存在 `FinalClassification`
  - 存在 `SSTA / SEND / FTLP / OVTK / SPTP`
  - 结果上呈现短会话且非标准 25 分正赛积分
- 当前用途：
  - 归入短结果类会话
  - 作为阶段二“短竞争结果样本”保留

### `session_type = 15`

- 项目内命名：`SprintRaceLike(15)`
- 置信度：`high`
- 归类原则：
  - 这是一个短距离 race-like 会话
  - 当前抓包里 `total_laps = 3`
  - 玩家最终结果为 `P2 / 7 points`
- 证据：
  - 存在 `SSTA / STLG / SEND / RCWN`
  - 存在 `FinalClassification`
  - `gap_source_ahead = official_lapdata_adjacent` 大量出现
  - `gap_source_behind = official_lapdata_adjacent` 大量出现
- 当前用途：
  - 归入 `race_like`
  - timing 支持等级为 `official_preferred`
  - 可直接作为阶段二 sprint-race 样本

### `session_type = 16`

- 项目内命名：`FeatureRaceLike(16)`
- 置信度：`high`
- 归类原则：
  - 这是一个完整的 race-like 会话
  - 当前抓包里 `total_laps = 5`
  - 玩家最终结果为 `P1 / 25 points`
- 证据：
  - 存在 `SSTA / STLG / SEND`
  - 存在 `FinalClassification`
  - `gap_source_behind = official_lapdata_adjacent` 大量出现
  - 结果积分与标准大奖赛胜利积分强一致
- 当前用途：
  - 归入 `race_like`
  - timing 支持等级为 `official_preferred`
  - 可直接作为阶段二 feature-race 样本

## 当前规则落地

对应实现见：

- [packet_snapshot.py](/Users/sn5/Asurada/asurada-core/src/asurada/packet_snapshot.py)

当前项目内时序归类规则：

- `1 -> time_trial_disabled`
- `5 / 13 -> qualifying_like`
- `10 / 15 / 16 -> race_like`
- 其他未明确编码 -> `session_type_estimated`

当前项目内 timing 支持等级规则：

- `1 -> disabled`
- `5 / 10 / 13 / 15 / 16 -> official_preferred`
- 其他未明确编码 -> `estimated_only`

## 阶段二样本入口

已按这些归类从大抓包切出独立样本，见：

- [data/capture_samples/shanghai_race_weekend](/Users/sn5/Asurada/asurada-core/data/capture_samples/shanghai_race_weekend)

样本 metadata 见：

- [metadata.json](/Users/sn5/Asurada/asurada-core/data/capture_samples/shanghai_race_weekend/metadata.json)

## 仍待收口

- `session_type = 8` 的官方语义仍未最终确认
- `session_type = 13` 的官方语义仍未最终确认
- 若后续拿到更多赛周样本，需要继续比对会话长度、积分结构、UI 场景和事件模式

# 阶段二调试看板

> 这是一个适合 GitHub 展示的阶段二静态调试看板。  
> 目标是把当前模型基线、主链接入状态和停滞项，以图表方式直接展示在仓库里。  
> 详细状态仍以 [STATUS.md](STATUS.md) 和 [PHASE2_MODEL_MATRIX_CN.md](PHASE2_MODEL_MATRIX_CN.md) 为准。

## 当前状态总览

![Baselines](https://img.shields.io/badge/Available%20Baselines-4-2ea44f?style=for-the-badge)
![Paused](https://img.shields.io/badge/Paused-2-f59e0b?style=for-the-badge)
![Not%20Started](https://img.shields.io/badge/Not%20Started-14-9ca3af?style=for-the-badge)
![Arbiter](https://img.shields.io/badge/Arbiter%20V2-Mainline%20Connected-2563eb?style=for-the-badge)

```mermaid
pie title 阶段二模型状态分布
    "已可用 baseline" : 4
    "暂停" : 2
    "未开始" : 14
```

## 当前主链

```mermaid
flowchart LR
    A["真实抓包回放"] --> B["标准化状态 / 特征导出"]
    B --> C["rear_threat_model"]
    B --> D["attack_opportunity_model"]
    B --> E["front_attack_commit_model"]
    B --> F["strategy_action_model"]
    F --> G["top-k candidates"]
    G --> H["strategy_arbiter_v2"]
    H --> I["final messages"]
    H --> J["debug payload / dashboard"]
```

## 已可用 baseline

| 模型 | 当前状态 | 说明 |
| --- | --- | --- |
| `rear_threat_model` | 可用 | 后车威胁识别第一版已成立 |
| `attack_opportunity_model` | 可用 | 已具备 exported `val/test` |
| `front_attack_commit_model` | 可接受 | 已具备 exported `val/test`，后续仍需继续收紧标签 |
| `strategy_action_model` | 可用 | 当前更适合作为 `top-k` 候选提供器 |

```mermaid
xychart-beta
    title "阶段二可用 baseline 数量"
    x-axis ["Available", "Paused", "Not Started"]
    y-axis "Count" 0 --> 16
    bar [4, 2, 14]
```

## 基线指标

### `rear_threat_model`

- `accuracy = 97.99%`
- `positive precision = 100.00%`
- `positive recall = 81.82%`

### `attack_opportunity_model`

- `accuracy = 99.94%`
- `positive precision = 100.00%`
- `positive recall = 79.31%`

### `front_attack_commit_model`

- `accuracy = 99.96%`
- `positive precision = 76.47%`
- `positive recall = 100.00%`

### `strategy_action_model`

- `top1_accuracy = 70.52%`
- `top2_accuracy = 99.98%`
- 当前覆盖动作：
  - `NONE`
  - `LOW_FUEL`
  - `DEFEND_WINDOW`
  - `DYNAMICS_UNSTABLE`

```mermaid
xychart-beta
    title "基线精度 / 召回（百分比）"
    x-axis ["rear_threat P", "rear_threat R", "attack_opportunity P", "attack_opportunity R", "front_attack_commit P", "front_attack_commit R"]
    y-axis "Percent" 0 --> 100
    bar [100, 82, 100, 79, 76, 100]
```

```mermaid
xychart-beta
    title "strategy_action_model Top-K 命中率"
    x-axis ["Top-1", "Top-2"]
    y-axis "Percent" 0 --> 100
    bar [71, 100]
```

## 当前停滞项

| 模型 | 当前状态 | 停滞原因 |
| --- | --- | --- |
| `yield_vs_defend_model` | 暂停 | 后验标签和攻防专题样本仍不稳定 |
| `event_impact_model` | 暂停 | 事件样本量不足，收紧后又过小，无法稳定泛化 |

```mermaid
flowchart TB
    A["yield_vs_defend_model"] --> B["后验标签不稳定"]
    A --> C["攻防样本覆盖不足"]
    D["event_impact_model"] --> E["事件样本过少"]
    D --> F["跨 session 泛化失败"]
```

## 已接入主链的控制模块

### `strategy_arbiter_v2`

- 已真实消费 `strategy_action_model top-k`
- 已接管最终 `messages` 排序
- 已加入 priority 校准
- 已接入自动回归断言：
  - `priority_floor_calibrated`
  - `cooldown_suppresses_last_action`
  - `duplicate_codes_deduped`

```mermaid
flowchart LR
    A["rule_candidates"] --> D["strategy_arbiter_v2"]
    B["model_candidates"] --> D
    C["tactical_context / fallback / confidence"] --> D
    D --> E["HUD action"]
    D --> F["Voice action"]
    D --> G["Final strategy stack"]
```

## 待开发项

### 上游基础模型

- `fuel_risk_model`
- `ers_risk_model`
- `tyre_risk_model`
- `dynamics_risk_model`
- `defence_cost_model`

### 攻防与对手模型

- `counterattack_window_model`
- `rival_pressure_model`

### 驾驶质量模型

- `entry_quality_model`
- `apex_quality_model`
- `exit_traction_model`

### 趋势与长期模型

- `tyre_degradation_trend_model`
- `short_horizon_risk_forecast_model`
- `driver_style_model`
- `pit_rejoin_traffic_model`

## 下一步建议

```mermaid
flowchart LR
    A["基础风险模型"] --> B["counterattack_window_model"]
    B --> C["confidence_model / uncertainty_layer"]
    C --> D["更完整的主链战术控制"]
```

当前最合理的顺序：

1. 补 `fuel / ers / tyre / dynamics` 风险模型
2. 再补 `counterattack_window_model`
3. 再实现 `confidence_model / uncertainty_layer`

## 参考文档

- [STATUS.md](STATUS.md)
- [PHASE2_MODEL_MATRIX_CN.md](PHASE2_MODEL_MATRIX_CN.md)
- [training/README.md](training/README.md)

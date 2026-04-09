# 阶段三 LLM Sidecar 路由规则

## 文档范围

本文档只回答一个问题：

**什么时候可以把“core 无法回答”的语音问题转给 LLM sidecar，什么时候绝对不行。**

本文档是 [STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md](STAGE3_LLM_EXPLAINER_BOUNDARY_CN.md) 的执行细化版。

不在本文档范围内：

- 具体选哪家 LLM
- prompt 细节
- 语音克隆 / TTS 音色
- 设备部署细节

---

## 一、总原则

路由优先级固定为：

1. `control`
2. `structured`
3. `explainer`
4. `reject`

也就是说：

- 先判定是不是控制命令
- 再判定 core 是否能稳定结构化回答
- 只有前两层都不能稳定处理，且属于允许解释域时，才考虑 LLM sidecar
- 其它情况一律拒绝或要求澄清

LLM sidecar 不是兜底垃圾桶。  
它只接：

- 可解释的问题
- 可总结的问题
- 可追问的问题

它不接：

- 控制命令
- 高频状态查询
- 未接入数据域上的自由猜测

### 当前实现进度

当前仓库里，这套路由已经实际存在，不再只是建议：

- `control`
- `structured`
- `explainer`
- `companion`
- `reject`

已落地行为：

- 比赛中：
  - 高频确定性问题继续走 `structured`
  - 解释类问题可走 `explainer`
- 非比赛中：
  - 非控制类问题转为 `companion`
  - companion 优先尝试 LLM sidecar
  - 若首次超时，会用放宽时限重试一次

当前边界仍然保留：

- control 不走 LLM
- structured 不让 LLM 抢占
- partial transcript 目前只做预览、唤醒兜底和 route fallback，不做提前执行

---

## 二、“core 无法回答”必须拆成四类

不能用一个布尔值表示“答不了”。  
至少要拆成下面四类：

### 1. `unrecognized`

含义：

- transcript 太差
- 意图不清
- 语义归类失败

例子：

- `后面那个...那个...现在那个情况`

处理：

- 不进 LLM
- 返回 `needs_clarification` 或 `please_repeat`

原因：

- 如果语音本身都没识别清楚，把脏 transcript 交给 LLM 只会放大错误

### 2. `unsupported_but_explainable`

含义：

- 结构化主路径没有现成 query kind
- 但问题属于允许解释域

例子：

- `整体形势怎么样`
- `为什么刚才不让我进攻`
- `现在最优先该做什么`

处理：

- 允许进入 LLM sidecar

### 3. `supported_but_not_enough_state`

含义：

- 问题类型在能力范围内
- 但当前状态数据不足以给可信答案

例子：

- 当前没有稳定的降雨趋势数据，却问：
  - `后面会不会下雨`

处理：

- 不进 LLM 硬猜
- 返回 `unsupported`
- 可附最近似状态说明

### 4. `disallowed_domain`

含义：

- 问题触碰禁止域

例子：

- `现在直接让我进站`
- `把防守改成进攻`
- `帮我决定这圈怎么开`

处理：

- 永不进 LLM
- 明确拒绝或转成结构化说明

---

## 三、路由决策表

| 条件 | 路由 | 备注 |
| --- | --- | --- |
| 命中控制命令 | `control` | 永不进 LLM |
| 命中结构化 query，且状态足够 | `structured` | core 直接回答 |
| 命中结构化 query，但状态不足 | `reject` | 返回 `unsupported` |
| 未命中结构化，但属于允许解释域 | `explainer` | 可进 LLM sidecar |
| transcript 质量差 / 语义不清 | `reject` | 返回 `needs_clarification` |
| 涉及禁止域 | `reject` | 永不进 LLM |

推荐伪代码：

```python
if is_control(turn):
    return "control"

structured = try_structured_route(turn)
if structured.status == "answerable":
    return "structured"
if structured.status == "not_enough_state":
    return "reject"

if transcript_quality_low(turn):
    return "reject"

if not capability_registry.is_explainer_allowed(turn):
    return "reject"

return "explainer"
```

---

## 四、允许转 LLM 的问题域

当前推荐允许的 explainer 域如下。

### A. 当前策略解释

- 为什么现在偏向防守
- 为什么现在不进攻
- 为什么当前策略是这样
- 为什么现在没有进站

### B. 全局总结

- 整体形势怎么样
- 现在最优先该做什么
- 当前最大风险是什么
- 这几圈主要关注什么

### C. 条件性追问

- 如果等一圈再进站会怎样
- 如果继续不进站会怎样
- 如果我现在守住会怎样
- 这个风险多久会变严重

### D. 结构化域的自然语言重述

- `后面那个是不是已经贴上来了`
- `这胎还能不能再撑一会`

注意：

- 这类优先尝试回归到 structured lane
- 只有无法稳定归一化时，才交给 explainer lane

---

## 五、禁止转 LLM 的问题域

### 1. 控制命令

- 停止
- 取消
- 重复
- 安静点
- 详细一点

### 2. 高频确定性状态查询

- 后车差距
- 前车差距
- 当前 DRS
- 当前 ERS
- 当前轮胎状态
- 当前天气
- 当前处罚
- 当前车损

这些问题已有 core 能力，交给 LLM 只会增加延迟和不确定性。

### 3. 直接策略执行请求

- 现在直接进站
- 帮我改成进攻
- 这圈让我守到底

这类请求不能由 LLM 决定。

### 4. 未接入数据域的推演

- 当前没有稳定状态支持，却问：
  - `最后能不能上领奖台`
  - `五圈后会不会出安全车`

这类问题必须拒绝或降级。

---

## 六、必须新增的判定输出

为了支撑上述路由，structured 路径本身要能返回原因，不是只返回“有/无命中”。

建议统一成：

```python
{
  "status": "answerable | not_enough_state | unsupported | unrecognized",
  "query_kind": "...",
  "reason": "...",
  "confidence": 0.0
}
```

推荐 reason 枚举：

- `matched_structured_query`
- `matched_but_missing_state`
- `semantic_unrecognized`
- `disallowed_domain`
- `explainer_candidate`

这样 `transcript_router` 才能清楚知道是否应转 LLM。

---

## 七、LLM sidecar 调用前必须做什么

在真正调用 LLM 前，必须再过三道检查。

### 1. Capability Check

检查：

- 当前问题是否在 `explainer_allowlist`
- 是否触碰 `denylist`

### 2. State Sufficiency Check

检查：

- 当前摘要是否足够支持这个问题
- 如果不够，直接 `unsupported`

### 3. Latency Budget Check

检查：

- 当前设备 / 配置是否允许走 sidecar
- 如果超预算，直接走规则化 fallback

---

## 八、LLM sidecar 输出后的处理

LLM sidecar 返回后，不能直接播。

必须先经过：

1. schema 校验
2. 安全状态检查
3. 置信度下限判断
4. 输出长度裁剪

建议最小规则：

- `status != answerable` 时，不播详细答案
- `confidence < threshold` 时，退回短拒答
- 文本过长时，截成适合播报的两到三句

---

## 九、失败和降级规则

### 情况 1：LLM 超时

处理：

- 回退到规则化 `open_fallback`
- 或回答：
  - `这个问题我暂时不能完整解释。`

### 情况 2：LLM 返回非法结构

处理：

- 丢弃
- 记日志
- 返回 `unsupported`

### 情况 3：LLM 明显越权

例子：

- 给出直接策略命令
- 猜测未接入数据

处理：

- 标记 `unsafe`
- 不播

### 情况 4：LLM 不可用

处理：

- 系统继续保留：
  - `control lane`
  - `structured lane`
- 禁用 `explainer lane`

---

## 十、样例路由表

### 样例 1

输入：

- `后车差距`

结果：

- `structured`

原因：

- 高频确定性查询，core 已支持

### 样例 2

输入：

- `为什么刚才不让我进攻`

结果：

- `explainer`

原因：

- 属于允许解释域
- core 可提供摘要，但当前不一定有固定结构化答案

### 样例 3

输入：

- `后面那个...那个现在什么情况`

结果：

- `reject`

原因：

- `unrecognized`
- 应先要求重说

### 样例 4

输入：

- `现在帮我决定要不要进站`

结果：

- `reject`

原因：

- 直接策略执行请求
- 不允许进 LLM

### 样例 5

输入：

- `如果等一圈再进站会怎样`

结果：

- `explainer`

原因：

- 条件性追问
- 属于允许解释域

### 样例 6

输入：

- `五圈后会不会出安全车`

结果：

- `reject`

原因：

- 未接入、不可验证预测域

---

## 十一、实施任务拆解

### Task 1：新增 `transcript_router.py`

职责：

- 统一输出 `control / structured / explainer / reject`

交付标准：

- 不接 LLM 时也能跑通全路由

### Task 2：新增 `capability_registry.py`

职责：

- 定义 allowlist / denylist

交付标准：

- 所有是否能进 LLM 的判断都不再散落在 prompt 或模板里

### Task 3：扩展 structured 路径返回结构

职责：

- 让 core 返回“为什么没答”

交付标准：

- `not_enough_state / unsupported / unrecognized` 可区分

### Task 4：新增 `state_summary_for_llm.py`

职责：

- 生成受控状态摘要

交付标准：

- 相同状态下摘要稳定

### Task 5：新增 `llm_response_schema.py`

职责：

- 约束 sidecar 输出

交付标准：

- 任意 LLM 输出都必须先过 schema

### Task 6：新增 `llm_explainer.py`

职责：

- 真正调用模型

交付标准：

- 只服务 `explainer lane`
- 支持超时和失败降级

### Task 7：增加回归

最少覆盖：

- 控制命令不进 LLM
- 结构化 query 不被 LLM 抢答
- 解释型问题能进 sidecar
- transcript 太差时拒绝而不是乱答
- LLM 超时时系统仍然可用

---

## 十二、结论

“把 core 无法回答的问题交给 LLM 旁路”是对的，  
但前提不是简单的：

- `core_fail -> LLM`

而是：

- `control 未命中`
- `structured 明确无法稳定回答`
- `问题属于允许解释域`
- `状态摘要足够`
- `能力边界允许`

只有满足这些条件，LLM sidecar 才是安全、可控、可部署的扩展方式。

# Asurada 人格与情绪系统：设计分析与工程实现方案

> 版本：v1.0 ｜ 日期：2026-10-28 ｜ 状态：设计提案（非已合并代码）
>
> 目标：在不影响 F1 遥测、策略计算与安全提醒的前提下，使 Asurada 形成稳定人格、情境情绪、长期搭档关系和自然语音表现，接近《高智能方程式》中具有独立判断与个性的赛车搭档。

## 0. 范围与代码核对说明

本文基于此前讨论的 Asurada 模块划分进行工程设计，涉及 `voice_input.py`、`interaction.py`、`semantic_normalizer.py`、`response_composer.py`、`ConversationContext`、`StrategyDecision`、`open_fallback` 等概念。**本文件不是对当前仓库 HEAD 的逐行审计**；新增类、字段、路径均为建议接口，落地时需先核对实际签名和数据流，不能把示例代码视作已存在实现。

仓库入口：[Sn55555/Asurada](https://github.com/Sn55555/Asurada)。

## 1. 总体结论与设计原则

Asurada 的核心竞争力是实时赛车状态感知、预测与策略仲裁，而不是生成式聊天。人格改造应该是**附着在决策之后的交互层**，而非替换策略引擎：

1. **决策事实由核心引擎负责**：轮胎、ERS、进站、风险、置信度等关键事实不能由 LLM 凭空生成。
2. **人格是长期稳定的特质**，情绪是短时、可衰减的状态；二者不能混为一谈。
3. **情绪改变表达，不改变安全与策略结论**；关键安全提示拥有最高播报优先级。
4. **小模型仅作旁路**：长尾语言理解、策略解释和赛后复盘；超时/失败退回确定性模板。
5. **让角色有选择地说话**：沉默、打断、追问、吐槽都由 Dialogue Policy 决定，而不是每帧遥测触发一次模型。
6. **长期关系基于可验证的比赛事件**，不能编造共同经历或把角色的“信任”当作实际预测可靠性。

## 2. 目标人格：理性、自信、固执但关心车手

| 维度 | 初始建议 | 角色行为 | 约束 |
|---|---:|---|---|
| rationality 理性 | 0.95 | 优先引用策略依据 | 不捏造数据 |
| pride 自信/自尊 | 0.85 | 对计算有信心，偶尔反驳 | 不把主观自信当概率 |
| stubbornness 固执 | 0.75 | 对重复忽略的建议更坚定 | 不持续骚扰车手 |
| empathy 关心 | 0.70 | 事故和车损时先关心安全 | 不削弱关键告警 |
| humor 幽默 | 0.45 | 低负荷阶段适度吐槽 | 高风险时关闭 |
| competitiveness 好胜 | 0.90 | 超车、领奖台时明显兴奋 | 不鼓励危险驾驶 |

**同一事实，不同表达**：策略引擎输出 `PIT_NOW`。冷静：“当前是推荐进站窗口，建议本圈进站。”不满：“我已经提醒过你了，轮胎余量正在下降。现在进站。”高担忧：“别再冒险，先保证车辆状态。本圈进站。”无论语气如何，`PIT_NOW` 不得变成“继续跑”。

## 3. 架构与数据流

```text
F1 UDP → Decoder → StateStore → StrategyEngine → StrategyDecision
                           │                         │
                           └──── EventExtractor ─────┤
                                      │              │
                                      ▼              ▼
                               EmotionEngine    DialoguePolicy
                                      │              │
                              EmotionalState    ReplyIntent
                                      │              │
                                      └──────┬───────┘
                                             ▼
                                    PersonalityEngine
                                             │
                                    DialogueContext
                                             │
                          ┌──────────────────┴──────────────────┐
                          ▼                                     ▼
                  Deterministic Templates                 Sidecar LLM
                          │                                     │
                          └──────────────────┬──────────────────┘
                                             ▼
                                       OutputValidator
                                             ▼
                                   Priority Voice Queue
                                             ▼
                                     Expressive TTS
```

**数据单向性**：`EmotionEngine` 和 `Sidecar LLM` 不得直接写入 `StrategyEngine`、仲裁权重或 UDP 状态。旁路 LLM 只能读经过裁剪的快照及决策摘要。未来如允许生成策略候选，应单独设置只观察模式、离线回放和明确审批流程。

## 4. 数据模型与状态边界

### 4.1 长期人格 PersonalityProfile

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PersonalityProfile:
    rationality: float = 0.95
    pride: float = 0.85
    stubbornness: float = 0.75
    empathy: float = 0.70
    humor: float = 0.45
    competitiveness: float = 0.90
```

固定配置（可版本化），不要每次对话由 LLM 改写。允许用户显式选择“冷静/经典/活泼”预设，但策略事实不随预设变化。

### 4.2 短期情绪 EmotionalState

```python
from dataclasses import dataclass

@dataclass
class EmotionalState:
    trust: float = 0.70          # 关系表达用，不是预测概率
    frustration: float = 0.00
    confidence: float = 0.80     # 角色自信表现
    concern: float = 0.00
    excitement: float = 0.30
    competitiveness: float = 0.70
    updated_at_monotonic: float = 0.0
```

所有值钳制到 `[0, 1]`；`updated_at_monotonic` 仅用于当前进程的时间差，持久化时保存墙上时间戳与版本号，恢复后重新建立 monotonic 基准。

### 4.3 长期关系 DriverRelationship

```python
@dataclass
class DriverRelationship:
    races_together: int = 0
    shared_victories: int = 0
    successful_strategies: int = 0
    ignored_warnings: int = 0
    driver_style: str = "unknown"  # conservative / balanced / aggressive
```

关系数据来自经过验证的事件。比如“忽略警告”必须有警告发出记录、有效时间窗和未执行的客观判据，不能仅因结果不好就归因于车手。跨比赛持久化建议 SQLite，支持清空/关闭记忆。

## 5. 情绪事件系统：避免随机脾气

### 5.1 事件契约

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class EmotionEvent:
    event_id: str
    kind: str
    timestamp: float
    session_id: str
    severity: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)
```

建议事件：`OVERTAKE_SUCCESS`、`FASTEST_LAP`、`COLLISION`、`HIGH_DAMAGE`、`TYRE_RISK_HIGH`、`WARNING_IGNORED`、`PIT_RECOMMENDATION_FOLLOWED`、`RACE_FINISHED`。事件必须去重（`event_id`），并对重复警告设置冷却时间，避免每帧累计情绪。

### 5.2 情绪增量表（初始经验参数，需回放调参）

| 事件 | frustration | concern | excitement | trust |
|---|---:|---:|---:|---:|
| 成功超车 | 0 | 0 | +0.20 | +0.01 |
| 最快圈 | 0 | 0 | +0.25 | +0.02 |
| 严重碰撞 | 0 | +0.55 | -0.15 | 0 |
| 高轮胎风险 | +0.03 | +0.20 | 0 | 0 |
| 明确忽略关键警告 | +0.15 | +0.05 | 0 | -0.05 |
| 采纳并验证有效的建议 | -0.08 | -0.05 | +0.05 | +0.03 |

对同一事件只计算一次；`severity` 控制幅度。不能仅依据用户说“我不进站”就直接认定警告已被忽略，应等待策略事件与时间窗闭合。

### 5.3 可运行的最小 EmotionEngine

```python
from dataclasses import dataclass
from math import exp
import time


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class EmotionalState:
    trust: float = 0.70
    frustration: float = 0.0
    confidence: float = 0.80
    concern: float = 0.0
    excitement: float = 0.30
    competitiveness: float = 0.70


class EmotionEngine:
    # 目标是回归基线，而非所有情绪回归零
    BASELINES = {
        "trust": 0.70,
        "frustration": 0.00,
        "confidence": 0.80,
        "concern": 0.00,
        "excitement": 0.30,
        "competitiveness": 0.70,
    }
    # 半衰期，秒。关系信任不在单场内快速衰减。
    HALF_LIFE = {
        "trust": 86400.0,
        "frustration": 180.0,
        "confidence": 900.0,
        "concern": 120.0,
        "excitement": 90.0,
        "competitiveness": 3600.0,
    }
    DELTAS = {
        "OVERTAKE_SUCCESS": {"excitement": 0.20, "trust": 0.01},
        "FASTEST_LAP": {"excitement": 0.25, "trust": 0.02},
        "COLLISION": {"concern": 0.55, "excitement": -0.15},
        "TYRE_RISK_HIGH": {"concern": 0.20, "frustration": 0.03},
        "WARNING_IGNORED": {"frustration": 0.15, "trust": -0.05},
        "ADVICE_FOLLOWED": {"frustration": -0.08, "trust": 0.03},
    }

    def __init__(self):
        self.state = EmotionalState()
        self._last = time.monotonic()
        self._seen: set[str] = set()

    def tick(self, now: float | None = None) -> EmotionalState:
        now = time.monotonic() if now is None else now
        dt = max(0.0, now - self._last)
        self._last = now
        for name, baseline in self.BASELINES.items():
            old = getattr(self.state, name)
            factor = exp(-0.69314718056 * dt / self.HALF_LIFE[name])
            setattr(self.state, name, clamp(baseline + (old - baseline) * factor))
        return self.state

    def apply(self, event_id: str, kind: str, severity: float = 1.0) -> EmotionalState:
        self.tick()
        if event_id in self._seen:
            return self.state
        self._seen.add(event_id)
        severity = clamp(severity)
        for name, delta in self.DELTAS.get(kind, {}).items():
            setattr(self.state, name, clamp(getattr(self.state, name) + delta * severity))
        return self.state
```

**生产化注意**：示例 `_seen` 集合会持续增长，实际使用需按 session 或 TTL 清理；跨线程调用需串行化或加锁；长期 `trust` 应由关系模块持久化，不能依赖上述进程内衰减器作为唯一真值。

## 6. DialoguePolicy：什么时候说，比说什么更重要

建立独立的输出优先级与冷却机制：

| 场景 | 允许内容 | 典型策略 |
|---|---|---|
| 高速事故 / 严重车损 | 安全提醒、必要确认 | 抢占普通对话；短句 |
| 紧急进站 / 轮胎风险 | 核心策略提醒 | 优先播报；不讲笑话 |
| 激烈攻防 | 极简战术信息 | 暂停闲聊与长解释 |
| 稳定巡航 | 策略解释、少量吐槽 | 控制频率 |
| 比赛结束 | 庆祝、安慰、复盘 | 可用较丰富表达 |

建议输出契约：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ReplyIntent:
    event_id: str
    priority: int                 # 数值越大越紧急
    canonical_fact: str          # 不可改写的核心事实
    speech_act: str              # warn / explain / celebrate / chat
    style: str                   # calm / firm / concerned / excited
    allow_llm: bool
    max_chars: int = 80
    expires_at: float | None = None
```

**策略约束**：安全告警即使 LLM 正在生成也必须立刻播报；低优先级语音允许被打断或取消；相同警告设置去重键和冷却期；同一时刻只允许一个 TTS 播放所有者；过期回复丢弃。

## 7. Sidecar LLM：只负责自然语言表达

### 7.1 与当前 `open_fallback` 的关系

将未知开放式问题交给旁路模型是合理方向，但**不要让 `open_fallback` 成为绕过结构化查询校验的入口**。推荐：已知意图走规则快速路径；未知意图由小模型输出受限的结构化查询建议；后端校验后再查询状态。策略解释类任务则将既定 `StrategyDecision` 交给 LLM 改写表达。

### 7.2 任务输入示例

```json
{
  "request_id": "req-1024",
  "snapshot_binding_id": "snap-88",
  "driver_utterance": "我还想继续跑两圈",
  "decision": {
    "action": "PIT_NOW",
    "reason_codes": ["TYRE_DEGRADATION"],
    "risk_level": "HIGH"
  },
  "emotion": {
    "frustration": 0.65,
    "concern": 0.85
  },
  "personality_profile": "classic_asurada_v1",
  "constraints": {
    "language": "zh-CN",
    "max_chars": 80,
    "must_preserve_action": "PIT_NOW",
    "forbid_unprovided_numbers": true
  }
}
```

### 7.3 建议的输出协议

```json
{
  "text": "我不同意。轮胎状态已经很危险了，这一圈必须进站。",
  "style": "firm_concerned",
  "decision_ref": "PIT_NOW",
  "used_fact_ids": ["TYRE_DEGRADATION"]
}
```

**校验边界**：JSON Schema 只保证结构，不保证语义正确。必须检查 `decision_ref` 是否一致、数字是否来自允许的事实字段、长度和敏感词约束。对高风险播报建议使用预先批准的固定事实句，LLM 只生成可选的情绪前缀或后缀；不能仅靠 Prompt 保证事实一致。

### 7.4 异步与生命周期

```text
VoiceInputCoordinator / StrategyEvent
             │
             ▼
        Create TaskHandle
             │
             ▼
   Bind snapshot + decision id
             │
             ▼
     Sidecar request queue
             │
       ┌─────┴─────┐
       ▼           ▼
    success     timeout/error
       │           │
       ▼           ▼
    validate   template fallback
       │           │
       └─────┬─────┘
             ▼
  check cancellation / expiry
             ▼
       Voice priority queue
```

建议独立进程/服务承载本地推理，避免阻塞 UDP 接收和策略线程；设置队列上限、请求超时、取消与过期检查、断路器、降级模板。先测 1.5B～4B 量化模型，不以参数规模代替真实延迟与准确率测试；游戏与推理共机时尤其关注 GPU 资源竞争。

## 8. TTS 情绪表现

建议新增语音风格元数据：

```python
@dataclass(frozen=True)
class VoiceStyle:
    emotion: str = "neutral"
    speed: float = 1.0
    intensity: float = 0.5
    pitch: float = 0.0
```

| 状态 | 表达目标 | TTS 注意 |
|---|---|---|
| calm | 理性、清晰 | 默认声线 |
| firm | 坚定、不满 | 适度强调，不靠尖锐音调 |
| concerned | 严肃、关心 | 降低夸张度 |
| excited | 兴奋、自豪 | 轻微加速，提高能量 |
| urgent | 极简、明确 | 禁止冗长生成 |

实际参数需适配具体 TTS 引擎：部分引擎不支持 `intensity`、`pitch` 或情绪标签，不能假定直接生效。优先确保语音可懂度与游戏音效混音安全。

## 9. 与现有模块的集成建议

| 现有/建议文件 | 改动 | 风险级别 |
|---|---|---|
| `response_composer.py` | 将事实文本与语气风格解耦，保留固定模板 | 低～中 |
| `interaction.py` | 透传 request_id、snapshot_binding_id、取消/过期状态 | 中 |
| `voice_input.py` | 将车手输入转为交互事件，禁止同步等待模型 | 中 |
| `semantic_normalizer.py` | 保留高频已知意图快速路径，未知输入走受限 fallback | 低～中 |
| `personality/profile.py`（新增） | 固定人格配置与版本 | 低 |
| `personality/emotion.py`（新增） | 事件驱动情绪更新、衰减、去重 | 中 |
| `personality/dialogue_policy.py`（新增） | 发言门控、优先级、冷却、抢占 | 高 |
| `personality/relationship.py`（新增） | 跨比赛记忆与用户控制 | 中 |
| `llm/sidecar.py`（新增） | 异步推理适配器、超时、取消、降级 | 中～高 |
| `llm/context_builder.py`（新增） | 只读最小快照与决策摘要 | 中 |
| `llm/validator.py`（新增） | 结构校验与关键事实保护 | 高 |
| TTS 模块 | 支持 VoiceStyle 与优先级队列 | 中 |

建议避免直接在 `ResponseComposer` 中执行模型 HTTP 请求：该模块应尽可能保持纯函数式组合，便于单元测试、回放和降级。

## 10. 实施路线图

### Phase 0：现状审计与基线

- 追踪当前 `VoiceInputCoordinator → SemanticNormalizer → QueryRoute → ResponseComposer → TTS` 实际调用路径。
- 确认 `open_fallback` 是模板兜底还是已具备 LLM Provider；确认同步/异步边界。
- 采集匿名化比赛事件样本与现有播报频率、延迟、打断情况。

**验收**：形成调用链图、线程/协程归属图、真实字段映射表。

### Phase 1：确定性人格 MVP（优先）

- 新增 `PersonalityProfile`、`EmotionEngine`、`DialoguePolicy`。
- 仅支持事故、超车、最快圈、轮胎风险、忽略建议五类事件。
- 模板覆盖 calm/firm/concerned/excited 四种风格。
- 完成去重、衰减、优先级、冷却与过期丢弃。

**验收**：关闭 LLM 时也能表现稳定角色感；安全提示不延迟；情绪轨迹可回放。

### Phase 2：旁路小模型表达

- 新增异步 Sidecar Provider、上下文裁剪、受限 JSON 输出、验证器和模板降级。
- 仅在非紧急交互、开放式提问、赛后复盘调用。
- 先以 Shadow Mode 记录模型输出，不实际播报；通过测试后小流量启用。

**验收**：模型异常不影响 UDP/策略；关键决策不被篡改；过期回答不会播报。

### Phase 3：关系记忆与情绪 TTS

- SQLite 记录经过验证的跨比赛事件，支持禁用与清除。
- 增加可配置的表达风格和 TTS 情绪映射。
- 实现比赛结束的个性化总结，严格引用真实历史。

**验收**：不编造共同经历；不同比赛间的关系变化可解释；用户可重置。

## 11. 测试计划与质量门槛

| 测试项 | 方法 | 建议验收标准 |
|---|---|---|
| 情绪状态边界 | 属性测试、随机事件序列 | 始终位于 0～1 |
| 重复事件去重 | 同 event_id 重放 | 状态仅更新一次 |
| 衰减正确性 | 注入虚拟时钟 | 按半衰期回归基线 |
| 事件可回放 | 固定输入、固定时间 | 同版本结果一致 |
| 策略事实一致性 | LLM 故意输出相反动作 | 必须拒绝并降级 |
| 实时性隔离 | 人为延迟/断开模型 | 核心 UDP/策略不被阻塞 |
| 取消与过期 | 赛况变化、快速连问 | 旧回答不再播报 |
| 关键播报抢占 | 正在闲聊时触发碰撞 | 紧急提醒优先 |
| 关系记忆真实性 | 注入未发生历史 | 不产生虚构共同经历 |
| 资源占用 | 与 F1 游戏同机压力测试 | 无明显帧率/语音卡顿 |

推荐补充两个量化指标：**每十分钟非必要播报次数**和**策略事实违背率**。人格体验并非“说得越多越好”；后者对正式启用应设为零容忍，实际测试中任何一次违背都应阻断上线并修复。

### 示例 pytest

```python
def test_duplicate_event_is_idempotent():
    engine = EmotionEngine()
    first = engine.apply("race1:lap5:overtake", "OVERTAKE_SUCCESS").excitement
    second = engine.apply("race1:lap5:overtake", "OVERTAKE_SUCCESS").excitement
    assert first == second


def test_emotion_clamped():
    engine = EmotionEngine()
    for n in range(100):
        engine.apply(f"collision-{n}", "COLLISION")
    assert 0.0 <= engine.state.concern <= 1.0
```

## 12. 关键工程风险及规避

1. **误判车手“不听建议”**：必须以已发出的有效警告 + 时间窗 + 客观动作判定；不可仅根据结果归责。
2. **情绪过于频繁变化**：事件去重、阈值滞回、冷却和衰减共同控制。
3. **LLM 改写策略**：保留不可变 `StrategyDecision`，输出验证，关键告警模板优先。
4. **过期语音**：每次结果都检查 `request_id`、快照版本、赛况时效与取消标记。
5. **长时记忆污染**：只记录可信事件，限制保存期限，提供删除与重置入口。
6. **过度拟人化影响体验**：允许“安静模式”和人格强度调节；角色脾气不能成为打扰。
7. **TTS 不支持情绪参数**：采用风格映射与句式模板降级，不假设所有引擎具备表现力。

## 13. 最小可交付任务清单

- [ ] 核对仓库当前代码的入口函数、类型签名和线程模型。
- [ ] 设计 `EmotionEvent` 与 `ReplyIntent` 契约，给出版本号。
- [ ] 实现 `EmotionEngine`（事件驱动、去重、衰减、上下界）。
- [ ] 实现 `DialoguePolicy`（优先级、静默、冷却、打断、过期）。
- [ ] 将 `ResponseComposer` 改为“事实 + 风格”的两阶段输出。
- [ ] 编写事件回放和单元测试，确保关闭 LLM 仍能工作。
- [ ] 接入只读 Sidecar LLM，先 Shadow Mode 再实际播报。
- [ ] 增加输出验证、超时、取消、降级和监控。
- [ ] 接入长期关系存储及用户控制。
- [ ] 适配情绪 TTS，并进行游戏同机性能测试。

## 14. 推荐优先级与最终定位

**第一优先级是 `DialoguePolicy + EmotionEngine`，而不是选模型或换声线。** 先让 Asurada 对事件有持续、合理的态度，并知道什么时候应该保持沉默。第二优先级才是 Sidecar LLM 自然语言表达；第三优先级是跨比赛记忆和情绪化 TTS。

最终目标是一个**有独立判断、会坚持意见、懂得关心车手、拥有共同经历，同时仍可靠且可控的赛车搭档**。即使旁路 LLM 故障，Asurada 的策略与人格基本行为也应继续正常工作。

---

### 参考入口

- 项目仓库：<https://github.com/Sn55555/Asurada>
- 架构文档（路径以仓库实际结构为准）：<https://github.com/Sn55555/Asurada/blob/main/asurada-core/ARCHITECTURE.md>
- 项目状态文档：<https://github.com/Sn55555/Asurada/blob/main/asurada-core/STATUS.md>

> 注：本设计中的阈值、情绪增量、类名、模型输出协议均为可落地的**建议初值**，必须通过真实遥测回放与语音测试验证后再用于正式版本。

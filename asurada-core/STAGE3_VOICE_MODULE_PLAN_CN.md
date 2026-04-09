# 阶段三语音模块实施计划

## 文档范围

本文档只拆解**阶段三语音模块**的实施计划，不覆盖整个阶段三。

---

## 一、实施目标

本文档描述的是**阶段三语音模块的最终产品化收口计划**，不是当前仓库实现快照。

当前仓库已经先落地了一条开发机可运行链：

- `voice sidecar`
- Doubao LLM / streaming TTS / realtime ASR
- macOS realtime `voice loop`
- `companion` 模式
- wake preview / partial transcript arm

因此下面的“首发边界”和“实施顺序”，应理解为：

- Pi / CM5 正式产品化目标
- 本地优先架构的收口路线

把当前已完成的统一下行语音输出主线，扩展成：

- 树莓派可部署
- 结构化双向语音可用
- 本地可降级
- 不重复开发输出侧

阶段三语音模块在 Pi / CM5 首发目标下的交付边界是：

- 系统主动播报继续可用
- 结构化语音查询可用
- 本地可降级
- 正式设备侧 TTS 可用

不在 Pi 首发必须完成的范围：

- 开放式自由问答
- 把 LLM 变成策略主链
- 完整产品级双工体验

当前代码位置：

- 已完成统一下行语音输出主线
- 已完成 `AudioIO / VAD / VoiceTurn / FastIntentASR / voice_nlu / voice_input` 输入基础
- 已完成语义归一化、短上下文记忆、规则化解释层与 `open_fallback`
- 已完成 `PiperBackend` 代码路径
- 已完成 `voice sidecar` 与 Doubao LLM / TTS / realtime ASR 开发链
- 当前剩余重点是 AEC / 串音抑制、local ASR fallback、watchdog 与 Pi 真机联调

---

## 二、实施顺序

### Phase A：锁定语音协议与模块边界

目标：

- 明确输入侧如何接入现有交互协议
- 明确输出侧继续复用现有主线

交付物：

- 本文档
- [STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md](STAGE3_VOICE_MODULE_ARCHITECTURE_CN.md)

完成标准：

- `InteractionInputEvent / StructuredQuerySchema / QueryRoute / ConfirmationPolicy / SpeechJob` 边界不再变化

### Phase B：AudioIO + VAD + AEC

目标：

- 在树莓派侧建立稳定的音频输入 turn 边界
- 解决当前开发链仍存在的串音与回声问题

实现项：

- `audio_io.py`
- `vad.py`
- `voice_turn.py`

建议先做：

- `PTT` 或受控 wake word
- `Silero VAD`
- AEC / 下行门控

完成标准：

- 能稳定形成语音 turn
- 能记录 turn 开始、结束、持续时长
- 不引入主链阻塞

### Phase C：正式输入主路径收口

目标：

- 在当前 realtime ASR 开发链基础上，收口正式输入主路径
- 区分“开发机云端 sidecar 主路径”和“Pi 本地主路径”

实现项：

- `asr_fast.py`
- `voice_nlu.py`
- `dialogue_policy.py`
- realtime ASR 与本地 fallback 的切换策略

首发 query 范围：

- 燃油
- 后车差距
- 轮胎状态
- 当前主策略
- 停止 / 取消 / 重复

完成标准：

- 受限 query 能进入现有 `StructuredQuerySchema`
- 查询响应能走现有统一输出主线
- 开发机链继续可跑
- Pi 目标链可替换掉当前云端依赖

### Phase D：PiperBackend 正式设备侧 TTS

目标：

- 把正式 TTS backend 从 `say` 切换到设备侧本地实现

实现项：

- `tts_backends.py`
- `PiperBackend`

完成标准：

- 树莓派可本地播报
- 继续复用当前 `OutputCoordinator`
- 不改变 `SpeechJob` 和 output lifecycle 协议

### Phase E：Voice Health / Watchdog

目标：

- 让语音模块具备正式降级与恢复能力

实现项：

- `voice_health.py`
- worker heartbeat
- 自动重启
- 降级模式切换

完成标准：

- 单个 worker 崩溃不拖死主链
- TTS / ASR / AudioIO 都可局部重启
- 降级状态可写入 debug/log

### Phase F：Local ASR Fallback / Transcript Arbiter

目标：

- 增加本地 ASR fallback，但不影响当前 realtime 主路径
- 为 Pi / 离线模式提供可降级识别链

实现项：

- `asr_open.py`
- `transcript_arbiter.py`

推荐：

- `whisper.cpp`

完成标准：

- 云端 realtime ASR 不可用时可切本地 fallback
- 不抢结构化 query 主路径
- transcript 来源在日志中可观测

### Phase G：Selective Barge-in

目标：

- 给 stop / cancel / repeat 增加有限硬打断

实现项：

- 输入 turn 与输出队列联动
- 控制命令 hard stop

完成标准：

- 仅控制命令允许打断 active TTS
- 其它普通 query 仍遵守现有 active 不打断规则

---

## 三、最终产品化仍需收口的模块清单

当前仓库里，以下模块已经存在并可运行：

- `voice_sidecar_server`
- `voice_sidecar_protocol`
- `voice_sidecar_asr`
- `voice_sidecar_tts`
- `llm_explainer`
- `phase3_macos_voice_loop.py`

下一批仍需补齐或收口的模块：

- `src/asurada/audio_io.py`
- `src/asurada/vad.py`
- `src/asurada/voice_health.py`
- `src/asurada/asr_open.py`
- `src/asurada/transcript_arbiter.py`
- `PiperBackend` 的 Pi 真机与正式切换路径

不建议第一批就把所有内容塞进：

- `output.py`
- `interaction.py`

这两份应继续作为稳定协议层使用。

---

## 四、测试计划

### 1. 单元测试

- `SpeechJob` 输入映射正确
- `FastIntentASR` 能输出结构化 query
- `DialoguePolicy` 能正确决定：
  - 执行
  - 拒绝
  - 重复
  - 取消
- `PiperBackend` 能启动、完成、失败回报

### 2. 集成测试

- `PTT -> VAD -> FastIntentASR -> QueryRoute -> TTS`
- 系统主动播报与语音查询混合触发
- `stop / cancel / repeat` 的控制命令链路

### 3. 设备测试

- 树莓派 CPU 占用
- 热负载
- 连续播报稳定性
- 长时间 worker 稳定性

### 4. 回归测试

- 保留并扩展当前：
  - [phase3_voice_regression.py](scripts/phase3_voice_regression.py)

新增方向：

- 输入 turn regression
- 语音 query routing regression
- watchdog regression

---

## 五、正式验收标准

阶段三语音模块首发完成的验收标准：

1. 树莓派上可本地播报
2. 结构化语音查询可用
3. 系统主动播报与查询响应共用同一输出主线
4. worker 异常不会拖死主链
5. 语音模块支持局部降级

只有满足以上条件，才能把阶段三语音模块视为“首发完成”。

---

## 六、当前最优推进顺序

建议严格按以下顺序推进：

1. `AudioIO + VAD`
2. `FastIntentASR`
3. `PiperBackend`
4. `Voice Health / Watchdog`
5. `OpenASR fallback`
6. `Selective barge-in`

不建议调整成：

- 先上 wake word
- 先上开放式 ASR
- 先做云端/远端语音

这些方向会显著增加复杂度，但不提升阶段三语音模块首发成功率。

---

## 七、结论

阶段三语音模块应作为一个独立子系统推进，而不是作为“整个阶段三”的模糊子任务推进。

当前最合理的执行策略是：

**先用结构化快路径完成树莓派本地双向语音闭环，再用开放式 ASR 和更复杂的唤醒/打断策略做后续扩展。**

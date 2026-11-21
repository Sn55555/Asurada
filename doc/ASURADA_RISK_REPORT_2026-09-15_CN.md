# Asurada 技术风险报告与处置方案

| 项 | 内容 |
| --- | --- |
| 报告类型 | 技术风险登记与处置方案 |
| 评估范围 | `/Users/sn5/Asurada` 全工作区（主体：`asurada-core`） |
| 评估日期 | 2026-09-15 |
| 评估方法 | 源码级实证扫描（逐文件阅读 + 文本检索 + `wc -l` / `git ls-files` / `diff` 实测），并对既有评审文档逐条回验 |
| 证据基线 | `src/` 共 29,178 行；226 个脚本（184 个含 `regression`）；`build/` 未纳入 git |
| 关联文档 | [ASURADA_ARCHITECTURE_REVIEW_2026-09-15_CN.md](ASURADA_ARCHITECTURE_REVIEW_2026-09-15_CN.md)、[ASURADA_ARCHITECTURE_IMPLEMENTATION_PLAN_CN.md](ASURADA_ARCHITECTURE_IMPLEMENTATION_PLAN_CN.md) |
| 总体结论 | **1 项 P0 级进程中断风险必须立即处置；3 项 P1 语义错误影响产品正确性；7 项既有 P0 缺陷经回验已修复，不应重复施工。** |

---

## 1. 报告概要

### 1.1 总体风险指数

| 维度 | 评级 | 说明 |
| --- | --- | --- |
| 运行时稳定性 | 🔴 高 | 存在单包畸形即终止实时策略循环的确定路径（R-01） |
| 决策正确性 | 🟡 中 | 事实源已统一（已修复），但仲裁防抖为死代码、能力时效口径过宽（R-02 / R-04） |
| 协议健壮性 | 🟠 中高 | Session 包定长强校验，版本漂移即全量失明（R-03） |
| 模型有效性 | 🔴 高 | 全部标签为伪标签、0 个 active 模型、5 个模型阻塞（R-12 / R-13） |
| 产品可用性 | 🔴 高 | 无 AEC、macOS 强绑定，直接阻断阶段三产品化目标（R-14 / R-15） |
| 工程可持续性 | 🟡 中 | 无测试框架、无 CI、7 个 >1000 行巨型文件（R-05 / R-06） |
| 可维护性 | 🟢 低 | 构建漂移、常量散落、冗余分支等清理项（R-07 / R-08 / R-10） |

### 1.2 风险统计

| 等级 | 数量 | 编号 |
| --- | --- | --- |
| 🔴 极高 | 1 | R-01 |
| 🟠 高 | 6 | R-02 ~ R-06、R-13 |
| 🟡 中 | 7 | R-07 ~ R-12、R-14 |
| 🟢 低 | 6 | R-15 ~ R-20 |

### 1.3 处置策略分布

| 策略 | 适用风险 | 说明 |
| --- | --- | --- |
| 消除（Avoid） | R-01、R-02、R-07 | 从根因移除，不留分支 |
| 降低（Mitigate） | R-03 ~ R-06、R-08 ~ R-13 | 加防护 / 收敛 / 分级 |
| 转移（Transfer） | 无 | 本项目为本地部署，无第三方转移空间 |
| 接受（Accept） | R-16 ~ R-20 | 记录 + 监视，不投入修复资源 |

---

## 2. 风险登记册（主表）

| ID | 风险描述 | 类别 | 严重度 | 可能性 | 等级 | 现有缓解 | 证据 | 置信度 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **R-01** | 单包解码异常（`struct.error` 等）逃逸，终止实时策略循环 | 可用性 | 高 | 高 | 🔴 极高 | 仅捕获 `PacketDecodeError` | `pdu_decoder.py:122/133/451`；`live_runtime.py:55-60`；`app.py:129-146` | 高 |
| **R-02** | 仲裁器冷却抑制为死代码，日志误报"冷却已生效" | 正确性 | 中 | 确定 | 🟠 高 | 无（`cooldown_hint` 仅作优先级下界） | `arbiter.py:225`；`fallback.py:43-47/88-99` | 高 |
| **R-03** | Session 包长度强等于 753，版本漂移即静默丢失全部赛况 | 协议 | 中高 | 中 | 🟠 高 | 无 | `pdu_decoder.py:173-174` | 高 |
| **R-04** | 全部 capability 共用 `freshness=15s`，秒级量可能用过时值回答 | 正确性 | 中 | 确定 | 🟠 高 | 无 | `capability_definitions.py:64-74` | 高 |
| **R-05** | 7 个源码文件 >1000 行，维护 / 评审成本高 | 可维护 | 中 | 确定 | 🟠 高 | 无 | `wc -l` 实测：`output.py` 1735 等 | 高 |
| **R-06** | 无测试框架、无 CI，184 个回归靠手工串跑 | 工程 | 中 | 高 | 🟠 高 | `run_regressions.py` 手工入口 | `pyproject.toml` 无 pytest；无 `.github` | 高 |
| **R-13** | 0 个 active 模型；3 个攻防主线模型未接入 runtime | 模型 | 中高 | 确定 | 🟠 高 | 12 observe + 2 disabled | `model_admission.py`；报告级证据 | 中高 |
| **R-07** | `build/` 旧副本漂移，语义与 `src/` 不同 | 维护 | 低 | 确定 | 🟡 中 | 未纳入 git | `diff` 实测：缺 `set_review_detail`、投影仍 v1 | 高 |
| **R-08** | `raw` 快照塞入整块子包，且含完全重复字段 | 性能 | 中 | 确定 | 🟡 中 | 无 | `packet_snapshot.py:533-550` | 高 |
| **R-09** | 墓碑集合无上界，长跑下单调增长 | 稳定性 | 低 | 低 | 🟡 中 | 注释说明为有意设计 | `session_lifecycle.py:23-25`；`output.py:90-92` | 高 |
| **R-10** | 字节上限常量散落多处，改一处易漏改 | 维护 | 中 | 中 | 🟡 中 | 无统一模块 | 实测多处字面量 | 高 |
| **R-11** | 旧 / 新仲裁通道并存，行为随生效通道漂移 | 可维护 | 中 | 确定 | 🟡 中 | arbiter 优先 | `strategy.py:918/950-973` | 中高 |
| **R-12** | 全部训练标签为伪标签，指标仅证明"复现规则" | 业务 | 高 | 确定 | 🟡 中 | manifest 标注 `human_validated=false` | manifest `label_provenance` | 中高 |
| **R-14** | 无 AEC，外放环境上行被播报污染 | 产品 | 中高 | 确定 | 🟡 中 | `voice_meter` 启发式门控 | `phase3_macos_voice_loop.py` 说明 | 中高 |
| **R-15** | macOS 强绑定（Swift + `say`/`afconvert`/`afplay`/`ffplay`） | 平台 | 高（对 Pi 目标） | 确定 | 🟡 中 | `AlsaArecordInputBackend` 已存在 | `audio_io.py`；`macos_*` | 中高 |
| **R-16** | 取消 ≠ 已停止，缺服务端停止回执 | 正确性 | 中 | 中 | 🟢 低 | 已真实 kill 播放进程 | `playback_control.py:48-60` | 高 |
| **R-17** | LapData 尾部 5 字节 speed trap 未解析 | 协议 | 低 | 确定 | 🟢 低 | 无 | `pdu_decoder.py:62/437-443` | 高 |
| **R-18** | 扩展数据集仅本机绝对路径可复现 | 工程 | 中 | 确定 | 🟢 低 | 有交接文档 | `tmp/local_extended_dataset_workflow.md` | 中 |
| **R-19** | 多个暂停模型指标不可用仍在库 | 模型 | 低 | 确定 | 🟢 低 | 报告标注 blocked | `training/reports/*` | 中 |
| **R-20** | 文档进度数字不一致（Phase 3：10% vs 35%） | 文档 | 低 | 确定 | 🟢 低 | 无 | 根 `README.md` vs `PROJECT_PROGRESS.md` | 高 |

---

## 3. 风险分级矩阵

```text
可能性 ↑
  高 │ R-01              │ (空)         │ (空)
     │                   │              │
  中 │ R-06              │ R-03 R-10    │ R-11
     │                   │ R-16         │
  低 │ R-09              │ (空)         │ (空)
     └───────────────────┴──────────────┴──────────────→ 严重度
         低                  中              高

确定级风险（可能性 = 确定，按严重度归位）：
  R-02 / R-04 / R-05  → 中高
  R-07 / R-08 / R-12 / R-13 / R-14 / R-15 / R-17 ~ R-20
```

**处置优先级（强制顺序）**：`R-01` → `R-02 / R-03 / R-04` → `R-06` → `R-05 / R-08` → `R-12 / R-13` → 其余。

---

## 4. 详细处置方案

### R-01 🔴 极高｜单包解码异常终止实时策略循环

**风险陈述**

`F125PacketDecoder.decode_raw()` 在 `pdu_decoder.py:122` 调用 `_decode_body()` 时**没有任何异常防护**。而 `_decode_motion_car`（`:133`）、`_decode_lap_data_car`（`:451-455`）、`_decode_car_telemetry`（`:595`）等使用无长度守卫的 `struct.unpack_from`，payload 截断时抛 **`struct.error`**（非 `PacketDecodeError`）。上层 `live_runtime.py:55-60` 只捕获 `PacketDecodeError`，`app.py:129-146` 是 `try/finally`（无 `except`），`__main__.py` 亦无兜底 → 异常一路逃逸至 CLI，**实时策略脑直接退出**。

**触发条件**：真实 F1 UDP 为不可靠传输，截断 / 畸形包属常态；故障注入或游戏版本变更均可复现。受影响包类型：Motion / LapData / CarTelemetry / CarStatus / MotionEx / CarSetups / Participants（共 7 类）。

**影响**：比赛进行中服务中断；离线导出 / 复盘（`export_phase2_training_data.py:616`、`review_capture.py:40`）整批失败而非跳过坏包。

**根因**：异常契约不完整 —— 解码层只定义了 `PacketDecodeError` 一种失败语义，但实现会抛出多种底层异常；调用方按"只有一种异常"的假设编写。

**处置方案（消除）**

| 步骤 | 动作 | 文件 |
| --- | --- | --- |
| A1 | `decode_raw` 中以受保护方式调用 `_decode_body`，捕获 `struct.error / IndexError / UnicodeDecodeError / ValueError / KeyError`，统一包装为 `PacketDecodeError(f"packet_id={id} kind={name} bytes={n}: {exc}")` | `pdu_decoder.py:122` |
| A2 | header 增 `decode_degraded` 标记，body 附 `_error` 字段，使坏包可观测而非静默 | `pdu_decoder.py:103-129` |
| A3 | `live_runtime` / `capture_runtime` 的循环增加 `except Exception` 兜底：计数 + 打印 + `continue`，**保证循环永不因单包退出** | `live_runtime.py:55-60`、`capture_runtime.py:69-73` |
| A4 | `run_live_udp` 的 `try/finally` 补 `except Exception`：先完成清理再抛出 | `app.py:129-146` |
| A5 | 导出与复盘路径同步兜底，坏包计入 `decode_errors` 统计 | `export_phase2_training_data.py`、`review_capture.py` |

**新增回归**：`scripts/packet_decode_resilience_regression.py`

- 对 7 类包各构造 `payload[:-1]` / `payload[:29]` / 半截断 三种畸形包
- 断言：① 抛 `PacketDecodeError`；② `LiveRuntime` 循环继续且 `decode_error_count` 递增；③ 畸形包之后的正常包仍被正常处理

**验收标准**：回归全绿；畸形包注入回放连续运行 30 分钟不中断；生成 `output/architecture-implementation/a02-decode-resilience/summary.json`

**工作量**：1.5 人日（含回归）｜**依赖**：无｜**约束**：R-03 必须在其后实施

---

### R-02 🟠 高｜仲裁器冷却抑制为死代码

**风险陈述**

`arbiter.py:225` 的抑制条件为 `output_control.last_emitted_action and output_control.suppression_window > 0`。但 `fallback.py` 在三处构造 `OutputControl` 时**全部写死** `last_emitted_action=None, suppression_window=0`（`:43-47` 初始、`:88-92` state_lock、`:95-99` tactical_prepare）。而 `strategy.py` 实际维护了 `_last_primary_action_by_session`，**却从未回灌**到 `OutputControl`。

**影响**：① 抑制分支永不触发，`suppressed_actions` 中永远看不到 `cooldown_window` 原因；② dashboard（`dashboard.py:968`）与日志呈现"冷却已配置"的错觉；③ 真实防抖仅靠 `cooldown_hint` 充当语音优先级下界，命名与语义不符；④ 后续开发者按注释调 `suppression_window` 将无效。

**处置方案（消除 —— 必须二选一，不得悬空）**

**方案 A（推荐，接通）**

| 步骤 | 动作 |
| --- | --- |
| B1 | `StrategyEngine` 增 `_last_emitted_at_by_session`（单调时钟），与已有 `_last_primary_action_by_session` 配对 |
| B2 | `_build_arbiter_sidecar` 组装 `OutputControl` 时传入真实 `last_emitted_action` 与 `suppression_window` |
| B3 | `fallback.py` 三处不再写死，改由入参透传；无历史时保持 `None/0` |
| B4 | 新增配置 `ASURADA_ARBITER_SUPPRESSION_WINDOW_S`（默认 8；设 0 = 关闭抑制，等价当前行为） |

**方案 B（删除）**：移除 `arbiter.py:225-238` 分支与 `OutputControl` 两字段，并在 dashboard 明确"cooldown 仅作语音优先级下界"。

**新增回归**：`scripts/arbiter_cooldown_window_regression.py`

- ① 窗口内重复主动作被抑制且 `suppression_reason="cooldown_window"`；② 窗口外不抑制；③ `SAFETY_CAR` 永不被抑制；④ 窗口 = 0 时逐帧行为与旧版完全一致

**验收标准**：选定方案后无残留字段；窗口开关双向验证通过

**工作量**：方案 A 2 人日 / 方案 B 0.5 人日｜**依赖**：无｜**注意**：方案 A 会引入真实行为变更，**必须先做差分回放**并归因每处差异

---

### R-03 🟠 高｜Session 包定长强校验导致版本漂移即失明

**风险陈述**

`pdu_decoder.py:173-174`：`if len(payload) != 753: raise PacketDecodeError(...)`。

**影响**：游戏小版本更新导致 Session 包长度变化时，**100% Session 包被丢弃**。由于 Session 为跨帧缓存（TTL 5s），`session_type / track_id / total_laps / weather / safety_car / marshal zones` 全部降级或过期，而 `session_router` 与策略层高度依赖这些字段 → 用户侧只感知"策略莫名退化"，无明确告警，排障成本极高。

**旁证**：同文件 `:168-171` 的注释本身已记录过同类事故（"之前按实际天气样本数截断，导致 forecast 槽位被误判成 trailer"）。且 `_decode_lobby_info`（`:533-534`）对同一类布局变更采取了宽松策略 —— Session 未走同一路线，属**防护不一致**。

**处置方案（降低）**

| 步骤 | 动作 |
| --- | --- |
| C1 | `:173` 改为下界检查：`if len(payload) < 753: raise PacketDecodeError(...)` |
| C2 | `SESSION_PREFIX_FORMAT` 的 `unpack_from`（`:175`）前补长度守卫 |
| C3 | 复用已有安全读取器 `read_u8/read_u32/read_f32`（`:232-253`），确保 `session_trailer_hex`（`:392`）**记录全部剩余字节而非丢弃** |
| C4 | 长度 ≠ 753 时输出 `[ASURADA][PROTOCOL] session packet size drift: got=…, expected=753` 告警，并写 `header["size_drift"]` 供 dashboard 展示 |
| C5 | 同步更新 `PACKET_FIELD_COVERAGE.md`、`UNRESOLVED_PACKET_FIELDS.md` |

**新增回归**：`scripts/session_packet_layout_tolerance_regression.py`

- 用 753 / 760 / 800 / 752 四种长度断言：① 前三者解析成功且 `size_drift` 正确；② 752 抛 `PacketDecodeError`；③ marshal zones / safety_car / 尾部设置字段取值不受长度影响

**验收标准**：回归全绿；长度漂移在日志与 dashboard 均可见

**工作量**：1 人日｜**依赖**：**必须晚于 R-01**（否则宽松化会放大 `struct.error` 暴露面）

---

### R-04 🟠 高｜能力时效口径全部写死 15 秒

**风险陈述**

`capability_definitions.py:64-74` 等处全部以**位置参数**传 `freshness_ms=15000, deadline_ms=1800`（参数序为 `lane, permission, freshness, deadline, priority, handler`），对所有 capability 一致。

**影响**：① `front_gap` / `rear_gap` / `drs_status` 等**秒级变化量**可能用 15 秒前的车距回答"前车多远"，属实时语义错误；② `race_control_status` / `penalty_*` 等低频量反而偏紧；③ 位置参数极易写错位；④ 与 `speech_applicability.py` 的 assist 窗口（0.35s / 0.75s）形成**同系统两套时效口径**。

**处置方案（降低 —— 分级 + 具名化）**

| 分组 | capability 示例 | freshness | deadline |
| --- | --- | --- | --- |
| `control` | stop / cancel / repeat / assist 开关 | 2000 | 800 |
| `structured` 秒级量 | `front_gap` `rear_gap` `drs_status` `front_rival_drs_status` `ers_status` | 1500 | 900 |
| `structured` 状态量 | `tyre_status` `damage_*` `fuel_status` `weather_status` `current_strategy` | 3000 | 1800 |
| `structured` 低频量 | `race_control_status` `penalty_*` `pit_penalty_plan` | 5000 | 1800 |
| `explainer` | `why_not_*` `overall_situation` `open_fallback` | 8000 | 1800 |
| `analysis_tool` | `compare_review_laps` `compare_review_segments` | 15000 | 1800 |

**动作**：① 全表 `freshness_ms=` / `deadline_ms=` 改具名参数；② 按上表分组赋值（初始值，后续用实机标定）；③ 显式记录与 assist 窗口的层级关系。

**新增回归**：`scripts/capability_freshness_policy_regression.py`

- 断言每个 lane 的 `freshness_ms` ≤ 该 lane 上限、`deadline_ms < freshness_ms`、**且无 capability 使用默认缺省值**（防漏填）

**验收标准**：回归全绿；差分回放确认收紧后未出现意外"拒答"（需检查 `answer_policy` 兜底文案是否覆盖该路径）

**工作量**：1.5 人日｜**依赖**：无｜**注意**：收紧会把部分场景从"答旧值"变为"拒答"，属体验变更，需产品确认

---

### R-05 🟠 高｜7 个源码文件超过 1000 行

**风险陈述**（实测，非文档估算）

| 文件 | 行数 |
| --- | --- |
| `output.py` | 1735 |
| `voice_sidecar_asr.py` | 1470 |
| `strategy.py` | 1213 |
| `dashboard.py` | 1190 |
| `long_horizon.py` | 1167 |
| `pdu_decoder.py` | 1104 |
| `packet_snapshot.py` | 1048 |

> ⚠️ **注意**：既有评审文档称 `interaction.py` 1152 行、`response_composer.py` 1156 行，实测为 **725 / 447 行** —— 该文档数字已过期，**不得据此做拆分评估**。

**影响**：评审 / 回归成本高；单文件改动误伤面大；新人上手门槛高。

**处置方案（降低 —— 低风险纯结构拆分，严禁改行为）**

| 步骤 | 动作 |
| --- | --- |
| E1 | `pdu_decoder` 拆为 `decoders/` 子包，按 packet 家族分文件（motion / lap_data / car_status / …），保留 `F125PacketDecoder` 为门面 |
| E2 | `dashboard.py` 抽取 HTML / JS 模板到 `dashboard_templates/`，Python 侧只留数据组装 |
| E3 | `long_horizon.py` 抽取常量与评分函数为独立模块 |
| E4 | `output.py` 按"队列调度 / 生命周期 / 信封构造"三段拆分，`ConsoleVoiceOutput` 保持公共入口不变 |
| E5 | 加"单文件行数上限"回归（阈值 800，**仅对新增文件生效**，存量渐进收敛） |

**验收标准**：拆分前后对同一抓包的 `session_log.jsonl` 与 `decision` 字段**逐字节一致**（差分断言）

**工作量**：8 人日（分 4 批）｜**依赖**：**必须晚于 R-01 ~ R-04** —— 在仍会崩溃的系统上重构等于放大风险

---

### R-06 🟠 高｜无测试框架、无 CI

**风险陈述**

`pyproject.toml` / `setup.py` 未声明 pytest / tox / nox / coverage；无 `.github` 目录；226 个脚本（184 个含 `regression`）全部依赖 `scripts/run_regressions.py` 手工串跑。

**影响**：无并行执行、无覆盖率度量、无强制门禁、新贡献者不知该跑哪几个；回归脚本自身也无测试覆盖（"测测试"缺失）。

**处置方案（降低 —— 只加发现与并行层，不改写脚本）**

| 步骤 | 动作 |
| --- | --- |
| F1 | `pyproject.toml` 增 `[project.optional-dependencies] dev = ["pytest==8.3.*"]` |
| F2 | 新增 `tests/test_regressions.py`，用 `pytest.mark.parametrize` 遍历 `scripts/*_regression.py`，以 `subprocess` 运行并把 `exit_code` + 脚本内 `checks` 断言映射为测试结果 |
| F3 | `run_regressions.py` 增 `--parallel N`（`concurrent.futures`），与 pytest 共用同一发现逻辑，避免两套清单漂移 |
| F4 | 加最小 CI（GitHub Actions 或本地 `pre-push` hook）：PR 跑 P0 / P1 关键子集（约 25 个），全量留夜间 |

**验收标准**：`pytest -n auto tests/` 可并行跑完 184 个回归；CI 门禁在 PR 上生效

**工作量**：2 人日｜**依赖**：无｜**约束**：**保留"每脚本独立可运行"契约**，不重写 184 个脚本

---

### R-13 🟠 高｜模型层未进入有效状态

**风险陈述**（报告级证据，需人工复核）

- `ModelAdmissionPolicy` 下 **0 个 active 模型**（12 observe + 2 disabled：`fuel_risk`、`front_pressure`）
- `rear_threat` / `attack_opportunity` / `front_attack_commit` 三个攻防主线模型**有模型文件但不在 `MODEL_NAMES`**，无旁路可视化
- `strategy_action_baseline_report.json` 的 `features` 指向 `/tmp/…` **临时目录**（不可复现）
- 24 份训练报告含**绝对 `model_path`**，不利资产迁移
- `rear_threat_baseline_report.json` 标注 v2/val=1012，与 v2 manifest `tactical_split_counts={train:44917, val:0, test:4970}` **矛盾**

**处置方案（降低）**

| 步骤 | 动作 |
| --- | --- |
| G1 | 将 3 个攻防模型加入 `MODEL_NAMES`，模式 **observe**，生成 `model-admission-evidence-v1` 证据文件（model sha / feature schema sha / context_window_version） |
| G2 | 修正全部绝对路径为可迁移相对解析（`model_assets.read_model_asset` 已具备 `require_manifest`） |
| G3 | 在 `training/exports/` 下重建 `strategylowfuel` 数据集，重跑并 `seal_report()` 重封资产 |
| G4 | 确认 `rear_threat` 报告的 split 来源，在报告中显式写 `validation_source` 字段 |

**新增回归**：`scripts/model_report_path_portability_regression.py`（断言报告无绝对路径 + 每个 runtime asset 有 manifest 且 sha 匹配）

**验收标准**：全部 runtime asset 有 manifest；报告零绝对路径；17 个（14+3）模型在 `MODEL_NAMES` 中

**工作量**：3 人日｜**依赖**：需先与 `retrain_current_models.py` 的 14 资产清单对齐

---

### R-12 🟡 中｜伪标签闭环（业务风险，不可纯技术修复）

**风险陈述**

manifest 标注 `label_provenance = {"kind":"rule_derived","human_validated":false}`，全部标签来自 `StrategyEngine` 的 assessment / risk_profile / messages。因此 `attack_opportunity` acc=0.9994、`front_attack_commit` acc=0.9999 等高分**只证明模型能复现现有规则，不证明优于规则**；同时存在"高 accuracy 与 r2=0.0 并存"的现象（`fuel_risk`、`front_pressure`）。

**处置方案（降低 —— 建立独立评估维度，不改训练链）**

| 步骤 | 动作 |
| --- | --- |
| H1 | 从 `uid15` / `uid16` 各抽 **100 帧**（覆盖 attack / defend / fuel-critical 三类场景），由领域专家独立标注 `primary_action_label` 与 `rear_threat_binary_label`，作为**独立 holdout** |
| H2 | manifest 增 `label_quality_tier`（`rule_derived` / `human_validated`）与 `not_for_mainline` 标记 |
| H3 | 对 5 个暂停模型输出 `not_for_mainline: true` |
| H4 | 3 个攻防模型报告新增"人工 holdout 指标"列，与伪标签指标**并列展示差异** |

**验收标准**：人工 holdout 指标产出；伪标签与人工标签的指标差异被量化

**工作量**：5 人日（含人工标注）｜**说明**：这是唯一能回答"模型是否真的优于规则"的路径，**越早开始越好**

---

### R-14 / R-15 🟡 中｜产品化阻断项

| ID | 风险 | 处置方案 | 工作量 |
| --- | --- | --- | --- |
| **R-14** | 无 AEC，外放环境上行被播报污染，仅靠 `voice_meter` 启发式门控 | ① 短期：文档明确要求"耳机或隔离回声输入环境"（已部分存在）；② 中期：引入 VAD 前置抑制 + 下行门控加强；③ 长期：接入平台 AEC API 或硬件回声消除 | 需实机标定 |
| **R-15** | macOS 强绑定（Swift 采集脚本 + `say`/`afconvert`/`afplay`/`ffplay`） | ① 收敛 Swift 脚本路径到 `asset_root/scripts`；② 抽象统一 `AudioBackend` 协议（`AlsaArecordInputBackend` 已存在，补 Linux 输出侧）；③ 非 darwin 平台 `env_ready()` 返回 **False 而非抛异常**，走 `Null*` 兜底；④ 为 Pi 5 / CM5 铺路 | 4 人日 |

---

### R-07 / R-08 / R-09 / R-10 / R-11 🟡 中｜工程收敛项

| ID | 处置方案 | 验收 | 工作量 |
| --- | --- | --- | --- |
| **R-07** | 删除 `asurada-core/build/`（`git ls-files` 为 0，确认无版本历史）；`.gitignore` 增 `build/` 与 `*.egg-info/` | `find . -name 'training_memory.py' -not -path './src/*'` 无结果 | 0.2 人日 |
| **R-08** | ① 删除 `packet_snapshot.py:550` 的 `auxiliary_packet_15`（`lap_positions` 完全重复）；② "只进 raw 不进决策"的整块子包改为按需展开，全量块由 `ASURADA_RAW_FULL_BLOCKS=1` 开关保留；③ 落盘前剥离全量块 | 同一抓包回放后 `session_log.jsonl` 字节数下降 ≥50%，且 `decision` 策略字段逐字段一致。**前置**：先 `grep -rn "raw\[" scripts/ src/` 建立字段消费清单 | 3 人日 |
| **R-09** | `SessionLifecycle._retired` 与 `ConsoleVoiceOutput._retired_sessions` 改为容量 256 的 FIFO 有界容器；淘汰时递增 `tombstone_evictions` 计数 + 打日志 + 暴露到健康快照 | 注入 300 个 session，断言集合 ≤256、淘汰计数 =44 | 1 人日 |
| **R-10** | 新建 `src/asurada/limits.py` 集中 `IPC_MAX_MESSAGE_BYTES=4<<20`、`SIDECAR_JSON_BODY_MAX=16<<20`、`DASHBOARD_PAYLOAD_MAX=2<<20`、`INGRESS_QUEUE_CAPACITY=512`、`ANALYSIS_STEP_SIZE_LIMIT=16384` 等，替换散落字面量 | `scripts/limits_single_source_regression.py` 断言字面量不再出现在其他位置 | 1.5 人日 |
| **R-11** | 旧 `_arbitrate` 加开关 `ASURADA_LEGACY_ARBITER`，默认仅在 `ordered_actions` 为空时启用；对该回退路径加计数与日志 | `scripts/arbiter_channel_parity_regression.py` 断言两通道均非空时最终 messages 完全一致 | 2 人日 |

---

### R-16 ~ R-20 🟢 低｜接受 + 监视

| ID | 处置 | 工作量 |
| --- | --- | --- |
| **R-16**（取消 ≠ 已停止） | `PlaybackControl.cancel()` 已真实 kill 播放进程并 close response；补 `stop_confirmed(handle) -> bool` 语义，超时未确认则显式输出 `stop_unconfirmed` 事件，使该状态**可观测** | 0.5 人日 |
| **R-17**（speed trap 未解析） | `_decode_lap_data_car` 补 `speed_trap_fastest_speed`（offset 52, `<f`）与 `speed_trap_fastest_lap`（offset 56, `u8`），同步更新两份字段文档 | 0.5 人日 |
| **R-18**（数据可复现性） | 保持现状；在 README 显式标注"仅本机可复现"，交接文档持续维护 | — |
| **R-19**（暂停模型留存） | 保持 blocked 状态，报告标注 `not_for_mainline`；不额外投入 | — |
| **R-20**（文档进度不一致） | 统一根 `README.md` 与 `PROJECT_PROGRESS.md` 的 Phase 3 数字（10% vs 35%） | 0.2 人日 |

---

## 5. 实施路线图

| 阶段 | 周期 | 交付项 | 门禁条件 |
| --- | --- | --- | --- |
| **阶段 0 · 止血** | Day 1 | R-01、R-07 | `packet_decode_resilience_regression` 全绿；畸形包注入回放 30 分钟不中断 |
| **阶段 1 · 语义修正** | Week 1 | R-02（先决策）、R-03、R-04 | 3 个新回归全绿 + 差分回放归因完成 |
| **阶段 2 · 工程收敛** | Week 2–3 | R-06、R-10、R-09、R-08 | pytest 可跑 184 回归；limits 单源断言通过；日志体积下降 ≥50% |
| **阶段 3 · 模型与协议** | Week 3–4 | R-13、R-17、R-11、R-12 启动 | 17 个资产有 manifest；报告零绝对路径；人工 holdout 指标产出 |
| **阶段 4 · 产品化前置** | Week 4+ | R-14、R-15、R-16 | 非 darwin `env_ready()` 全 False 且不抛异常；`stop_confirmed` 有回执 |
| **阶段 5 · 结构收敛** | 待定 | R-05 | 拆分前后 `session_log.jsonl` 逐字节一致 |

### 执行纪律（硬约束）

1. **顺序不可颠倒**：`R-01` 必须先于 `R-03`；`R-01` ~ `R-04` 必须先于 `R-05`。
2. **行为变更必须差分**：`R-02`（真实开始抑制）、`R-04`（收紧新鲜度）、`R-08`（raw 瘦身）三项都会改变输出，**必须**先跑同抓包差分回放，把每处差异归因清楚再合入。
3. **不得依据过期文档施工**：既有评审文档中 `interaction.py` / `response_composer.py` 的行数、以及部分 P0 缺陷描述均已过期（详见第 6 节）。
4. **保留既有契约**：`R-06` 只加发现 / 并行层；`R-05` 只做纯结构拆分。
5. **每项修复必须有对应回归脚本**，并在 `output/architecture-implementation/` 生成 `summary.json`，维持项目既有的证据驱动传统。

---

## 6. 已关闭风险（审计记录 —— 避免重复施工）

以下 7 项在既有评审文档中列为 P0 / P1，**经代码回验已修复**，不应重复投入：

| 原缺陷 | 当前状态 | 回验证据 |
| --- | --- | --- |
| 燃油结论不一致（核心 critical / 查询"正常"） | ✅ 已修复 | `capabilities/resources.py:15-22` 直接调用 `assess_fuel(state).describe()`；`response_composer.py:3` 亦导入 `assess_fuel`，不再自建阈值 |
| 缺失 sidecar 分数被当 0 触发"低风险"减分 | ✅ 已修复 | `arbiter.py:389-397` 返回 `None`；`:423-432` 全部 `is not None` 守卫；`:381-387` 显式注释；有 `arbiter_missing_scores_regression.py` |
| `interrupt=true` 未被输出队列消费 | ✅ 已修复 | `output.py:557` 写入 metadata；`:625-639` 执行真实抢占（`cancel_requested` + `_request_stop_confirmation`） |
| sidecar `stop()` 是空操作 | ✅ 已修复 | `tts_backends.py:236-238` → `PlaybackControl.cancel()`；`playback_control.py:48-60` `terminate()`→`kill()` + `response.close()` |
| LLM 超时不能及时返回 | ✅ 已修复 | `llm_explainer.py:465` 改用 `context.wait()`；`task_runtime.py:46-56` 以 `min(remaining, 0.01)` 轮询，到期抛 `TimeoutError`；`:55` 拒绝交付迟到结果 |
| `UnifiedStateStore` history 无场次隔离 | ✅ 已修复 | `state.py:23-24` 在 `last_transition.changed` 时 `self._history.clear()` |
| 24 份报告含绝对 `model_path` | ⚠️ 待复核 | 已并入 R-13 G2，需实跑 `grep -rln '"/Users/\|/tmp/' training/reports/*.json` 确认 |

---

## 7. 残余风险与需人工验收项

以下风险无法通过静态分析或代码修复消除，**必须在真实环境验收**：

| ID | 残余风险 | 验收方式 |
| --- | --- | --- |
| A1 | 取消请求后云端 TTS 是否真正停止合成 | 真实 Doubao 端点 + 抓包观测上游连接关闭时序 |
| A2 | 无 AEC 下的误唤醒率与回声自触发率 | 实车外放环境，统计误唤醒 / 分钟 |
| A3 | 畸形包防护在真实 UDP 丢包 / 乱序下的有效性 | 长时实机运行 + 抓包统计 `decode_degraded` 比例 |
| A4 | 模型相对规则的真实收益 | 人工 holdout（R-12）指标对比 |
| A5 | Pi 5 / CM5 上的端到端时延与负载 | 目标硬件实测 |

---

## 8. 附录：扫描方法与证据索引

### 8.1 方法

1. 逐文件阅读关键路径源码（`pdu_decoder` / `runtime_pipeline` / `live_runtime` / `app` / `arbiter` / `fallback` / `state` / `session_lifecycle` / `task_runtime` / `playback_control` / `tts_backends` / `output` / `capability_*` / `packet_snapshot`）
2. 文本检索验证字段使用面与死代码（`last_emitted_action` / `suppression_window` / `_retired_sessions` / `PacketDecodeError` / `_ns_to_ms` / `interrupt`）
3. 实测命令：`wc -l` 统计文件规模、`git ls-files | grep build/` 确认跟踪状态、`diff` 比对 `build/` 与 `src/` 漂移
4. 对既有评审文档逐条回验，区分"仍存在"与"已修复"

### 8.2 关键证据锚点

| 风险 | 文件:行 |
| --- | --- |
| R-01 | `pdu_decoder.py:122`、`:133`、`:451-455`、`:595`；`live_runtime.py:55-60`；`app.py:129-146` |
| R-02 | `arbiter.py:225`；`fallback.py:43-47`、`:88-99` |
| R-03 | `pdu_decoder.py:173-174`、`:168-171`（同类事故注释） |
| R-04 | `capability_definitions.py:64-74` |
| R-05 | `wc -l` 实测（29,178 行总量） |
| R-06 | `pyproject.toml`；无 `.github`；`scripts/run_regressions.py` |
| R-07 | `build/lib/asurada/training_memory.py`、`build/lib/asurada/review_capture.py` |
| R-08 | `packet_snapshot.py:533-550`（`:550` 为重复字段） |
| R-09 | `session_lifecycle.py:23-25`；`output.py:90-92`、`:123` |
| R-11 | `strategy.py:918`、`:950-973` |
| R-13 | `model_admission.py`；`training/reports/*` |
| R-17 | `pdu_decoder.py:62`、`:437-443` |

---

## 9. 一页速览

```text
立即（Day 1）      R-01 解码异常终止实时循环 ─────────── 1.5 PD  ← 最高优先
                   R-07 清理 build/ 漂移 ─────────────── 0.2 PD
Week 1             R-02 仲裁冷却死代码（接通 or 删除）── 0.5~2 PD  ← 需先决策
                   R-03 Session 定长放宽 ─────────────── 1.0 PD
                   R-04 capability 时效分级 ──────────── 1.5 PD
Week 2-3           R-06 引入 pytest + CI ────────────── 2.0 PD
                   R-10 limits 单源 ─────────────────── 1.5 PD
                   R-09 墓碑有界 ────────────────────── 1.0 PD
                   R-08 raw 瘦身 ────────────────────── 3.0 PD
Week 3-4           R-13 模型准入 + 资产可迁移 ───────── 3.0 PD
                   R-12 人工标注小集（关键，建议尽早启动）5.0 PD
Week 4+            R-14 / R-15 产品化前置 ───────────── 4.0 PD
待定               R-05 巨型文件拆分（须排在最后）──── 8.0 PD
```

### 三条最关键结论

1. **`R-01` 是唯一会导致真实比赛中策略脑直接退出的缺陷，且修复成本最低（1.5 PD）—— 必须最先做。**
2. **`R-02` 必须做出"接通或删除"的显式决策**，不能让死分支继续伪装成已生效的防抖能力。
3. **`R-12` 的人工标注小集是打破"模型只复现规则"循环的唯一路径**，是决定阶段二价值能否成立的关键，越早启动越好。

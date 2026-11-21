# Asurada：Ollama 云 GPU 租赁与模型选型验证方案 v1.0

**日期**：2026-10-28  **状态**：待执行的实验计划，所有价格和性能需在下单时复核。  **目的**：先确定人格模型的效果与资源需求，再购买 Orin、Thor 或桌面 GPU 主机。

## 1. 关键决策

- 本轮只租用 GPU 进行 **模型质量、推理接口、上下文设计和网络容错** 测试，不以云端 RTX 的速度预测 Jetson 性能。
- 首选 Ollama 作为快速原型推理接口，保留 `LLMProvider` 抽象；将来可替换为 llama.cpp、TensorRT-LLM 或其他 ARM64 推理后端。
- 游戏 PC 与 Asurada Core 本地运行；云端只接受经过脱敏、限量的对话上下文、人格状态和比赛快照，不接管实时策略、SpeechScheduler、音频设备或长期记忆主库。
- 先试 4B、8B、14B 三档，32B 仅作为可选质量上限。具体模型版本、量化标签、许可证、thinking 模式、上下文长度、随机种子在实验开始前冻结并写入清单。
- 优先租用一张 24GB 显存的 RTX 3090/4090 类实例作为测试环境；云平台可比较 RunPod 与 Vast.ai，**价格按实际结算页面确认**。不要把之前讨论中的小时价当作报价保证。

## 2. 网络与部署拓扑

```text
F1 25 -> UDP -> Asurada Core -> StrategyEngine -> deterministic speech -> local TTS
                          |                     (never waits for cloud)
                          +-> RaceEvent / PersonalityRuntime / DialoguePolicy
                                             |
                                    bounded async LLMProvider
                                             |
                                  SSH tunnel / private VPN
                                             |
                                  rented GPU: Ollama
                                             |
                             validated text -> local SpeechScheduler
```

- 云端 Ollama 默认绑定 127.0.0.1:11434；**不要把 11434 裸露到公网**。采用 SSH 隧道或私有网络并启用主机鉴权、实例防火墙。
- 测试环境不得上传账户凭据、原始个人隐私数据或未经筛选的日志；记录传输数据类别与保留期限。
- 服务调用使用 request_id、turn_id、session_id、snapshot_id、deadline、cancel_token；请求失效或遥测状态变化时直接丢弃晚到响应。
- 本地保留确定性模板；断网、超时、云端错误、模型胡编时均不阻塞策略和语音播报。

## 3. 建议的试验矩阵

| 维度 | 实验变量 | 输出证据 |
|---|---|---|
| 模型 | 4B / 8B / 14B；可选 32B | 模型精确标签、哈希、量化、许可证 |
| 上下文 | 仅当前比赛快照 / +人格情绪 / +历史记忆 | 对话样本、质量差异 |
| 成长 | H0/H1/H2/H3 同一场景 | 人格一致性、幽默时机 |
| 场景 | 最快圈、失误、进站、轮胎、比赛风险、闲聊、长回合 | 正确率、越权率、幻觉率 |
| 负载 | 冷启动、热启动、单请求、并发 2、网络抖动 | TTFT、token/s、p50/p95/p99 |
| 故障 | 云端超时、断连、晚到、重复请求、取消、输出非法 JSON | 降级与状态机日志 |
| 表达 | 纯模板 / LLM 改写非关键句 / 混合 | 盲评结果、人工评分 |

建议建立至少 60 条带标准事实的回放样例，覆盖正常、边界、紧急、关系成长四类；关键样本固定种子重复 3 次。评价者盲评“自然度、中文流畅度、角色一致性、幽默是否恰当、事实准确性、冗余程度”，分别打分；**事实错误、紧急信息被改写为一票否决项**。不把主观评分伪装成硬件跑分。

## 4. 指标、日志和候选门槛

- `ttft_ms`, `tokens_per_second`, `generation_total_ms`, `model_load_ms`, `network_rtt_ms`, `request_timeout_rate`, `late_response_drop_rate`, `cancellation_success_rate`。
- 全链路增加 `asr_final_to_tts_first_audio_ms`, `telemetry_packet_age_ms`, `strategy_latency_p99_ms`, `speech_preemption_latency_ms`。
- 每次样本保存：git commit、模型版本、量化、prompt_version、采样参数、输入事实、模型原文、校验结果、TTS 结果、资源占用与时间戳。
- **候选目标（非实测）**：普通问答首段播报 1–2 秒为探索性目标；关键策略警告不等待云端；LLM 失败 100% 可降级；禁止输出未经校验的关键数值。
- 若网络 RTT 或冷启动影响体验，改用本地模板、预热模型或更短的输出；不要用云端 TTFT 直接定 Jetson 采购规格。

## 5. 部署与测试步骤

1. 在 RunPod/Vast.ai 核对实例的 GPU 型号、显存、CPU/RAM、磁盘、网络、镜像、账单及停止后存储费用；设置预算上限。
2. 使用官方 Ollama 安装方法安装服务，确认 `nvidia-smi`、`ollama --version`、`ollama list`；避免同一服务重复启动。
3. 仅在实例本机测试 `http://127.0.0.1:11434/api/generate`，然后建立 SSH 隧道；不要公开推理端口。
4. 分模型下载、记录准确标签与哈希；固定 `num_ctx`、`temperature`、`top_p`、`num_predict`、是否开启推理模式等参数。
5. 先运行离线回放与评分，再将 OllamaProvider 以旁路模式接入 Asurada；先不自动播报 LLM 输出。
6. 接入 `SpeechPersonalizer` 的非关键文本通道，启用校验、TTL、取消、回退；最后进行带 TTS 的真实端到端测试。
7. 测试后导出 CSV/JSONL、图表和结论；停止实例并检查持久磁盘和账单。

示例（实例内）：

```bash
nvidia-smi
ollama --version
ollama pull qwen3:8b
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:8b","prompt":"用一句简短中文祝贺车手刷新个人最佳圈速，不编造具体数据。","stream":false}'
```

本地安全隧道示例：

```bash
ssh -N -L 11434:127.0.0.1:11434 <user>@<gpu-host>
```

注意：实际模型标签和 Ollama API 参数以部署当日官方文档为准；使用云服务前评估数据安全与许可。

## 6. 预算与停止条件

- **探索性预算上限：20–30 美元**，不是保证完成所有实验的固定价格。按小时 GPU、存储、镜像、出站流量和税费计费；采用分阶段预算闸门。
- 第 1 关（2 小时）：环境、连通性、安全配置；失败即停止排障并记录原因。
- 第 2 关（6–10 小时）：4B/8B 质量对照；若效果不达标，先优化事件/提示词，不升级 GPU。
- 第 3 关（6–10 小时）：14B 对照和多轮记忆；只有质量收益明显时才进入更大模型。
- 第 4 关（按剩余预算）：云故障、取消、真实语音链路与结果复盘。
- 每阶段必须停止不必要的 GPU 实例并确认是否仍收取存储费。

## 7. 硬件采购决策门

- 4B 达标：先评估 Orin NX 16GB；但需真机内存与并发测试。
- 8B 达标：Orin NX 16GB / AGX Orin 64GB 均列入真机测试，不直接承诺性能。
- 14B 有明显且稳定的质量收益：优先验证 AGX Orin 64GB，并用 x86 RTX 作性能对照。
- 32B 才达标：重新比较 Thor、x86 RTX 的成本与性能；Thor 不是默认采购项。
- 无模型达标：回到人格策略、记忆证据、事实绑定与评测集设计，不以堆硬件替代架构修复。

## 8. 交付物与验收

`experiment_manifest.yaml`、`cases.jsonl`、`results.jsonl`、`metrics.csv`、`evaluation_report.md`、`model_selection_decision.md`、`hardware_shortlist.md`、故障日志与可重放脚本。以上是计划交付物，当前未执行实验。

参考导航：Ollama https://ollama.com/ ；RunPod https://www.runpod.io/ ；Vast.ai https://vast.ai/ 。

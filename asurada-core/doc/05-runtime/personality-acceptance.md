# Asurada 人格手动验收

在 `/Users/sn5/Asurada/asurada-core` 运行下列命令。手测档案、日志和语音服务与日常运行分开。

## 短回放

```bash
cd /Users/sn5/Asurada/asurada-core
replay_dir="$(mktemp -d /tmp/asurada-personality-replay.XXXXXX)"
.venv/bin/python scripts/personality_acceptance_regression.py --write-capture "$replay_dir/scenes.jsonl"
ASURADA_RUNTIME_DIR="$replay_dir/logs" ASURADA_PERSONALITY_ENABLED=1 \
  ASURADA_LLM_SIDECAR_ENABLED=0 ASURADA_TTS_BACKEND=null \
  .venv/bin/python -m asurada --capture-jsonl "$replay_dir/scenes.jsonl"
open "$replay_dir"
```

- 回归 JSON 的 `trajectory` 列出情绪轨迹。第 11 秒碰撞将担忧增至 0.85，重发同一包只算一次。第 12 秒最快圈提高兴奋值。第 42 秒担忧自然衰减，第 10 秒的闪回分支撤销之后的情绪。
- `checks` 验证安全车抢占问答、重复查询各自排队、静默后端、危险和过期场景拦截、赛果去重与 H0–H3 晋升。H3 示例只引用样本中已验证的最快圈。自动测试的关系库随用例清理。
- `logs/session_log.jsonl` 每条已接受的快照可查看 `personality` 和 `debug.runtime_timing`。闪回等待真实新分支时暂停发布人格，策略继续运行。

用 macOS 当前语音后端试听回放场景和赛后短评：

```bash
ASURADA_TTS_BACKEND=say .venv/bin/python scripts/personality_acceptance_regression.py --listen
```

试听脚本不等待比赛自然发生，它在回放快照上向同一个结构化回答入口提问。抢占、过期和阶段阈值用前面的回归命令检查。

## 进站建议人格回放

同一组归一化赛车快照通过策略引擎与语音调度，分别固定在 H0 至 H3。

```bash
.venv/bin/python scripts/personality_pit_advice_regression.py
```

- 已播放完成的轮胎磨损进站建议才会进入跟进。连续磨损高位 12 秒后，在驾驶负荷低且语音空闲时最多坚持一次。
- 匹配当前建议的明确同意或拒绝会停止催促，包括正在播放的催促。遥测证实需要更正时仍可播报。未明确同意的换胎会留下遥测证据，采纳字段保持为否。
- 观察到进站及换胎证据后，稳定读数确认满 2 秒再收回原建议。同一套轮胎、未进站且四轮读数分别回落至少 10 个百分点时，二次确认后承认之前的判断有误。缺少可信套号时保持克制。
- 测试让失稳和安全车提示分别打断跟进台词，检查被打断的语音和新语音的生命周期。实体耳麦首音与停音仍以音频测量为准。

## 阿斯拉达中文声线

为共享语音服务配置 `ASURADA_PERSONALITY_VOICE_DIR`，指向本机声线目录。目录内包含 `.venv/bin/python`、`model/`、`reference.wav` 和预生成的 `cache/`。本次安装在 `~/.asurada/voice/asurada-zh-v1`。语音进程还需要 `ffmpeg` 和 `afplay`。

- 人格台词优先播放本地预生成音频。其余人格表达使用独立可取消进程合成，语速和停顿沿用已选试听参数。
- 动态失稳、安全车和红旗的常用短句预生成。未命中音频的紧急消息走现有即时后端。
- 平静、坚定、关怀、兴奋使用同一声线和原速。平静保留原读法，坚定突出结论，关怀保留略长的自然停顿，兴奋缩短停顿并加强重音。紧急短句和已确认的进站台词使用原节奏。
- 姓名在整句里用原声线合成。合成输入用同音的「笋」标注 sǔn，台词和日志仍显示「隼人」。含姓名的旧拼接缓存自动失效。坚定提示用「注意」引出具体风险。进站建议及其更正、紧急短句保留原节奏。
- 点播时校验 WAV 和播报长度。原模型输出达到长度上限时会重新合成，失败时不会提交残缺或超长音频。紧急缓存失效时使用即时备援。
- 语音生命周期的 `metadata.render_voice`、`render_delivery`、`render_rate`、`render_follow_rate` 记录实际路由和两段的目标节奏。进程停止确认与真实耳麦停音属于不同测量。

## F1 25 与耳麦

让 F1 25 向 Asurada 所在主机的 UDP `20778` 端口发送遥测。用第一条命令创建本次手测目录，将打印出的实际路径填到两个终端的 `ASURADA_CHECK_DIR`。如果之前的核心占用了 `20778`，先正常退出它。

```bash
mktemp -d /tmp/asurada-personality-live.XXXXXX
```

终端 A 启动核心和独立的共享语音服务：

```bash
cd /Users/sn5/Asurada/asurada-core
export ASURADA_CHECK_DIR=/tmp/asurada-personality-live.填写实际目录
export ASURADA_RUNTIME_DIR="$ASURADA_CHECK_DIR/logs"
export ASURADA_RELATIONSHIP_DB="$ASURADA_CHECK_DIR/relationship.sqlite3"
export ASURADA_PERSONALITY_ENABLED=1 ASURADA_LLM_SIDECAR_ENABLED=0
export ASURADA_TTS_BACKEND=say
.venv/bin/python -m asurada.speech_service --socket "$ASURADA_CHECK_DIR/voice.sock" \
  --session-source "$ASURADA_RUNTIME_DIR/latest_snapshot.json" &
asurada_check_speech_pid=$!
export ASURADA_SPEECH_SOCKET="$ASURADA_CHECK_DIR/voice.sock"
while [ ! -S "$ASURADA_SPEECH_SOCKET" ] && kill -0 "$asurada_check_speech_pid" 2>/dev/null; do sleep 0.1; done
.venv/bin/python -m asurada --live-udp --udp-port 20778
kill -TERM "$asurada_check_speech_pid"
```

终端 B 启动手动语音测试。macOS 首次运行可能提示授予麦克风和语音识别权限。

```bash
cd /Users/sn5/Asurada/asurada-core
export ASURADA_CHECK_DIR=/tmp/asurada-personality-live.填写实际目录
export ASURADA_RUNTIME_DIR="$ASURADA_CHECK_DIR/logs"
export ASURADA_SPEECH_SOCKET="$ASURADA_CHECK_DIR/voice.sock"
export ASURADA_PERSONALITY_ENABLED=1 ASURADA_LLM_SIDECAR_ENABLED=0
.venv/bin/python scripts/phase3_macos_voice_loop.py --session-log "$ASURADA_RUNTIME_DIR/session_log.jsonl" \
  --recognizer-backend macos_speech \
  --manual --disable-wake-word --show-processing-json
```

| 场景 | 检查点 |
|---|---|
| 戴耳麦问两次「轮胎状态」 | 两次是独立请求。冷静时简短播报同样的结构化事实。 |
| 轻微碰撞后问「车损情况怎么样」 | 担忧语气出现，原回答的车损值不变。紧急策略文本原样播出。 |
| 查询播报期间进入安全车状态 | 查询停下后播报安全车提示，耳麦中没有重叠。 |
| 播报完成后说「重复」 | 播出最近一次完成的可复述内容。刚排队、被取消或幽默台词不进入复述记录。 |
| 完成赛事并安全减速 | 满足低负荷且空闲时，可能听到一条简短完赛幽默。密集攻防、危险或数据不新鲜时保持静默。 |
| 同一组问题分别开启和关闭幽默 | 完成试验后重启两个终端，在终端 A 加上 `ASURADA_HUMOR_ENABLED=0`。确定性语气继续生效，幽默停止。 |
| 到达 H2 后说「开个玩笑」 | 低负荷和冷却满足时用短句回应。到 H3 才能回调档案里已核实的超车或最快圈。 |

核心关闭后可用手测专用库检查成长并重置：

```bash
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" status
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" history
# 需要确认一场已核实赛事时，把 UID 替换为 history 显示的 race_id。
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" acknowledge 比赛UID
# 需要回到 H0 时执行。此命令清空指定手测档案。
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" reset
```

`submit_to_backend_start_ms` 记录提交至后端接受，`stop_confirmed_ms` 记录后端确认停止。二者可在语音生命周期日志中查看。耳麦实际首音和停音以录音或听感为准。

## S6 旁路模型

共享语音服务读取 `ASURADA_PERSONALITY_LLM_MODE`。默认 `disabled` 使用模板。`shadow` 继续即时播模板，并在后台统计模型结果。`enabled` 只为驾驶负荷低、正常幽默强度、H2 及以上的超车、最快圈和完赛附加经过校验的短语。模型请求预算为 600 毫秒，沿用主动机会的两秒有效期。失败且机会仍有效时使用模板，失效时取消。

本机验证使用 `ASURADA_PERSONALITY_LLM_MODEL=qwen3:8b` 和默认的回环地址。共享语音 IPC 的 `health.personality_llm` 可查看模式、未完成请求及结果计数。生命周期中的 `metadata.personality.model` 记录启用模式下实际采用模型或回退的原因与耗时。回退到模板时重启共享语音服务并恢复 `disabled`，沿用原有关系与证据库。

    .venv/bin/python scripts/personality_model_regression.py
    .venv/bin/python scripts/personality_model_delivery_regression.py
    .venv/bin/python scripts/personality_s6_scenario_matrix.py --model qwen3:8b
    .venv/bin/python scripts/personality_model_delivery_regression.py --benchmark

实跑先用 `shadow`。在同一场比赛的日志里对照实际播出的台词与方案，记录耳麦首音、人格播报被紧急提示抢占后的停音，以及语气盲听结果。模板通过回放和进程停止确认后，真人耳麦评估仍需单独记录。

## 查看和重建成长档案

```bash
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" progress
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/relationship.sqlite3" export --output "$ASURADA_CHECK_DIR/evidence.json"
.venv/bin/python -m asurada.personality_memory --db "$ASURADA_CHECK_DIR/reconstructed.sqlite3" rebuild "$ASURADA_CHECK_DIR/evidence.json"
```

`progress` 列出当前阶段、各类证据和下一档还缺的有效完赛或正向赛事。目标已满足时，阶段在下次核实完赛时更新。`export` 读取完赛、赛事中的正向事件和人工确认。重建按原记录顺序重放，并核对统计与阶段，仅生成新数据库。

## 赛中静默与幽默强度

连接共享语音服务后，可通过同一 Unix socket 即时调整本次运行的设置。

```bash
.venv/bin/python -m asurada.personality_controls --socket "$ASURADA_SPEECH_SOCKET"
.venv/bin/python -m asurada.personality_controls --socket "$ASURADA_SPEECH_SOCKET" --quiet on
.venv/bin/python -m asurada.personality_controls --socket "$ASURADA_SPEECH_SOCKET" --quiet off --humor low
```

静默会停下可选人格台词和重复坚持建议。紧急提示照常播出，已经给出的进站建议若被新证据推翻，仍会用简短台词更正。幽默有 `off`、`low` 和 `normal` 三档。低档减少调侃并延长冷却，关闭档不播幽默。服务重启后恢复默认设置。

## 进站建议的明确反馈与结果

在共享语音服务和权威实时遥测启用时，等进站建议播完，可以说「同意进站」或「我不进站」。可用表达还包括「我会进站」「我去换胎」「先不进站」和「拒绝进站建议」。仍使用当前语音入口的唤醒方式，普通的「好」不会产生采纳证据。

- 每条建议记录自己的 ID、播放开始与完成、策略决定和车手反馈。反馈窗口为建议后 120 秒，要求车还在赛道上、原磨损条件仍成立。相同语音 turn ID 幂等，进站前以最后一次明确反馈为准。
- 遥测独立记录进站信号、计数增长和更换轮胎的证据。出站后至少 2 秒的连续样本确认结果。观察最长 180 秒，闪回、新会话或权威遥测丢失终止待核对建议。
- 仅在播完、明确同意、随后确认进站换胎时标记采纳。车手没有回应时，实际换胎和磨损变化仍可查。结果只衡量轮胎磨损和磨损判定。

```bash
.venv/bin/python -m asurada.pit_feedback --limit 10
.venv/bin/python scripts/pit_feedback_regression.py
```

证据默认写入 `~/.asurada/pit-evidence.sqlite3`。共享语音服务可通过 `--pit-evidence-db` 或 `ASURADA_PIT_EVIDENCE_DB` 指定独立档案。语音处理结果中的 `queued` 表示交给异步写入，经落盘可用上述命令核对。

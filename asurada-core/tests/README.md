# 回归测试入口与证据

现有脚本自身的断言、JSON 报告和独立执行入口继续保留。`scripts/regression_runner.py` 统一负责发现、结果校验和子进程执行；CLI 和 pytest 不维护第二份完整脚本清单。

## 安装与执行

在 `asurada-core` 目录执行：

```sh
python -m pip install -e '.[dev,training,http-voice,dashboard,realtime-asr]'
python scripts/run_regressions.py --suite critical --parallel 4
python scripts/run_regressions.py --suite contracts --parallel 4 --timeout 300
python -m pytest -n auto tests/
```

`-n auto` 通过 xdist hook 限为最多 4 个 worker，避免每个测试再加载模型造成过量内存与线程；明确传 `-n N` 可覆盖。运行环境存在无关第三方 pytest 插件时，可用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p xdist.plugin -n auto tests/` 保持插件范围明确。

`--only script_stem`（CLI）与 `--regression-only script_stem`（pytest）都接受重复参数，拼错名称会直接失败。`--list` 只列出 CLI 所选脚本及串行原因；pytest 用 `--collect-only`。新增 `*regression.py` 自动纳入 contracts，PR 关键集合见 `scripts/regression_suites.json`，修改名称时缺项会被校验出来。

`contracts` 为可用仓库契约全量，默认排除依赖大型外部录制数据的 `phase1_regression.py`；`all` 保留包括该外部回放的原语义。缺少可选依赖/外部录制的脚本必须显式报告 skipped，跳过不计作实际验证通过。

模型编码回归在本机外部 capture 齐全时保留原先逐文件每 128 帧抽样；干净 CI 缺这些外部数据时使用仓库单帧 fixture 并报告 `replay_evidence=checked_in_frame_fixture`。两种证据均验证 14 个真实模型的编码边界一致性，fixture 不等于完整实录回放。外部 capture 较大时使用 `--timeout 300` / `--regression-timeout 300`；该重资源用例单独串行。

## 结果判定与隔离

- 子进程退出 0 和报告中的有效断言同时成立才通过。`passed: true` 不能遮蔽 `checks` 中的失败，空 checks、只打印 passed、没有报告都失败。
- 保留既有四种报告结构：具名 checks、顶层布尔断言、分组 checks、逐赛道断言。诊断数据中的业务 false 不解释为失败。
- 每个子进程独立 TMPDIR、运行日志目录和语音 socket；清除继承的 ASURADA 实时配置，限制原生计算库线程为 1。即使脚本使用固定临时文件名，也不会与另一个用例混用。
- 固定 TCP 测试端口和短实际时钟的取消/截止测试持有排他 flock；普通测试持共享锁。CLI 和 pytest 的不同 worker/不同运行实例使用同一仓库锁，串行规则不依赖 xdist 调度模式。
- 超时终止该测试自己的进程组并保留已输出内容，不杀真实应用进程。脚本必须自行清理刻意启动新会话的子进程；默认进程组隔离不能代替所有外部资源清理。
- 每个脚本保存 stdout、stderr、result.json；CLI 另有汇总 summary.json，pytest 可生成 JUnit XML。指定输出目录应为本次运行独占，避免覆盖另一轮同名用例证据。

## CI 范围

`.github/workflows/regressions.yml` 为 Linux/Python 3.9 和 macOS/Python 3.11 配置 PR/push 26 个关键契约，每日计划及手动触发运行所有发现的 contracts。退出失败会使 job 失败，报告保存 14 天。macOS 另安装 LightGBM 所需 libomp。

这里只定义远端运行配置。远端 workflow 实际成功、分支保护必需检查、真实游戏/麦克风/扬声器/硬件验收都需要各自直接证据，不能由本地 pytest 成功代替。未宣称测试覆盖率百分比；此改动提供适配与并行，不虚构 coverage 数据。

实现参考：[pytest 参数化](https://docs.pytest.org/en/stable/example/parametrize.html)、[xdist 并行和 worker hook](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)、[GitHub Actions workflow 语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。

新增源码行数门禁基于修复开始前的文件名单，仅限制新文件不超过 800 行；已有大文件继续在报告中列出，不因这轮改动而强行判失败。范围为有原始基线的 core/src、core/scripts、core/tests、live-dashboard、macos-voice、script，历史 tools 归档不在基线内。基线位于 scripts/source_size_baseline.json，不能靠刷新名单把本轮新大文件改称存量。

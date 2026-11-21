# Asurada 架构改进交付索引

当前状态：A01–A13 开发验证完成，U01–U04 等待隼人最终验收。iOS 暂缓，ESP 适配不做。

## 已接入的主要改动

| 范围 | 当前实现 | 工作包 |
| --- | --- | --- |
| 事实与决定 | 统一领域评估、快照绑定、决定内容身份、缺失值与来源语义 | A01/A04 |
| 实时链 | 有界采集、日志、观察和规划后台，队列丢弃与阶段时延可见 | A02/A05/A06 |
| 语音 | 实时入口共享声音服务，独立调度、抢占和过期；取消与停止确认区分；可选持续识别的口头停止 | A03 |
| 能力与回答 | 单一能力定义、权限/时效/schema；LLM 引用与数值校验；历史与比赛作用域隔离 | A07/A08 |
| 网页契约 | 快照/决定绑定、版本化语音及场次事件、来源状态、慢消费者隔离 | A09 |
| 复盘与训练 | 持久任务恢复、有限预算、圈弯对比、来源化记忆、训练草稿与后续圈关联 | A10/A11 |
| 模型治理 | 整场分割、连续预测窗口、统一特征、派生标签标识、资产/输入哈希 | A12 |
| 交付 | 全部契约回归、干净安装及修复后完整回放通过 | A13 |

## 当前开发证据（缺失值修复后）

- [182 个契约回归及覆盖核对](../output/architecture-implementation/a13-missing-fixed-contracts/coverage-audit.json)：182 通过、0 失败、0 跳过，源码哈希一致。
- [干净构建与安装](../output/architecture-implementation/a13-missing-fixed-wheel/summary.json)：11 项通过。临时源码构建 wheel，再安装到新虚拟环境；验证模块、资产、CLI、demo 和网页依赖。
- [训练资产与导出复核](../output/architecture-implementation/a12-completion-check/artifact-recheck.json)：14 个隔离资产及完整导出通过完整性核对，未启用模型。
- [逐工作包证据索引](../output/architecture-implementation/delivery-index.json)：连接 A01–A13 的要求与审计文件。
- [最终回放范围](../output/architecture-implementation/a13-missing-fixed-replay/verification-scope.json)：主抓包和重叠场次子集均无快照上限；主抓包 31,726 个快照及四个重叠场次子集全部通过，拒绝 0，输入哈希未变。

wheel SHA-256：`599a596684da0d8f683a571dd012792c45ea018756e0e0b51f4704b00c8e1ffd`。这是本地验证产物，未发布、推送或部署。

[最终完成审计](../output/architecture-implementation/final-completion-audit.json) 已核对 A01–A13 的要求和证据。

## 使用与验收边界

口头停止需显式 `--spoken-interrupt`、完整唤醒词和停止/取消指令，使用耳机或隔离回声输入。键盘 `s + Enter` 停止，`q + Enter` 退出。当前没有 AEC 算法；模拟识别和播放器通过不等于真实听音通过。

网页将连接通道与来源状态分开显示：`live`、`stale`、`future`、`unavailable`。默认源数据年龄超过 15 秒为 stale，持续传输旧数据不会刷新来源时间。

当前模型的规则、公式派生标签和遥测变化标签不等于人工驾驶质量真值。隔离重训、特征一致性和资产完整性通过，不构成生产启用许可或驾驶收益结论。

[最终用户验收任务](ASURADA_FINAL_USER_ACCEPTANCE_CN.md) 的 U01 真实比赛、U02 真实语音、U03 网页及 U04 复盘/训练价值全部保留，由隼人最终填写。开发侧不得代填实际体验通过。

详细过程见 [执行计划](ASURADA_ARCHITECTURE_IMPLEMENTATION_PLAN_CN.md)。

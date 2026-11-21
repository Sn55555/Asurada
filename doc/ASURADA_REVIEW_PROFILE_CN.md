# 本地复盘档案使用说明

此入口管理 Asurada 自己的本地驾驶员档案。driver-id 是调用者显式选择的档案，不是网络登录或身份认证。使用既有复盘任务数据库；不会修改 Codex 的用户记忆。

项目根目录的基础命令（路径和档案须替换为实际值）：

    PYTHONPATH=asurada-core/src asurada-core/.venv/bin/python -m asurada.review_profile --database /absolute/path/review.db --driver-id local-driver preferences

最后的 preferences 可替换为以下命令：

- set-detail brief：简略复盘；或使用 detailed。
- show --task-id review-task-id：读取指定复盘，应用当前偏好。
- record-performance --task-id review-task-id：从指定复盘核验并保存圈时观测。
- revoke-detail：撤销详略偏好，恢复默认详细展示。

set-detail 默认有效期 30 天，可用 --ttl-days 设置有限正值。重复设置仍有效的相同值不会延长有效期；修改值或过期后重新设置才开始新有效期。

show 校验任务已完成且属于该档案，读取当前未过期偏好。简略结果仍保留圈比较、训练草稿、后续观测、来源哈希、限制说明和完整报告位置。输出是对原始结果的展示，不会重新执行或改写持久任务，也不改变实时语音详略。

record-performance 从指定复盘所属的有效官方圈事实核对首尾圈时差，按 UID/epoch/赛道隔离，保存事实快照与原始来源。重复执行保持同一记录和到期时间。它验证的是观测数值；不证明驾驶能力提升、条件相同或训练的因果效果。圈数不足时返回 insufficient_laps，事实过期或匹配失败时明确报错。

当前 CLI 使用复盘数据库旁的 .memory.sqlite3 文件，符合默认复盘入口。通过 Python API 自定义记忆数据库的调用者应将同一 TrainingMemory 传入 present_review / record_performance，不能混用默认档案文件。

# 模型资产与人工验证边界

2026-09-16 核对：当前主目录的 24 个模型文件引用均已是相对路径，并有模型与特征 schema 的 SHA-256；运行时注册仍是 14 个，默认 12 observe、2 disabled、0 active。0 active 是当前没有生产准入批准的结果，不应通过批量激活或增加注册数量来“修复”。

`audit_model_assets.py` 逐个检查资产与运行时注册，列出历史数据路径是否仍存在。报告中的历史训练输入路径与运行时 `model_path` 不同：保留一个历史引用不保证该批训练仍可复现，删除绝对路径也不能恢复已丢失的数据。

从仓库根目录只读审计：

```bash
asurada-core/.venv/bin/python asurada-core/scripts/audit_model_assets.py \
  --output output/model-asset-audit.json
```

`--annotate-reports` 只补 `review_qualification`，不修改模型、指标、分区来源或准入模式。缺少训练时来源的旧报告标记 `label_quality_tier=unknown`，不会借用旁边某个新版 manifest 给旧权重补造来源。`human_holdout.metrics=null` 表示没有提交这项证据；`not_for_mainline=true` 表示这份审查尚不支持主线使用。真正 active 仍须原有 `model-admission-evidence-v1` 明确批准并绑定模型、schema、当前上下文窗口和评估说明。包装用 `model-asset-v1` 不代替这份批准。

## 完整导出的迁移

已有且通过当前完整导出校验的数据，可以复制成按 manifest 所在目录解析的包：

```bash
asurada-core/.venv/bin/python asurada-core/scripts/package_training_export.py \
  --dataset /实际/已验证的导出目录 \
  --output-dir /实际/尚不存在的目标目录
```

打包先校验全部六张表的计数、唯一记录、session 分区和 features/labels 对应关系，再复制并逐文件比较 SHA-256，完成后重新校验源数据没有变化。目标不得覆盖原目录。旧的、缺少当前身份/分区协议的导出必须先按当前 exporter 重新生成；打包器不会修写旧数据来绕过校验。

包内保留原 manifest 和原验证报告的原始来源信息，实际表路径使用 `path_base=manifest_directory`。它包含训练表，不包含原始遥测。移动目录后先运行 `validate_training_export.py /移动后的目录 --report /移动后的目录/validation.json`，或者使用会先执行同样校验的 `retrain_current_models.py`。本轮技术债处理没有执行训练，也没有发布或激活候选模型。

## 人工 holdout 仍需真正采集与标注

当前模型的高分可能来自规则蒸馏、公式 proxy 或遥测差值；这些指标不能直接称为人工验证收益。缺少来源的历史报告尤其不能推定标签种类。

独立验证应先冻结按整场 session 隔离的 holdout，并核对它未参与训练、调参或阈值选择，再让领域专家在看不到模型输出和伪标签的情况下标注。风险方案指定的 uid15/uid16 已用于旧模型的 train/val/test，不能只从这些文件抽取 200 帧，就宣称得到了新的独立 holdout。

人工标注至少记录：`record_id`、`session_uid`、`session_epoch`、前后文范围、`primary_action_label`、`rear_threat_binary_label`、标注人、复核状态、分歧原因；无法从现有证据判断时应允许 `uncertain`。完成后将相同 holdout 上的规则结果与模型结果并列统计，保留训练/评估数据哈希。未提供人工答案、有效样本覆盖和独立性证据前，这项验收保持待人工完成。

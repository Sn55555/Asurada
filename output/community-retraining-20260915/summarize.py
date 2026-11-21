# -*- coding: utf-8 -*-
import json
from pathlib import Path
O=Path('/Users/sn5/Asurada/output/community-retraining-20260915');R=O.parents[1];new=json.loads((O/'models/retraining-report.json').read_text());old=json.loads((R/'output/architecture-implementation/a12-current-retraining/retraining-report.json').read_text());assert new['passed'] and len(new['assets'])==14
oldassets={a['model']:json.loads(Path(a['report']).read_text()) for a in old['assets']};comparison=[]
for a in new['assets']:
 d=json.loads(Path(a['report']).read_text());b=oldassets[a['model']];k='top1_accuracy' if a['model']=='strategy_action' else 'r2';score=d.get('metrics',d)[k];before=b.get('metrics',b)[k];comparison.append({'model':a['model'],'metric':k,'previous':before,'retrained':score,'difference':score-before,'report':a['report']})
(O/'model-comparison.json').write_text(json.dumps(comparison,indent=2));assert all(x['difference']==0 for x in comparison)
c=json.loads((O/'community-experiment/report.json').read_text());v=json.loads((O/'community-experiment/verification.json').read_text());audit=json.loads((O/'data-audit.json').read_text());status=json.loads((O/'run-status.json').read_text());assert status['exit_code']==0 and not status['changed_code_during_run'] and not audit['hash_failures']
lines=['# 新增赛道数据补查与隔离重训报告','',
'日期：2026-09-15。所有新产物位于本目录；没有替换运行时模型、修改默认模型准入或更改主线程源代码。',
'',
'## 结论',
'',
'原 14 个模型已在原有 6-session 数据快照上重新训练，14/14 产物完成校验，指标逐项复现上一轮。社区 27 布局数据不具备这 14 个模型所需的完整物理字段与标签，未伪造字段合并。另完成一个明确独立的社区短距车速变化实验，使用新增数据，并按物理赛道分组留出验证。它不是原 14 模型中的任何一个，也不属于已经上线的功能。',
'',
'## 数据与接入调查',
'',
'- 社区数据：27 个布局、81 圈，所有文件 SHA-256 与清单匹配；清单采样数合计 195,467，不等于完整 UDP 状态行。',
'- 81/81 圈含速度、刹车、油门、转向、挡位、DRS；65/81 圈含四轮胎温。ERS 字段名虽存在，但本次检查没有非空 ERS 数组，纠正此前“部分文件含 ERS”的表述。',
'- 不包含现有模型所需的完整轮速滑移、车身姿态、胎耗、燃油、官方前后差距和比赛事件标签。胎温不能代替胎耗，转向不能代替横向加速度。',
'- 现有社区入口 fetch_f1laps_track_telemetry → build_f1_25_track_semantics：距离归一化、5 m 重采样、多圈中位数、刹车/弯心/出弯分段。27 布局中 24 个生成、3 个保留已有配置。',
'- 现有训练入口 export_phase2_training_data 默认读取 phase2_dataset_v2_extended 配置，其 phase2_metadata_combined.json 和 sample_splits 仅选 6 个完整状态 session。训练器没有社区遥测转换入口。',
'- 两份原始 UDP 录像逐包头核对：发现的有效 track_id 只有上海 2 和铃鹿 13。上海原录像还有未选入清单的练习及短 session，不能据此称原始所有 session 均已训练；其完整性与标签资格尚未验收，本轮未加入。',
'',
'## 对现有 14 模型的新增数据适配结论',
'',
'| 模型组 | 缺少的关键证据 | 本轮处理 |','|---|---|---|','| fuel_risk | 燃油、剩余比赛圈数、风险标签 | 原数据隔离重训 |','| ers_risk | 非空能量状态、对手状态、比赛上下文 | 原数据隔离重训 |','| tyre_risk、两个未来趋势 | 磨损、胎龄、连续 stint 和滑移 | 原数据隔离重训 |','| dynamics_risk、三项驾驶质量 | 车身运动、滑移、过载/不稳标签所需字段 | 原数据隔离重训 |','| 三项对手压力、defence_cost | 官方差距、对手状态、攻防上下文 | 原数据隔离重训 |','| strategy_action | 比赛动作标签及完整输入 | 原数据隔离重训 |',
'',
'## 原 14 模型重训对比',
'',
'| 模型 | 指标 | 上轮 | 本轮 | 差值 |','|---|---|---:|---:|---:|']
for a in comparison:lines.append(f"| {a['model']} | {a['metric']} | {a['previous']:.6f} | {a['retrained']:.6f} | {a['difference']:.6f} |")
lines+=['',
'这组比较证明重复训练可复现，不证明新增赛道泛化提升。输入表已复制并哈希记录；6 个训练阶段退出码为 0、14 个资产完成训练来源与清单校验，训练期间监测的源码哈希无变化。',
'',
'燃油测试目标共 5,071 行，全部为 20；前车压力测试目标 5,071 行全部为 0，官方前车差距非空行数为 0。两者 R²=0 是恒定标签下的退化评价，不能解释为模型已验证有效或确定无效。应增加包含不同风险/前车情形的独立测试 session。未来抓地代理目标 R² 仍为负，尚不支持接管决策。',
'',
'## 使用社区数据的独立实验',
'',
'目标：由当前及此前 10 m、30 m 的六个通道，预测前方 50 m 的车速变化。算法为 LightGBM 回归；18 个输入，只选当前位置以前的观测，不使用未来语义分段、圈排名或未来操作。未来车速标签在原始距离轴插值得到，按 10 m 网格取样；这是距离窗口，不是固定秒数。',
'',
'按物理赛道确定性划分，正反向布局始终在同一集合，整圈留出，避免相邻采样点随机拆分。训练 16 布局/25,339 行，验证 5 布局/6,622 行，测试 6 布局/8,912 行（18 圈、5 个物理赛道）。测试布局：阿布扎比、加泰罗尼亚、墨西哥、蒙特利尔、银石、银石反向。超参数与迭代数仅使用验证集，未根据测试结果调整。',
'',
'| 方法 | MAE km/h | RMSE km/h | 未来车速 R² |','|---|---:|---:|---:|']
for k,label in [('model','LightGBM'),('persistence','保持当前车速'),('linear','过去 30 m 线性外推')]:
 a=c['test'][k];lines.append(f"| {label} | {a['mae_kph']:.3f} | {a['rmse_kph']:.3f} | {a['r2']:.4f} |")
lines+=['',f"相对保持车速，MAE 降低 {(1-c['test']['model']['mae_kph']/c['test']['persistence']['mae_kph'])*100:.1f}%；相对线性外推降低 {(1-c['test']['model']['mae_kph']/c['test']['linear']['mae_kph'])*100:.1f}%。六个测试布局均优于保持车速基线。车速变化量本身的 R² 为 {v['delta_r2']:.4f}，避免只报告车速绝对值的高 R²。", '',
'| 测试布局 | 模型 MAE km/h |','|---|---:|']
for t,a in c['per_track'].items():lines.append(f"| {t} | {a['metrics']['model']['mae_kph']:.2f} |")
lines+=['',
'局限：总体绝对误差 P95 为 43.72 km/h；前方 50 m 降速超过 30 km/h 的 1,225 个点，MAE 为 28.86 km/h。当前没有未来赛道几何输入，尤其难以提前判断尚未开始的制动。只能说明存在短距预测信号，不能输出最优刹车点、圈速收益或安全指令。排行榜优选圈、同圈相关采样、驾驶者身份未分组、插值目标均限制泛化；未验证普通驾驶、雨天、不同车辆设置、真实运行时和比赛策略。',
'',
'## 下一步实现优先级',
'',
'1. 保留社区数据作为独立 reference/forecast 数据源，明确字段缺失，禁止把缺失物理量填成零并生成训练标签。',
'2. 驾驶教练先做同赛道距离对齐的参考圈比较；优化建议需对圈段损失与实际练习效果单独验证。',
'3. 为 fuel_risk/front_pressure 补充非恒定、真实事件覆盖的测试集，再判断模型价值；不要根据当前退化 R² 调参。',
'4. 未来抓地模型先重审代理目标；策略模型需要实际方案结果，不应把四类规则模仿称为完整策略学习。',
'',
'## 可复现文件',
'',
'- run_audit.py：文件审计、UDP 头盘点、输入快照、14 模型重训。',
'- data-audit.json、input-hashes.json、code-hashes-before.json、run-status.json：来源与执行证据。',
'- models/retraining-report.json、model-comparison.json：14 模型报告与对比。',
'- diagnose.py、label-diagnosis.json：恒定测试标签诊断。',
'- community_experiment.py：社区实验训练；community-experiment/report.json：来源、分组、指标。',
'- verify_experiment.py、community-experiment/verification.json：留出预测的数值检查。',
'- community-experiment/test-predictions.csv、speed_delta_50m_lightgbm.txt：逐点预测及实验模型（模型文件位于 community-experiment 内）。',
'',
'本轮完成离线重训和独立社区实验；未完成新增数据对原 14 模型的直接扩充、线上模型启用或实车/游戏实时验收。']
(O/'分析报告.md').write_text('\n'.join(lines)+'\n');print('14 metrics reproduced; report saved:',O/'分析报告.md')

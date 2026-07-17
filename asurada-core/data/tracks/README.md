# F1 25 赛道语义数据

本目录覆盖 EA SPORTS F1 25 的 27 个可驾驶布局：24 条常规赛道，以及 Silverstone、Austria、Zandvoort 的 3 条反向布局。

## 数据来源与处理

- `austria_segments.json`、`shanghai_segments.json`、`suzuka_segments.json` 保留项目原有人工整理结果。
- 其余 24 个 profile 由 F1Laps 的 F1 25 公开社区榜单遥测生成。
- 每个布局下载榜单中 3 个完整有效圈；速度、制动、油门、方向、档位和 DRS 在 5 米网格上重采样，并按通道取多圈中位数。
- F1Laps 横轴是车辆实际行驶路径距离。生成时会线性归一化到 F1 25 赛道圈长，使语义边界可直接匹配 UDP `lap_distance_m`。
- 自动生成 profile 会在每个弯心附近按多圈中位数生成 `recommended_gear`；三条人工 profile 继续使用代码中的人工档位映射。
- 不完整圈、空通道和圈长明显异常的榜单记录会自动跳过，并从前 10 名继续补足。

原始下载索引及哈希在 `../community_telemetry/f1laps_f12025/manifest.json`。34 MB 原始遥测不进入 Git；
`f1_25_track_semantics_quality_baseline.json` 保留从原始遥测重算得到的质量基线。完整覆盖清单在
`f1_25_track_semantics_manifest.json`。

## 重建与校验

```bash
cd asurada-core
python3 scripts/fetch_f1laps_track_telemetry.py --top 3
python3 scripts/build_f1_25_track_semantics.py
python3 scripts/validate_f1_25_track_semantics.py
python3 scripts/phase1_all_track_semantics_regression.py
python3 scripts/phase1_track_semantics_quality_regression.py
python3 scripts/phase1_real_udp_track_semantics_regression.py
python3 scripts/phase1_all_track_udp_replay_regression.py
```

生成器默认不覆盖项目原有的三条人工 profile。只有显式传入 `--include-curated` 才会重建它们。

## 验收口径

- `validate_f1_25_track_semantics.py`：校验 27 条布局、81 个来源圈哈希、分段连续性、边界判定、下一段预视和档位范围。
- `phase1_all_track_semantics_regression.py`：校验 27 条布局都可加载，并可生成区段分类、刹车点目标和档位目标。
- `phase1_track_semantics_quality_regression.py`：对 24 条自动 profile 检查每圈制动区命中、弯心方向输入和档位一致性；包含摩纳哥、吉达、迈阿密与三条反向布局的高风险集合。
- `phase1_real_udp_track_semantics_regression.py`：本机存在外部抓包时，使用上海、铃鹿、奥地利真实 F1 25 raw UDP 抓包验证解码、组帧与语义分类；干净检出会明确标记跳过外部证据。
- `phase1_all_track_udp_replay_regression.py`：复用由真实抓包提取的 7 包紧凑完整帧并替换规范内的赛道元数据，验证 27 个 `track_id` 的 raw decoder、assembler 和 profile 映射矩阵。

当前范围只包含 F1 25 基础版 UDP 与 27 个基础版布局，不包含 2026 Season Pack。

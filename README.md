# Asurada Workspace

Asurada 是一个面向赛车策略大脑项目的多模块工作区。

Asurada is a multi-part workspace for the racing strategy-brain project.

## 工作区组成

仓库根目录当前作为以下模块的顶层容器：

- [asurada-core](asurada-core)
  - 后端策略大脑
  - packet 解码
  - 标准化状态模型
  - 分层策略引擎
  - 回放日志与调试 dashboard
- [ios-racetrack-analytics](ios-racetrack-analytics)
  - App 侧工程目录
- [tools](tools)
  - 抓包文件、工具脚本和外部数据资产
- [doc](doc)
  - 导出的项目文档

This repository root currently acts as the top-level container for:

- [asurada-core](asurada-core)
  - backend strategy brain
  - packet decoding
  - normalized state model
  - layered strategy engine
  - replay logging and debug dashboard
- [ios-racetrack-analytics](ios-racetrack-analytics)
  - app-side project workspace
- [tools](tools)
  - capture files, utilities, and external data assets
- [doc](doc)
  - exported project documents

## 当前版本管理范围

当前仓库已提交并推送的主体是：

- [asurada-core](asurada-core)

其余顶层目录当前保留在本地工作区中，默认不作为已提交历史的一部分。

The repository currently commits the backend workspace in:

- [asurada-core](/Users/sn5/Asurada/asurada-core)

The other top-level directories are present locally, but are not yet part of the committed project history by default.

## 主入口

如果当前工作重点是策略脑后端，请从这里开始：

- [asurada-core/README.md](asurada-core/README.md)
- [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md)

关键后端项目文档：

- [asurada-core/STATUS.md](asurada-core/STATUS.md)
- [asurada-core/ARCHITECTURE.md](asurada-core/ARCHITECTURE.md)
- [asurada-core/PHASE1_ACCEPTANCE.md](asurada-core/PHASE1_ACCEPTANCE.md)
- [asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md](asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md)
- [asurada-core/SESSION_TYPE_CLASSIFICATION.md](asurada-core/SESSION_TYPE_CLASSIFICATION.md)

If you are working on the strategy brain, start here:

- [asurada-core/README.md](asurada-core/README.md)
- [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md)

## 项目总进度

![Phase 1](https://img.shields.io/badge/Phase%201-90%25-2ea44f?style=for-the-badge)
![Phase 2](https://img.shields.io/badge/Phase%202-35%25-f59e0b?style=for-the-badge)
![Phase 3](https://img.shields.io/badge/Phase%203-0%25-9ca3af?style=for-the-badge)

详细看板：
- [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md)

Important backend project documents:

- [asurada-core/STATUS.md](asurada-core/STATUS.md)
- [asurada-core/ARCHITECTURE.md](asurada-core/ARCHITECTURE.md)
- [asurada-core/PHASE1_ACCEPTANCE.md](asurada-core/PHASE1_ACCEPTANCE.md)
- [asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md](asurada-core/STAGE2_MODEL_INPUT_SCHEMA.md)
- [asurada-core/SESSION_TYPE_CLASSIFICATION.md](asurada-core/SESSION_TYPE_CLASSIFICATION.md)

## 目录结构

```text
Asurada/
├── asurada-core/              后端策略脑工作区
├── ios-racetrack-analytics/   App 工作区
├── tools/                     抓包与外部工具
├── doc/                       项目文档导出目录
├── tmp/                       本地临时文件
└── .derived-data/             本机构建产物
```

## 后端快速开始

```bash
cd /Users/sn5/Asurada/asurada-core
source .venv/bin/activate

python main.py --demo
python main.py --csv /Users/sn5/asurada_simulator/tools/f1_recorder/data/20260319_015115_shanghai_lap.csv
python main.py --capture-jsonl /Users/sn5/Asurada/tools/captures/f1_25_udp_capture_20260321_024707.jsonl
python main.py --build-dashboard
```

## 说明

- 根目录 `.gitignore` 只忽略明显的本机和临时产物。
- `asurada-core/.gitignore` 负责后端工程自身的忽略规则，例如 `.venv/` 和 `runtime_logs/`。
- 按 `session_uid` 切出来的大体积抓包样本默认不提交，只跟踪其 metadata。

## Notes

- Root-level `.gitignore` only excludes obvious local artifacts.
- `asurada-core/.gitignore` manages backend-specific ignores such as `.venv/` and `runtime_logs/`.
- Large extracted per-session capture samples are intentionally not committed; only their metadata is tracked in `asurada-core`.

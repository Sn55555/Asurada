from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 备注:
# usage_hooks.json 承载赛道语义用途到策略权重的映射。
# 后续调优优先修改配置文件，不直接改策略代码里的分值。
DEFAULT_USAGE_HOOKS_PATH = PROJECT_ROOT / "data" / "strategy" / "usage_hooks.json"


@dataclass
class StrategyThresholds:
    """Base thresholds used by the strategy state assessment layer."""

    low_fuel_laps: float = 2.5
    tyre_wear_warn: float = 58.0
    tyre_wear_box: float = 72.0
    ers_low_pct: float = 18.0
    rival_gap_attack: float = 1.2
    rival_gap_defend: float = 1.0


@dataclass
class AppConfig:
    """Top-level application configuration."""

    thresholds: StrategyThresholds = field(default_factory=StrategyThresholds)
    replay_log_dir: Path = PROJECT_ROOT / "runtime_logs"
    usage_hooks_path: Path = DEFAULT_USAGE_HOOKS_PATH


@dataclass
class UdpConfig:
    """Socket settings for the live UDP real-time runtime path."""

    host: str = "0.0.0.0"
    port: int = 20778
    buffer_size: int = 65535
    receive_timeout_s: float = 0.5


def load_usage_hooks(path: Path) -> dict[str, dict[str, int]]:
    """Load configurable track-usage weight hooks from JSON."""

    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    hooks = payload.get("usage_hooks", payload)
    normalized: dict[str, dict[str, int]] = {}
    for usage, values in hooks.items():
        if not isinstance(values, dict):
            continue
        normalized[usage] = {
            "attack": int(values.get("attack", 0)),
            "ers": int(values.get("ers", 0)),
            "defend": int(values.get("defend", 0)),
            "tyre": int(values.get("tyre", 0)),
            "dynamics": int(values.get("dynamics", 0)),
        }
    return normalized

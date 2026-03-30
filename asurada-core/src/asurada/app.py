from __future__ import annotations

from pathlib import Path

from .analysis import summarize_lap
from .capture_runtime import CaptureReplayRuntime
from .config import AppConfig, UdpConfig
from .csv_ingest import LapCsvSource
from .dashboard import DebugDashboardBuilder
from .decode import decode_snapshot
from .ingest import ReplaySource
from .live_runtime import LiveRuntime
from .output import ConsoleLapSummaryOutput, ConsoleVoiceOutput
from .replay import ReplayLogger
from .reports import ReportWriter
from .state import UnifiedStateStore
from .strategy import StrategyEngine
from .udp_ingest import UdpPacketSource


class AsuradaApp:
    """Top-level application facade.

    备注:
    这里负责把输入源、状态仓、策略引擎、日志和输出层组装在一起。
    业务逻辑尽量留在各子模块，避免这里演变成巨型控制器。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state_store = UnifiedStateStore()
        self.strategy = StrategyEngine(config.thresholds, config.usage_hooks_path)
        self.voice_output = ConsoleVoiceOutput()
        self.summary_output = ConsoleLapSummaryOutput()
        self.logger = ReplayLogger(config.replay_log_dir)
        self.report_writer = ReportWriter(config.replay_log_dir / "reports")
        self.dashboard_builder = DebugDashboardBuilder(config.replay_log_dir / "dashboard")

    def run_replay(self, replay_path: Path) -> None:
        # 备注:
        # replay 是“已标准化快照”路径，适合快速回归策略逻辑，
        # 不经过原始 PDU 解析与组帧。
        self.logger.reset()
        source = ReplaySource(replay_path)
        for payload in source:
            state = decode_snapshot(payload)
            self.state_store.update(state)
            decision = self.strategy.evaluate(state, self.state_store.recent(12))
            self.voice_output.emit(decision, render=True)
            self.logger.append(state, decision)

    def run_csv_lap(self, csv_path: Path) -> None:
        # 备注:
        # CSV 单圈分析既要输出实时策略，也要生成赛后复盘报告，
        # 因此这里在循环后额外执行 lap summary 和 report writer。
        self.logger.reset()
        source = LapCsvSource(csv_path)
        lap_states = []
        for payload in source:
            state = decode_snapshot(payload)
            self.state_store.update(state)
            lap_states.append(state)
            decision = self.strategy.evaluate(state, self.state_store.recent(12))
            render_output = bool(decision.messages and decision.messages[0].priority >= 70)
            self.voice_output.emit(decision, render=render_output)
            self.logger.append(state, decision)

        summary = summarize_lap(lap_states)
        self.summary_output.emit(summary)
        report_path = self.report_writer.write_json(
            f"{csv_path.stem}_lap_report",
            summary.to_report_dict(track=lap_states[0].track if lap_states else "Unknown", sample_count=len(lap_states)),
        )
        print(f"[ASURADA][REPORT] 已生成复盘报告: {report_path}")

    def run_live_udp(self, udp_config: UdpConfig) -> None:
        self.logger.reset()
        runtime = LiveRuntime(
            UdpPacketSource(udp_config),
            state_store=self.state_store,
            strategy=self.strategy,
            voice_output=self.voice_output,
            logger=self.logger,
            dashboard_refresh=None,
        )
        runtime.run()

    def run_capture_replay(self, capture_path: Path, *, session_paced: bool = False, pace_multiplier: float = 1.0) -> None:
        # 备注:
        # capture replay 是“最接近真实输入”的离线验证模式：
        # raw UDP packet -> decoder -> assembler -> SessionState -> strategy。
        self.logger.reset()
        runtime = CaptureReplayRuntime(
            capture_path,
            state_store=self.state_store,
            strategy=self.strategy,
            voice_output=self.voice_output,
            logger=self.logger,
            dashboard_refresh=self.build_debug_dashboard,
            session_paced=session_paced,
            pace_multiplier=pace_multiplier,
        )
        runtime.run()

    def build_debug_dashboard(self) -> None:
        dashboard_path = self.dashboard_builder.build_from_session_log(self.logger.path)
        print(f"[ASURADA][DASHBOARD] 已生成调试面板: {dashboard_path}")

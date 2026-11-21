from __future__ import annotations

from .context_window import CONTEXT_WINDOW_SECONDS

from .async_sink import AsyncRuntimeSink
from .async_capture import AsyncPacketRecorder
from .buffered_ingest import BufferedPacketSource
from .speech_driver import SpeechOutputDriver
from .speech_client import make_voice_output
from .speech_submission import LiveSpeechSubmission

import os
from pathlib import Path

from .analysis import summarize_lap
from .capture_runtime import CaptureReplayRuntime
from .config import AppConfig, UdpConfig
from .csv_ingest import LapCsvSource
from .dashboard import DebugDashboardBuilder
from .decode import decode_snapshot
from .ingest import ReplaySource
from .live_dashboard_feed import CompositeRuntimeLogger, DashboardFeedWriter, LatestSnapshotWriter
from .live_runtime import LiveRuntime
from .output import ConsoleLapSummaryOutput, ConsoleVoiceOutput
from .personality_runtime import PersonalityRuntime, personality_enabled
from .personality_memory import relationship_path
from .replay import ReplayLogger
from .reports import ReportWriter
from .state import UnifiedStateStore
from .strategy import StrategyEngine
from .tts_backends import NullSpeechBackend, resolve_default_speech_backend
from .udp_capture import RawPacketCaptureRecorder
from .udp_ingest import UdpPacketSource


class AsuradaApp:
    """Top-level application facade.

    备注:
    这里负责把输入源、状态仓、策略引擎、日志和输出层组装在一起。
    业务逻辑尽量留在各子模块，避免这里演变成巨型控制器。
    """

    def __init__(self, config: AppConfig, *, voice_output=None, shared_speech=True) -> None:
        self.config = config
        self.state_store = UnifiedStateStore()
        self.strategy = StrategyEngine(config.thresholds, config.usage_hooks_path)
        self.voice_output = voice_output if voice_output is not None else make_voice_output(backend_factory=self._resolve_voice_backend, shared=shared_speech)
        self.summary_output = ConsoleLapSummaryOutput()
        self.logger = ReplayLogger(config.replay_log_dir, max_archives=config.replay_log_max_archives)
        self.live_dashboard_feed = DashboardFeedWriter(config.replay_log_dir / "dashboard")
        self.report_writer = ReportWriter(config.replay_log_dir / "reports")
        self.dashboard_builder = DebugDashboardBuilder(config.replay_log_dir / "dashboard")

    def _resolve_voice_backend(self):
        forced_backend = str(os.getenv("ASURADA_TTS_BACKEND") or "").strip().lower()
        if forced_backend:
            return resolve_default_speech_backend()
        if str(os.getenv("ASURADA_DISABLE_LOCAL_VOICE_OUTPUT") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return NullSpeechBackend()
        return None

    def run_replay(self, replay_path: Path) -> None:
        # 备注:
        # replay 是“已标准化快照”路径，适合快速回归策略逻辑，
        # 不经过原始 PDU 解析与组帧。
        self.logger.reset()
        source = ReplaySource(replay_path)
        for payload in source:
            state = decode_snapshot(payload)
            if not self.state_store.update(state):
                continue
            decision = self.strategy.evaluate(state, self.state_store.recent_seconds(CONTEXT_WINDOW_SECONDS))
            self.voice_output.emit(decision, state=state, render=True)
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
            if not self.state_store.update(state):
                continue
            lap_states.append(state)
            decision = self.strategy.evaluate(state, self.state_store.recent_seconds(CONTEXT_WINDOW_SECONDS))
            render_output = bool(decision.messages and decision.messages[0].priority >= 70)
            self.voice_output.emit(decision, state=state, render=render_output)
            self.logger.append(state, decision)

        summary = summarize_lap(lap_states)
        self.summary_output.emit(summary)
        report_path = self.report_writer.write_json(
            f"{csv_path.stem}_lap_report",
            summary.to_report_dict(track=lap_states[0].track if lap_states else "Unknown", sample_count=len(lap_states)),
        )
        print(f"[ASURADA][REPORT] 已生成复盘报告: {report_path}")

    def run_live_udp(self, udp_config: UdpConfig, *, capture_path: Path | None = None, grid_plan_stops: int | None = None) -> None:
        self.logger.reset()
        self.live_dashboard_feed.reset()
        packet_recorder = None
        if capture_path is not None:
            packet_recorder = RawPacketCaptureRecorder(capture_path)
            packet_recorder.reset()
            packet_recorder = AsyncPacketRecorder(packet_recorder)
            print(f"[ASURADA] Raw UDP capture recording: {capture_path}")
        latest = LatestSnapshotWriter(self.logger.directory)
        latest.reset()
        async_latest = AsyncRuntimeSink(latest, latest_only=True)
        self.strategy.enable_background_observations()
        self.strategy.enable_background_planning()
        async_log = AsyncRuntimeSink(self.logger, capacity=128)
        async_feed = AsyncRuntimeSink(self.live_dashboard_feed, latest_only=True)
        live_logger = CompositeRuntimeLogger(async_log, async_feed, async_latest)
        packet_source = BufferedPacketSource(UdpPacketSource(udp_config), capacity=udp_config.receive_queue_capacity)
        speech_submission = (LiveSpeechSubmission(self.voice_output)
                             if getattr(self.voice_output, 'externally_driven', False) else None)
        personality = PersonalityRuntime(relationship_db=relationship_path()) if personality_enabled() else None
        runtime = LiveRuntime(
            packet_source,
            state_store=self.state_store,
            strategy=self.strategy,
            voice_output=speech_submission or self.voice_output,
            logger=live_logger,
            packet_recorder=packet_recorder,
            dashboard_refresh=None,
            **({"personality": personality} if personality is not None else {}),
        )
        if grid_plan_stops is not None:
            runtime.pipeline.grid_feed.selected_stops = grid_plan_stops
        try:
            with SpeechOutputDriver(self.voice_output):
                runtime.run()
        finally:
            if personality is not None:
                personality.close()
            if speech_submission is not None:
                stopped = speech_submission.close()
                print(f"[ASURADA][SPEECH-SUBMISSION] stopped={stopped} health={speech_submission.snapshot()}")
            print(f"[ASURADA][INGRESS] closed={packet_source.close()} health={packet_source.snapshot()}")
            if packet_recorder is not None:
                drained = packet_recorder.close(ingress_health=packet_source.snapshot())
                print(f"[ASURADA][CAPTURE] drained={drained} health={packet_recorder.snapshot()}")
            if self.strategy.planning_lane is not None:
                print(f"[ASURADA][PLANNER] completed={self.strategy.planning_lane.close()}")
            if self.strategy.observation_lane is not None:
                print(f"[ASURADA][OBSERVE] completed={self.strategy.observation_lane.close()}")
            for name, sink in (("replay", async_log), ("dashboard", async_feed), ("latest", async_latest)):
                drained = sink.close()
                print(f"[ASURADA][SINK] {name} drained={drained} health={sink.snapshot()}")

    def run_capture_replay(self, capture_path: Path, *, session_paced: bool = False, pace_multiplier: float = 1.0,
                           grid_plan_stops: int | None = None) -> None:
        # 备注:
        # capture replay 是“最接近真实输入”的离线验证模式：
        # raw UDP packet -> decoder -> assembler -> SessionState -> strategy。
        self.logger.reset()
        personality = PersonalityRuntime() if personality_enabled() else None
        runtime = CaptureReplayRuntime(
            capture_path,
            state_store=self.state_store,
            strategy=self.strategy,
            voice_output=self.voice_output,
            logger=self.logger,
            dashboard_refresh=self.build_debug_dashboard,
            session_paced=session_paced,
            pace_multiplier=pace_multiplier,
            personality=personality,
        )
        if grid_plan_stops is not None:
            runtime.pipeline.grid_feed.selected_stops = grid_plan_stops
        with SpeechOutputDriver(self.voice_output):
            runtime.run()

    def build_debug_dashboard(self) -> None:
        dashboard_path = self.dashboard_builder.build_from_session_log(self.logger.path)
        print(f"[ASURADA][DASHBOARD] 已生成调试面板: {dashboard_path}")

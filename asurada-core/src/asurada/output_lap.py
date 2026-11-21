"""Console-only lap-summary presentation, independent of speech ownership."""
from __future__ import annotations
import threading
from .analysis import LapAnalysisSummary, SegmentAnalysis
from .output_contracts import _OutputProcessingResult, _serialized


class ConsoleLapSummaryOutput:
    """Print a compact single-lap review summary."""

    def __init__(self) -> None:
        self._output_lock = threading.RLock()

    def _scope_rejection(self):
        debug={}
        event=self._build_event_from_envelope(None,"suppress",metadata={"reason":"stale_session_scope"})
        self._write_debug_payload(debug=debug,result=_OutputProcessingResult(lifecycle_event=event,event_envelope=None))
        return debug

    @_serialized
    def emit(self, summary: LapAnalysisSummary) -> None:
        """Render lap summary metrics and segment review lines."""

        print("[ASURADA][LAP] 单圈总结")
        print(f"  - 最高车速: {summary.max_speed_kph:.0f} km/h")
        print(f"  - 最低车速: {summary.min_speed_kph:.0f} km/h")
        print(f"  - 重刹事件: {summary.heavy_braking_events}")
        print(f"  - 姿态不稳事件: {summary.unstable_events}")
        print(f"  - 前轮负荷过高事件: {summary.overload_events}")
        print(f"  - 扇区切换次数: {summary.sector_transitions}")
        if summary.top_risk_segments:
            print("  [赛道复盘] 高风险区段")
            for segment in summary.top_risk_segments:
                print(f"    - {self._segment_line(segment)}")
        if summary.dynamics_phases:
            print("  [驾驶动态] 分阶段摘要")
            for phase in summary.dynamics_phases:
                print(
                    "    - "
                    f"{phase.phase}: sample={phase.sample_count}, "
                    f"unstable={phase.unstable_events}, "
                    f"front_load={phase.overload_events}, "
                    f"heavy_brake={phase.heavy_braking_events}, "
                    f"avg_speed={phase.avg_speed_kph:.0f}"
                )
        if summary.driver_style_summary:
            print("  [驾驶风格] 标签")
            print(f"    - {', '.join(summary.driver_style_summary)}")
        if summary.deployment_segments:
            print("  [赛道复盘] 主要部署区")
            for segment in summary.deployment_segments:
                print(
                    "    - "
                    f"{segment.name}: 最高 {segment.max_speed_kph:.0f} km/h, "
                    f"最低 {segment.min_speed_kph:.0f} km/h"
                )

    def _segment_line(self, segment: SegmentAnalysis) -> str:
        """Format one segment summary row."""

        return (
            f"{segment.name} ({segment.zone_type}) | "
            f"unstable={segment.unstable_events}, "
            f"front_load={segment.overload_events}, "
            f"heavy_brake={segment.heavy_braking_events}, "
            f"vmax={segment.max_speed_kph:.0f}"
        )



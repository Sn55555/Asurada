from __future__ import annotations

from .analysis import LapAnalysisSummary, SegmentAnalysis
from .models import StrategyDecision


class ConsoleVoiceOutput:
    """Temporary stand-in for voice copilot and HUD output.

    备注:
    控制台输出同时承担当前阶段的策略调试视图。
    当策略引擎完成分层推理后，这里会把“状态评估 -> 风险评分 ->
    候选策略 -> 最终播报”按可读格式打印出来，便于快速校验策略逻辑。
    """

    def emit(self, decision: StrategyDecision) -> None:
        """Print final strategy output and debug layers to the console."""

        if not decision.messages:
            print("[ASURADA] 状态稳定，无高优先级播报。")
            return

        top = decision.messages[0]
        print(f"[ASURADA][P{top.priority}] {top.title}: {top.detail}")
        for extra in decision.messages[1:3]:
            print(f"  - {extra.title}: {extra.detail}")
        self._emit_debug(decision)

    def _emit_debug(self, decision: StrategyDecision) -> None:
        """Render layered debug state for maintenance and tuning."""

        context = decision.debug.get("context", {})
        assessment = decision.debug.get("assessment", {})
        risk_profile = decision.debug.get("risk_profile", {})
        candidates = decision.debug.get("candidates", [])

        print("  [备注] 分层策略调试")
        if context:
            print(f"    - 上下文因子: {self._format_mapping(context)}")
        if assessment:
            print(f"    - 状态评估: {self._format_mapping(assessment)}")
        if risk_profile:
            print(f"    - 风险评分: {self._format_mapping(risk_profile)}")
        if candidates:
            ranked = ", ".join(
                f"{item['code']}@{item['priority']}({item['layer']})"
                for item in candidates[:5]
            )
            print(f"    - 候选策略: {ranked}")
        if decision.messages:
            ordered = " > ".join(f"{item.code}@{item.priority}" for item in decision.messages[:5])
            print(f"    - 最终排序: {ordered}")

    def _format_mapping(self, payload: dict) -> str:
        """Format a flat mapping into one readable debug line."""

        return ", ".join(f"{key}={value}" for key, value in payload.items())


class ConsoleLapSummaryOutput:
    """Print a compact single-lap review summary."""

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

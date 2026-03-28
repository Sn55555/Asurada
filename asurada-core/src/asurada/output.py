from __future__ import annotations

from dataclasses import asdict

from .analysis import LapAnalysisSummary, SegmentAnalysis
from .interaction import OutputLifecycleEvent
from .models import StrategyDecision


class ConsoleVoiceOutput:
    """Temporary stand-in for voice copilot and HUD output.

    备注:
    控制台输出同时承担当前阶段的策略调试视图。
    当策略引擎完成分层推理后，这里会把“状态评估 -> 风险评分 ->
    候选策略 -> 最终播报”按可读格式打印出来，便于快速校验策略逻辑。
    """

    def __init__(self) -> None:
        self.output_session_id = "voice-output:console"
        self._active_output_event_id: str | None = None
        self._active_code: str | None = None
        self._event_counter = 0

    def emit(self, decision: StrategyDecision, *, render: bool = True) -> dict:
        """Emit one lifecycle-aware output step and return the lifecycle event."""

        interaction_input_event = decision.debug.get("interaction_input_event", {}) or {}
        arbiter_output = (decision.debug.get("arbiter_v2", {}) or {}).get("output", {}) or {}
        final_voice_action = arbiter_output.get("final_voice_action") or {}

        lifecycle_event = self._resolve_lifecycle_event(
            decision=decision,
            interaction_input_event=interaction_input_event,
            final_voice_action=final_voice_action,
        )
        decision.debug["output_lifecycle"] = {
            "event": lifecycle_event.to_dict(),
            "active_output": {
                "output_session_id": self.output_session_id,
                "active_output_event_id": self._active_output_event_id,
                "active_code": self._active_code,
            },
        }

        if lifecycle_event.event_type == "idle":
            if render:
                print("[ASURADA] 状态稳定，无高优先级播报。")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "suppress":
            if render:
                print(f"[ASURADA][SUPPRESS] {lifecycle_event.action_code}: {lifecycle_event.metadata.get('reason', 'suppressed')}")
            return decision.debug["output_lifecycle"]
        if lifecycle_event.event_type == "cancel":
            if render:
                print(f"[ASURADA][CANCEL] {lifecycle_event.action_code}")
            return decision.debug["output_lifecycle"]

        top = decision.messages[0]
        prefix = "INTERRUPT" if lifecycle_event.event_type == "interrupt" else f"P{top.priority}"
        if render:
            print(f"[ASURADA][{prefix}] {top.title}: {top.detail}")
            for extra in decision.messages[1:3]:
                print(f"  - {extra.title}: {extra.detail}")
            self._emit_debug(decision)
        return decision.debug["output_lifecycle"]

    def _resolve_lifecycle_event(
        self,
        *,
        decision: StrategyDecision,
        interaction_input_event: dict,
        final_voice_action: dict,
    ) -> OutputLifecycleEvent:
        self._event_counter += 1
        output_event_id = f"out:{self._event_counter}"
        turn_id = str(interaction_input_event.get("turn_id") or "turn:unknown")
        request_id = str(interaction_input_event.get("request_id") or "req:unknown")
        snapshot_binding_id = str(interaction_input_event.get("snapshot_binding_id") or "snap:unknown")

        if not decision.messages or not final_voice_action:
            interrupted = self._active_output_event_id
            code = self._active_code or "NONE"
            self._active_output_event_id = None
            self._active_code = None
            return OutputLifecycleEvent(
                output_session_id=self.output_session_id,
                output_event_id=output_event_id,
                event_type="cancel" if interrupted is not None else "idle",
                channel="voice",
                action_code=code,
                priority=0,
                cancelable=True,
                turn_id=turn_id,
                request_id=request_id,
                snapshot_binding_id=snapshot_binding_id,
                speak_text="",
                interrupted_output_event_id=interrupted,
                metadata={"reason": "no_final_voice_action"},
            )

        top = decision.messages[0]
        code = top.code
        priority = int(final_voice_action.get("priority") or top.priority or 0)
        interrupt = bool(final_voice_action.get("interrupt"))
        speak_text = str(final_voice_action.get("speak_text") or top.title)

        if self._active_code == code and not interrupt:
            return OutputLifecycleEvent(
                output_session_id=self.output_session_id,
                output_event_id=output_event_id,
                event_type="suppress",
                channel="voice",
                action_code=code,
                priority=priority,
                cancelable=True,
                turn_id=turn_id,
                request_id=request_id,
                snapshot_binding_id=snapshot_binding_id,
                speak_text=speak_text,
                interrupted_output_event_id=self._active_output_event_id,
                metadata={"reason": "duplicate_active_code"},
            )

        interrupted_output_event_id = None
        event_type = "start"
        if self._active_output_event_id is not None:
            if interrupt:
                event_type = "interrupt"
                interrupted_output_event_id = self._active_output_event_id
            else:
                return OutputLifecycleEvent(
                    output_session_id=self.output_session_id,
                    output_event_id=output_event_id,
                    event_type="suppress",
                    channel="voice",
                    action_code=code,
                    priority=priority,
                    cancelable=True,
                    turn_id=turn_id,
                    request_id=request_id,
                    snapshot_binding_id=snapshot_binding_id,
                    speak_text=speak_text,
                    interrupted_output_event_id=self._active_output_event_id,
                    metadata={"reason": "active_output_not_interruptible"},
                )

        self._active_output_event_id = output_event_id
        self._active_code = code
        return OutputLifecycleEvent(
            output_session_id=self.output_session_id,
            output_event_id=output_event_id,
            event_type=event_type,
            channel="voice",
            action_code=code,
            priority=priority,
            cancelable=code != "SAFETY_CAR",
            turn_id=turn_id,
            request_id=request_id,
            snapshot_binding_id=snapshot_binding_id,
            speak_text=speak_text,
            interrupted_output_event_id=interrupted_output_event_id,
            metadata={"source": "console_voice_output"},
        )

    def _emit_debug(self, decision: StrategyDecision) -> None:
        """Render layered debug state for maintenance and tuning."""

        context = decision.debug.get("context", {})
        assessment = decision.debug.get("assessment", {})
        risk_profile = decision.debug.get("risk_profile", {})
        candidates = decision.debug.get("candidates", [])
        interaction_input_event = decision.debug.get("interaction_input_event", {})
        output_lifecycle = decision.debug.get("output_lifecycle", {})

        print("  [备注] 分层策略调试")
        if interaction_input_event:
            snapshot_binding = interaction_input_event.get("snapshot_binding", {})
            print(
                "    - 交互事件: "
                f"{interaction_input_event.get('intent_type')} "
                f"turn={interaction_input_event.get('turn_id')} "
                f"request={interaction_input_event.get('request_id')} "
                f"snapshot={snapshot_binding.get('snapshot_binding_id')}"
            )
        if output_lifecycle:
            event = output_lifecycle.get("event", {})
            print(
                "    - 输出生命周期: "
                f"{event.get('event_type')} "
                f"action={event.get('action_code')} "
                f"output_event={event.get('output_event_id')}"
            )
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

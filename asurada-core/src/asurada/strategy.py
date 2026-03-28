from __future__ import annotations

from .arbiter import (
    ArbiterInput,
    ConfidenceContext,
    FallbackContext,
    ModelCandidate,
    OutputControl,
    RuleCandidate,
    StrategyArbiterV2,
    TacticalContext,
)
from .config import StrategyThresholds, load_usage_hooks
from .models import (
    ContextProfile,
    RiskProfile,
    SessionState,
    StateAssessment,
    StrategyCandidate,
    StrategyDecision,
    StrategyMessage,
)
from .model_runtime import StrategyActionModelRuntime
from .track_model import load_track_profile


class StrategyEngine:
    """Run the four-stage strategy pipeline for one normalized frame."""

    def __init__(self, thresholds: StrategyThresholds, usage_hooks_path=None) -> None:
        self.thresholds = thresholds
        self.usage_hooks = load_usage_hooks(usage_hooks_path) if usage_hooks_path is not None else {}
        self.arbiter_v2 = StrategyArbiterV2()
        self.strategy_action_runtime = StrategyActionModelRuntime()

    def evaluate(self, state: SessionState, history: list[SessionState] | None = None) -> StrategyDecision:
        """Evaluate one frame and return ranked strategy messages plus debug data."""

        # 备注:
        # 这里保留稳定的四层流程，后续接趋势模型、对手建模、进站收益评估时，
        # 直接插入对应层即可，不需要再把整套策略引擎推倒重写。
        context = self._build_context(state, history or [state])
        assessment = self._assess_state(state)
        risk_profile, risk_explain = self._score_risks(state, assessment, context)
        candidates = self._build_candidates(state, assessment, risk_profile, context)
        legacy_messages = self._arbitrate(candidates)
        arbiter_sidecar = self._build_arbiter_sidecar(state, context, candidates, assessment)
        messages = self._resolve_final_messages(legacy_messages, arbiter_sidecar)
        usage_bias = self._usage_bias(context.track_usage)
        return StrategyDecision(
            messages=messages,
            debug={
                "player_position": state.player.position,
                "lap": state.lap_number,
                "track": state.track,
                "context": context.__dict__,
                "assessment": assessment.__dict__,
                "risk_profile": risk_profile.__dict__,
                "risk_explain": risk_explain,
                "usage_bias": usage_bias,
                "candidates": [candidate.__dict__ for candidate in candidates],
                "arbiter_v2": arbiter_sidecar,
            },
        )

    def _build_context(self, state: SessionState, history: list[SessionState]) -> ContextProfile:
        """Derive short-window context features from recent frames and track metadata."""

        recent = history[-12:] if history else [state]
        total = max(len(recent), 1)
        unstable_count = 0
        overload_count = 0
        throttle_values = []
        brake_values = []
        steer_values = []

        for item in recent:
            tags = set(item.player.status_tags)
            unstable_count += int("unstable" in tags)
            overload_count += int("front_tyre_overload" in tags)
            throttle_values.append(float(item.raw.get("throttle", 0.0)))
            brake_values.append(float(item.raw.get("brake", 0.0)))
            steer_values.append(abs(float(item.raw.get("steer", 0.0))))

        lap_distance = float(state.raw.get("lap_distance_m", 0.0))
        track_profile = load_track_profile(state.track)
        if track_profile is not None:
            classified = track_profile.classify(lap_distance)
            track_zone = classified.zone_type
            track_segment = classified.zone_name
            track_usage = classified.usage
        else:
            track_zone = self._classify_track_zone(lap_distance)
            track_segment = "Generic Segment"
            track_usage = ""
        avg_throttle = sum(throttle_values) / total
        avg_brake = sum(brake_values) / total
        avg_steer = sum(steer_values) / total

        if avg_brake > 0.45:
            driving_mode = "brake_loaded"
        elif avg_throttle > 0.72 and avg_steer > 0.18:
            driving_mode = "push_exit"
        elif avg_steer > 0.28:
            driving_mode = "cornering"
        else:
            driving_mode = "straightline"

        tyre_age = state.player.tyre.age_laps
        tyre_age_factor = 12 if tyre_age >= 10 else 8 if tyre_age >= 6 else 2
        brake_phase_factor = 10 if avg_brake > 0.45 else 4 if avg_brake > 0.2 else 0
        throttle_phase_factor = 8 if avg_throttle > 0.78 else 4 if avg_throttle > 0.55 else 0
        steering_phase_factor = 8 if avg_steer > 0.30 else 4 if avg_steer > 0.18 else 0

        return ContextProfile(
            recent_unstable_ratio=unstable_count / total,
            recent_front_overload_ratio=overload_count / total,
            driving_mode=driving_mode,
            track_zone=track_zone,
            track_segment=track_segment,
            track_usage=track_usage,
            tyre_age_factor=tyre_age_factor,
            brake_phase_factor=brake_phase_factor,
            throttle_phase_factor=throttle_phase_factor,
            steering_phase_factor=steering_phase_factor,
        )

    def _assess_state(self, state: SessionState) -> StateAssessment:
        """Convert the current frame into discrete state labels."""

        player = state.player
        fuel_source = str(state.raw.get("fuel_laps_remaining_source", ""))
        fuel_in_tank = float(state.raw.get("fuel_in_tank", 0.0))
        fuel_capacity = float(state.raw.get("fuel_capacity", 0.0))
        tank_ratio = (fuel_in_tank / fuel_capacity) if fuel_capacity > 0.0 else 0.0
        completed_laps = max(state.lap_number - 1, 0)
        remaining_race_laps = max(state.total_laps - completed_laps, 0)
        fuel_margin_laps = player.fuel_laps_remaining - remaining_race_laps
        fuel_state = (
            "critical"
            if (
                state.lap_number > 1
                and fuel_source == "derived_from_sample_consumption"
                and fuel_margin_laps <= 0.3
            )
            or tank_ratio <= 0.08
            else "stable"
        )
        if player.tyre.wear_pct >= self.thresholds.tyre_wear_box:
            tyre_state = "box_now"
        elif player.tyre.wear_pct >= self.thresholds.tyre_wear_warn:
            tyre_state = "manage"
        else:
            tyre_state = "stable"

        ers_state = "low" if player.ers_pct <= self.thresholds.ers_low_pct else "stable"
        race_state = "controlled" if state.safety_car != "NONE" else "green"
        attack_state = (
            "available"
            if player.drs_available
            and player.gap_ahead_s is not None
            and player.gap_ahead_s <= self.thresholds.rival_gap_attack
            else "closed"
        )
        defend_state = (
            "urgent"
            if player.gap_behind_s is not None and player.gap_behind_s <= self.thresholds.rival_gap_defend
            else "clear"
        )

        if "unstable" in player.status_tags:
            dynamics_state = "unstable"
        elif "front_tyre_overload" in player.status_tags:
            dynamics_state = "front_overload"
        else:
            dynamics_state = "stable"

        return StateAssessment(
            fuel_state=fuel_state,
            tyre_state=tyre_state,
            ers_state=ers_state,
            race_state=race_state,
            attack_state=attack_state,
            defend_state=defend_state,
            dynamics_state=dynamics_state,
        )

    def _score_risks(
        self,
        state: SessionState,
        assessment: StateAssessment,
        context: ContextProfile,
    ) -> tuple[RiskProfile, dict[str, dict[str, int | str]]]:
        """Score numeric risks and opportunities from state plus context."""

        usage_bias = self._usage_bias(context.track_usage)
        tyre_context_bonus = context.tyre_age_factor + int(context.recent_front_overload_ratio * 18)
        dynamics_context_bonus = int(context.recent_unstable_ratio * 25) + context.steering_phase_factor
        ers_context_bonus = 6 if context.driving_mode == "push_exit" else 0
        defend_context_bonus = 8 if context.track_zone == "braking_entry" else 6 if context.track_zone == "apex_rotation" else 0
        attack_context_bonus = 8 if context.track_zone == "deployment_straight" else 4 if context.track_zone == "exit_traction" else 0
        tyre_management_bonus = 10 if context.track_zone == "high_load_management" else 0
        dynamics_zone_bonus = 10 if context.track_zone == "apex_rotation" else 6 if context.track_zone == "high_load_management" else 0
        fuel_risk = 95 if assessment.fuel_state == "critical" else 20
        tyre_risk = (
            90 + tyre_context_bonus + tyre_management_bonus + usage_bias["tyre"] if assessment.tyre_state == "box_now"
            else 65 + tyre_context_bonus + tyre_management_bonus + usage_bias["tyre"] if assessment.tyre_state == "manage"
            else 20 + min(tyre_context_bonus + tyre_management_bonus + usage_bias["tyre"], 14)
        )
        ers_risk = (60 + ers_context_bonus + usage_bias["ers"]) if assessment.ers_state == "low" else 15 + ers_context_bonus + usage_bias["ers"]
        race_control_risk = 130 if assessment.race_state == "controlled" else 0
        dynamics_risk = (
            72 + dynamics_context_bonus + dynamics_zone_bonus + usage_bias["dynamics"] if assessment.dynamics_state == "unstable"
            else 58 + dynamics_context_bonus + dynamics_zone_bonus + usage_bias["dynamics"] if assessment.dynamics_state == "front_overload"
            else 10 + int(context.recent_unstable_ratio * 12) + max(usage_bias["dynamics"], 0)
        )
        attack_opportunity = (
            56 + attack_context_bonus + context.throttle_phase_factor + usage_bias["attack"]
            if assessment.attack_state == "available"
            else 0
        )
        defend_risk = (
            54 + defend_context_bonus + context.brake_phase_factor + usage_bias["defend"]
            if assessment.defend_state == "urgent"
            else 10 + max(usage_bias["defend"], 0)
        )
        risk_profile = RiskProfile(
            fuel_risk=fuel_risk,
            tyre_risk=tyre_risk,
            ers_risk=ers_risk,
            race_control_risk=race_control_risk,
            dynamics_risk=dynamics_risk,
            attack_opportunity=attack_opportunity,
            defend_risk=defend_risk,
        )
        risk_explain = {
            "fuel_risk": {
                "state": assessment.fuel_state,
                "base": 95 if assessment.fuel_state == "critical" else 20,
                "usage_hook": 0,
                "total": fuel_risk,
            },
            "tyre_risk": {
                "state": assessment.tyre_state,
                "base": 90 if assessment.tyre_state == "box_now" else 65 if assessment.tyre_state == "manage" else 20,
                "tyre_age_factor": context.tyre_age_factor,
                "recent_front_overload_bonus": int(context.recent_front_overload_ratio * 18),
                "track_zone_bonus": tyre_management_bonus,
                "usage_hook": usage_bias["tyre"],
                "total": tyre_risk,
            },
            "ers_risk": {
                "state": assessment.ers_state,
                "base": 60 if assessment.ers_state == "low" else 15,
                "driving_mode_bonus": ers_context_bonus,
                "usage_hook": usage_bias["ers"],
                "total": ers_risk,
            },
            "race_control_risk": {
                "state": assessment.race_state,
                "base": race_control_risk,
                "usage_hook": 0,
                "total": race_control_risk,
            },
            "dynamics_risk": {
                "state": assessment.dynamics_state,
                "base": 72 if assessment.dynamics_state == "unstable" else 58 if assessment.dynamics_state == "front_overload" else 10,
                "recent_unstable_bonus": int(context.recent_unstable_ratio * 25) if assessment.dynamics_state != "stable" else int(context.recent_unstable_ratio * 12),
                "steering_phase_factor": context.steering_phase_factor,
                "track_zone_bonus": dynamics_zone_bonus,
                "usage_hook": usage_bias["dynamics"] if assessment.dynamics_state != "stable" else max(usage_bias["dynamics"], 0),
                "total": dynamics_risk,
            },
            "attack_opportunity": {
                "state": assessment.attack_state,
                "base": 56 if assessment.attack_state == "available" else 0,
                "track_zone_bonus": attack_context_bonus if assessment.attack_state == "available" else 0,
                "throttle_phase_factor": context.throttle_phase_factor if assessment.attack_state == "available" else 0,
                "usage_hook": usage_bias["attack"] if assessment.attack_state == "available" else 0,
                "total": attack_opportunity,
            },
            "defend_risk": {
                "state": assessment.defend_state,
                "base": 54 if assessment.defend_state == "urgent" else 10,
                "track_zone_bonus": defend_context_bonus if assessment.defend_state == "urgent" else 0,
                "brake_phase_factor": context.brake_phase_factor if assessment.defend_state == "urgent" else 0,
                "usage_hook": usage_bias["defend"] if assessment.defend_state == "urgent" else max(usage_bias["defend"], 0),
                "total": defend_risk,
            },
        }
        return risk_profile, risk_explain

    def _build_candidates(
        self,
        state: SessionState,
        assessment: StateAssessment,
        risk_profile: RiskProfile,
        context: ContextProfile,
    ) -> list[StrategyCandidate]:
        """Build candidate messages before final arbitration."""

        player = state.player
        candidates: list[StrategyCandidate] = []
        completed_laps = max(state.lap_number - 1, 0)
        remaining_race_laps = max(state.total_laps - completed_laps, 0)
        fuel_margin_laps = player.fuel_laps_remaining - remaining_race_laps

        if assessment.race_state == "controlled":
            candidates.append(
                StrategyCandidate(
                    code="SAFETY_CAR",
                    priority=risk_profile.race_control_risk,
                    title="赛道管制",
                    detail=f"{state.safety_car} 阶段，策略窗口重算，优先评估进站与站位保护。",
                    layer="strategy_candidate",
                )
            )
        if assessment.fuel_state == "critical":
            candidates.append(
                StrategyCandidate(
                    code="LOW_FUEL",
                    priority=risk_profile.fuel_risk,
                    title="燃油紧张",
                    detail=(
                        f"当前可跑约 {player.fuel_laps_remaining:.1f} 圈，剩余赛程约 {remaining_race_laps:.1f} 圈，"
                        f"燃油余量差 {fuel_margin_laps:+.1f} 圈，立即切换保守节奏并复核终盘覆盖。"
                    ),
                    layer="risk_response",
                )
            )
        if assessment.tyre_state == "box_now":
            candidates.append(
                StrategyCandidate(
                    code="BOX_WINDOW",
                    priority=risk_profile.tyre_risk,
                    title="进站窗口开启",
                    detail=f"{player.tyre.compound} 当前磨损 {player.tyre.wear_pct:.0f}%，优先进入进站评估。",
                    layer="strategy_candidate",
                )
            )
        elif assessment.tyre_state == "manage":
            candidates.append(
                StrategyCandidate(
                    code="TYRE_MANAGE",
                    priority=risk_profile.tyre_risk,
                    title="轮胎管理",
                    detail=(
                        f"{player.tyre.compound} 当前磨损 {player.tyre.wear_pct:.0f}%，"
                        f"轮胎年龄 {player.tyre.age_laps} 圈，当前圈开始控制滑移和出弯负载。"
                    ),
                    layer="risk_response",
                )
            )
        if assessment.ers_state == "low":
            candidates.append(
                StrategyCandidate(
                    code="ERS_LOW",
                    priority=risk_profile.ers_risk,
                    title="ERS 余量偏低",
                    detail=(
                        f"ERS 剩余 {player.ers_pct:.0f}%，当前驾驶模式 {context.driving_mode}，"
                        f"所在区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），后续防守优先，直道部署收紧。"
                    ),
                    layer="resource_management",
                )
            )
        if assessment.attack_state == "available" and player.gap_ahead_s is not None:
            candidates.append(
                StrategyCandidate(
                    code="ATTACK_WINDOW",
                    priority=risk_profile.attack_opportunity,
                    title="攻击窗口",
                    detail=(
                        f"前车差距 {player.gap_ahead_s:.1f}s，DRS 可用，"
                        f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），准备完成压迫。"
                    ),
                    layer="opportunity",
                )
            )
        if assessment.defend_state == "urgent" and player.gap_behind_s is not None:
            candidates.append(
                StrategyCandidate(
                    code="DEFEND_WINDOW",
                    priority=risk_profile.defend_risk,
                    title="防守窗口",
                    detail=(
                        f"后车差距 {player.gap_behind_s:.1f}s，当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
                        "出弯牵引和电量配置进入防守模式。"
                    ),
                    layer="risk_response",
                )
            )
        if assessment.dynamics_state == "unstable":
            candidates.append(
                StrategyCandidate(
                    code="DYNAMICS_UNSTABLE",
                    priority=risk_profile.dynamics_risk,
                    title="动态不稳定",
                    detail=(
                        f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
                        f"当前用途 {context.track_usage or 'general'}，压 curb 与转向输入需要收敛。"
                    ),
                    layer="dynamics",
                )
            )
        elif assessment.dynamics_state == "front_overload":
            candidates.append(
                StrategyCandidate(
                    code="FRONT_LOAD",
                    priority=risk_profile.dynamics_risk,
                    title="前轮负荷偏高",
                    detail=(
                        f"前轴负荷上升，最近前轮过载占比 {context.recent_front_overload_ratio:.2f}，"
                        f"当前用途 {context.track_usage or 'general'}，建议修正入弯峰值与中段转向保持。"
                    ),
                    layer="dynamics",
                )
            )

        return candidates

    def _arbitrate(self, candidates: list[StrategyCandidate]) -> list[StrategyMessage]:
        """Sort candidates into final output order."""

        layer_weight = {
            "strategy_candidate": 6,
            "risk_response": 4,
            "resource_management": 2,
            "dynamics": 1,
            "opportunity": 0,
        }
        code_weight = {
            "SAFETY_CAR": 20,
        }
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.priority,
                code_weight.get(item.code, 0),
                layer_weight.get(item.layer, 0),
            ),
            reverse=True,
        )
        return [
            StrategyMessage(
                code=item.code,
                priority=item.priority,
                title=item.title,
                detail=item.detail,
            )
            for item in ranked
        ]

    def _resolve_final_messages(
        self,
        legacy_messages: list[StrategyMessage],
        arbiter_sidecar: dict[str, object],
    ) -> list[StrategyMessage]:
        """Resolve final messages from arbiter output, with legacy fallback."""

        ordered_actions = arbiter_sidecar.get("output", {}).get("ordered_actions") if isinstance(arbiter_sidecar, dict) else None
        if not isinstance(ordered_actions, list) or not ordered_actions:
            return legacy_messages

        resolved: list[StrategyMessage] = []
        for item in ordered_actions[:3]:
            if not isinstance(item, dict):
                continue
            resolved.append(
                StrategyMessage(
                    code=str(item.get("code") or "NONE"),
                    priority=int(item.get("priority") or 0),
                    title=str(item.get("title") or item.get("code") or "NONE"),
                    detail=str(item.get("detail") or ""),
                )
            )
        return resolved or legacy_messages

    def _build_arbiter_sidecar(
        self,
        state: SessionState,
        context: ContextProfile,
        candidates: list[StrategyCandidate],
        assessment: StateAssessment,
    ) -> dict[str, object]:
        """Build a sidecar arbiter output without changing the current final messages."""

        tactical_state = "neutral"
        state_priority_hint = None
        state_lock = False

        if assessment.defend_state == "urgent":
            tactical_state = "defence_active"
            state_priority_hint = "DEFEND_WINDOW"
            state_lock = True
        elif assessment.attack_state == "available":
            tactical_state = "counterattack_prepare"
            state_priority_hint = "ATTACK_WINDOW"

        model_candidates = self._build_strategy_action_model_candidates(state=state, context=context)
        payload = ArbiterInput(
            rule_candidates=[RuleCandidate.from_strategy_candidate(candidate) for candidate in candidates],
            model_candidates=model_candidates,
            tactical_context=TacticalContext(
                tactical_state=tactical_state,
                state_priority_hint=state_priority_hint,
                state_lock=state_lock,
                state_transition=None,
            ),
            confidence_context=ConfidenceContext(
                confidence_score=1.0,
                confidence_level="high",
                mainline_allowed=True,
            ),
            fallback_context=FallbackContext(
                fallback_mode="none",
                voice_allowed=True,
                hud_only=False,
            ),
            output_control=OutputControl(
                cooldown_hint=0,
                last_emitted_action=None,
                suppression_window=0,
            ),
        )
        result = self.arbiter_v2.arbitrate(payload)
        return {
            "input": {
                "rule_candidates": [item.__dict__ for item in payload.rule_candidates],
                "model_candidates": [item.__dict__ for item in payload.model_candidates],
                "tactical_context": payload.tactical_context.__dict__,
                "confidence_context": payload.confidence_context.__dict__,
                "fallback_context": payload.fallback_context.__dict__,
                "output_control": payload.output_control.__dict__,
            },
            "output": {
                "final_hud_action": result.final_hud_action.__dict__,
                "final_voice_action": result.final_voice_action.__dict__ if result.final_voice_action is not None else None,
                "final_strategy_stack": result.final_strategy_stack.__dict__,
                "ordered_actions": [item.__dict__ for item in result.ordered_actions],
                "suppressed_actions": [item.__dict__ for item in result.suppressed_actions],
            },
        }

    def _build_strategy_action_model_candidates(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
    ) -> list[ModelCandidate]:
        """Build top-k model candidates from the local strategy-action baseline, if available."""

        if not self.strategy_action_runtime.enabled:
            return []
        candidates = self.strategy_action_runtime.predict_top_k(state=state, context=context, k=2)
        fuel_source = str(state.raw.get("fuel_laps_remaining_source", ""))
        fuel_in_tank = float(state.raw.get("fuel_in_tank", 0.0))
        fuel_capacity = float(state.raw.get("fuel_capacity", 0.0))
        tank_ratio = (fuel_in_tank / fuel_capacity) if fuel_capacity > 0.0 else 0.0
        fuel_mainline_allowed = (
            (state.lap_number > 1 and fuel_source == "derived_from_sample_consumption")
            or tank_ratio <= 0.08
        )
        if fuel_mainline_allowed:
            return candidates
        return [candidate for candidate in candidates if candidate.code != "LOW_FUEL"]

    def _classify_track_zone(self, lap_distance: float) -> str:
        """Fallback coarse track-zone classifier used when no track model exists."""

        # 备注:
        # 当前区段分类先用圈距粗分，后续接入正式赛道地图或 braking zone
        # 数据后，再替换为赛道级分段模型。
        if lap_distance < 700 or 3500 <= lap_distance < 4200:
            return "deployment_straight"
        if 700 <= lap_distance < 1400 or 4200 <= lap_distance < 4900:
            return "braking_entry"
        return "apex_rotation"

    def _usage_bias(self, track_usage: str) -> dict[str, int]:
        """Resolve configured weight offsets for the current track usage."""

        # 备注:
        # usage 权重已外置到 data/strategy/usage_hooks.json。
        # 这里仅负责读取并提供默认回退，不再维护内嵌常量表。
        return self.usage_hooks.get(track_usage or "", {"attack": 0, "ers": 0, "defend": 0, "tyre": 0, "dynamics": 0})

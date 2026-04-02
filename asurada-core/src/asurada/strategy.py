from __future__ import annotations

from .arbiter import (
    ArbiterInput,
    ModelCandidate,
    OutputControl,
    RuleCandidate,
    StrategyArbiterV2,
    TacticalContext,
)
from .confidence import StrategyUncertaintyLayer
from .config import StrategyThresholds, load_usage_hooks
from .fallback import StrategyFallbackPolicy
from .interaction import (
    build_asr_stage_event,
    build_confirmation_policy,
    build_query_normalization_event,
    build_structured_query_schema,
    build_task_handle,
    build_strategy_stage_event,
    build_system_strategy_input_event,
    route_structured_query,
)
from .long_horizon import LongHorizonStrategyBaseline, PitWindowSupport
from .models import (
    ContextProfile,
    RiskProfile,
    SessionState,
    StateAssessment,
    StrategyCandidate,
    StrategyDecision,
    StrategyMessage,
)
from .model_runtime import (
    DrivingQualityRuntimeSet,
    RivalPressureRuntimeSet,
    DEFAULT_DEFENCE_COST_REPORT,
    ResourceRiskModelRuntime,
    ResourceRiskRuntimeSet,
    StrategyActionModelRuntime,
    TyreDegradationTrendRuntimeSet,
)
from .session_router import SessionModeRouter, SessionRoute
from .state_machine import TacticalStateMachine
from .track_model import load_track_profile


class StrategyEngine:
    """Run the four-stage strategy pipeline for one normalized frame."""

    def __init__(self, thresholds: StrategyThresholds, usage_hooks_path=None) -> None:
        self.thresholds = thresholds
        self.usage_hooks = load_usage_hooks(usage_hooks_path) if usage_hooks_path is not None else {}
        self.arbiter_v2 = StrategyArbiterV2()
        self.strategy_action_runtime = StrategyActionModelRuntime()
        self.resource_risk_runtime = ResourceRiskRuntimeSet()
        self.rival_pressure_runtime = RivalPressureRuntimeSet()
        self.driving_quality_runtime = DrivingQualityRuntimeSet()
        self.tyre_degradation_trend_runtime = TyreDegradationTrendRuntimeSet()
        self.pit_window_support = PitWindowSupport()
        self.long_horizon_strategy = LongHorizonStrategyBaseline()
        self.defence_cost_runtime = ResourceRiskModelRuntime(
            name="defence_cost",
            report_path=DEFAULT_DEFENCE_COST_REPORT,
        )
        self.uncertainty_layer = StrategyUncertaintyLayer()
        self.fallback_policy = StrategyFallbackPolicy()
        self.session_mode_router = SessionModeRouter()
        self.tactical_state_machine = TacticalStateMachine()
        self._last_tactical_resolution_by_session: dict[str, object] = {}
        self._last_primary_action_by_session: dict[str, str] = {}

    def evaluate(self, state: SessionState, history: list[SessionState] | None = None) -> StrategyDecision:
        """Evaluate one frame and return ranked strategy messages plus debug data."""

        # 备注:
        # 这里保留稳定的四层流程，后续接趋势模型、对手建模、进站收益评估时，
        # 直接插入对应层即可，不需要再把整套策略引擎推倒重写。
        context = self._build_context(state, history or [state])
        session_route = self.session_mode_router.resolve(state)
        assessment = self._assess_state(state)
        risk_profile, risk_explain = self._score_risks(state, assessment, context)
        candidates = self._apply_session_route(
            self._build_candidates(state, assessment, risk_profile, context),
            session_route=session_route,
        )
        legacy_messages = self._arbitrate(candidates)
        arbiter_sidecar = self._build_arbiter_sidecar(
            state,
            history or [state],
            context,
            candidates,
            assessment,
            session_route,
        )
        self._attach_long_horizon_debug_text(arbiter_sidecar)
        messages = self._resolve_final_messages(legacy_messages, arbiter_sidecar)
        session_key = str(state.session_uid)
        tactical_machine_debug = ((arbiter_sidecar.get("input", {}) or {}).get("tactical_state_machine", {}) or {})
        self._last_tactical_resolution_by_session[session_key] = tactical_machine_debug
        self._last_primary_action_by_session[session_key] = messages[0].code if messages else "NONE"
        usage_bias = self._usage_bias(context.track_usage)
        interaction_input_event = build_system_strategy_input_event(
            state=state,
            primary_message=messages[0] if messages else None,
            session_mode=session_route.session_mode,
        )
        structured_query = build_structured_query_schema(interaction_input_event)
        query_route = route_structured_query(structured_query)
        confirmation_policy = build_confirmation_policy(
            input_event=interaction_input_event,
            schema=structured_query,
            route=query_route,
        )
        task_handle = build_task_handle(
            input_event=interaction_input_event,
            route=query_route,
            confirmation_policy=confirmation_policy,
        )
        pipeline_log = {
            "asr": build_asr_stage_event(interaction_input_event).to_dict(),
            "query_normalization": build_query_normalization_event(interaction_input_event).to_dict(),
            "query_route": query_route.to_dict(),
            "confirmation_policy": confirmation_policy.to_dict(),
            "strategy": build_strategy_stage_event(
                input_event=interaction_input_event,
                session_mode=session_route.session_mode,
                primary_action_code=messages[0].code if messages else "NONE",
                final_message_count=len(messages),
                rule_candidate_count=len((arbiter_sidecar.get("input", {}) or {}).get("rule_candidates", [])),
                model_candidate_count=len((arbiter_sidecar.get("input", {}) or {}).get("model_candidates", [])),
                confidence_level=str(
                    ((arbiter_sidecar.get("input", {}) or {}).get("confidence_context", {}) or {}).get("confidence_level")
                    or "unknown"
                ),
                fallback_mode=str(
                    ((arbiter_sidecar.get("input", {}) or {}).get("fallback_context", {}) or {}).get("fallback_mode")
                    or "none"
                ),
            ).to_dict(),
        }
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
                "pit_window_support": ((arbiter_sidecar.get("input", {}) or {}).get("pit_window_support") or {}),
                "long_horizon_strategy": ((arbiter_sidecar.get("input", {}) or {}).get("long_horizon_strategy") or {}),
                "session_route": {
                    "session_mode": session_route.session_mode,
                    "allowed_action_codes": sorted(session_route.allowed_action_codes),
                    "allow_timing_actions": session_route.allow_timing_actions,
                    "allow_race_resource_actions": session_route.allow_race_resource_actions,
                    "route_reason": session_route.route_reason,
                },
                "candidates": [candidate.__dict__ for candidate in candidates],
                "arbiter_v2": arbiter_sidecar,
                "interaction_input_event": interaction_input_event.to_dict(),
                "structured_query": structured_query.to_dict(),
                "query_route": query_route.to_dict(),
                "confirmation_policy": confirmation_policy.to_dict(),
                "task_handle": task_handle.to_dict(),
                "voice_pipeline_log": pipeline_log,
            },
        )

    def _attach_long_horizon_debug_text(self, arbiter_sidecar: dict) -> None:
        input_payload = (arbiter_sidecar.get("input", {}) or {}) if isinstance(arbiter_sidecar, dict) else {}
        sidecar_scores = (input_payload.get("sidecar_scores", {}) or {}) if isinstance(input_payload, dict) else {}
        pit_window_support = dict((input_payload.get("pit_window_support", {}) or {}))
        long_horizon_strategy = dict((input_payload.get("long_horizon_strategy", {}) or {}))

        pit_window_support["summary"] = self._format_pit_window_support_summary(pit_window_support)
        long_horizon_strategy["summary"] = self._format_long_horizon_summary(long_horizon_strategy)

        if isinstance(input_payload, dict):
            input_payload["pit_window_support"] = pit_window_support
            input_payload["long_horizon_strategy"] = long_horizon_strategy
        if isinstance(sidecar_scores, dict):
            sidecar_scores["pit_window_support"] = pit_window_support
            sidecar_scores["long_horizon_strategy"] = long_horizon_strategy

    def _format_pit_window_support_summary(self, payload: dict) -> str:
        if not payload or not payload.get("enabled", False):
            return "当前 session route 不启用进站窗口支持"

        parts: list[str] = []
        pit_window_open_prob = payload.get("pit_window_open_prob")
        if isinstance(pit_window_open_prob, (int, float)):
            parts.append(f"进站开窗概率 {float(pit_window_open_prob):.2f}")

        lap_life_remaining_est = payload.get("lap_life_remaining_est")
        if isinstance(lap_life_remaining_est, (int, float)):
            parts.append(f"预计当前胎还可支撑 {float(lap_life_remaining_est):.1f} 圈")

        compound_rule_state = payload.get("compound_rule_state")
        if compound_rule_state:
            parts.append(f"干胎规则状态 {compound_rule_state}")

        remaining_required_stops = payload.get("remaining_required_stops")
        if isinstance(remaining_required_stops, (int, float)):
            parts.append(f"剩余必要进站 {int(remaining_required_stops)} 次")

        rejoin_traffic_penalty = payload.get("rejoin_traffic_penalty")
        if isinstance(rejoin_traffic_penalty, (int, float)):
            parts.append(f"回场交通代价 {float(rejoin_traffic_penalty):.1f}")

        return "；".join(parts) if parts else "进站窗口支持已启用"

    def _format_long_horizon_summary(self, payload: dict) -> str:
        if not payload or not payload.get("enabled", False):
            rationale = payload.get("rationale") or []
            if rationale:
                return str(rationale[0])
            return "当前 session route 不启用长周期进站规划"

        parts: list[str] = []
        recommended_pit_lap = payload.get("recommended_pit_lap")
        if isinstance(recommended_pit_lap, (int, float)):
            parts.append(f"推荐进站圈 {int(recommended_pit_lap)}")

        pit_window_start_lap = payload.get("pit_window_start_lap")
        pit_window_end_lap = payload.get("pit_window_end_lap")
        if isinstance(pit_window_start_lap, (int, float)) and isinstance(pit_window_end_lap, (int, float)):
            parts.append(f"窗口 {int(pit_window_start_lap)}-{int(pit_window_end_lap)}")

        recommended_compound = payload.get("recommended_compound")
        if recommended_compound:
            parts.append(f"推荐换胎 {recommended_compound}")

        recommended_set_index = payload.get("recommended_set_index")
        recommended_set_available = payload.get("recommended_set_available")
        if isinstance(recommended_set_index, (int, float)):
            parts.append(f"推荐轮胎组 #{int(recommended_set_index)}")
        elif recommended_compound and recommended_set_available is False:
            parts.append("当前无可用轮胎组")

        strategy_confidence = payload.get("strategy_confidence")
        if isinstance(strategy_confidence, (int, float)):
            parts.append(f"置信度 {float(strategy_confidence):.2f}")

        aggression_bias = payload.get("aggression_bias")
        if isinstance(aggression_bias, (int, float)):
            parts.append(f"攻击倾向 {float(aggression_bias):+.2f}")

        rationale = payload.get("rationale") or []
        if rationale:
            parts.append(str(rationale[0]))

        return "；".join(parts) if parts else "长周期规划已启用"

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
        derived_fuel_available = state.lap_number > 1 and fuel_source == "derived_from_sample_consumption"
        fuel_state = (
            "critical"
            if (derived_fuel_available and fuel_margin_laps <= 0.3)
            or (not derived_fuel_available and tank_ratio <= 0.08)
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
        history: list[SessionState],
        context: ContextProfile,
        candidates: list[StrategyCandidate],
        assessment: StateAssessment,
        session_route: SessionRoute,
    ) -> dict[str, object]:
        """Build a sidecar arbiter output without changing the current final messages."""
        previous_state = history[-2] if len(history) >= 2 else None
        session_key = str(state.session_uid)
        previous_resolution_payload = self._last_tactical_resolution_by_session.get(session_key)
        previous_resolution = None
        if isinstance(previous_resolution_payload, dict):
            previous_resolution = self._coerce_tactical_resolution(previous_resolution_payload)
        tactical_resolution = self.tactical_state_machine.resolve(
            state=state,
            previous_state=previous_state,
            previous_resolution=previous_resolution,
            last_output_action=self._last_primary_action_by_session.get(session_key),
            assessment=assessment,
            context=context,
        )

        model_candidates = self._build_strategy_action_model_candidates(
            state=state,
            context=context,
            session_route=session_route,
        )
        confidence_resolution = self.uncertainty_layer.evaluate(
            state=state,
            context=context,
            model_candidates=model_candidates,
            tactical_state=tactical_resolution.tactical_state,
        )
        resource_models = self.resource_risk_runtime.predict_all(state=state, context=context)
        rival_pressure_models = self.rival_pressure_runtime.predict_all(state=state, context=context)
        driving_quality_models = self.driving_quality_runtime.predict_all(state=state, context=context)
        tyre_degradation_trend_models = self.tyre_degradation_trend_runtime.predict_all(state=state, context=context)
        defence_cost_model = self.defence_cost_runtime.predict_score(state=state, context=context)
        pit_window_support = self.pit_window_support.evaluate(
            state=state,
            context=context,
            resource_models=resource_models,
            rival_pressure_models=rival_pressure_models,
            tyre_degradation_trend_models=tyre_degradation_trend_models,
        )
        long_horizon_strategy = self.long_horizon_strategy.plan(
            state=state,
            session_route=session_route,
            support=pit_window_support,
            resource_models=resource_models,
            rival_pressure_models=rival_pressure_models,
        )
        tactical_context = TacticalContext(
            tactical_state=tactical_resolution.tactical_state,
            state_priority_hint=tactical_resolution.state_priority_hint,
            state_lock=tactical_resolution.state_lock,
            state_transition=tactical_resolution.state_transition,
        )
        fallback_resolution = self.fallback_policy.resolve(
            state=state,
            context=context,
            session_route=session_route,
            confidence_resolution=confidence_resolution,
            tactical_context=tactical_context,
            rule_candidates=[RuleCandidate.from_strategy_candidate(candidate) for candidate in candidates],
            model_candidates=model_candidates,
        )
        rule_candidates = [RuleCandidate.from_strategy_candidate(candidate) for candidate in candidates]
        payload = ArbiterInput(
            rule_candidates=rule_candidates,
            model_candidates=model_candidates,
            tactical_context=tactical_context,
            confidence_context=confidence_resolution.confidence_context,
            fallback_context=fallback_resolution.fallback_context,
            output_control=fallback_resolution.output_control,
            sidecar_scores={
                "resource_models": resource_models,
                "rival_pressure_models": rival_pressure_models,
                "driving_quality_models": driving_quality_models,
                "tyre_degradation_trend_models": tyre_degradation_trend_models,
                "defence_cost_model": defence_cost_model,
                "pit_window_support": pit_window_support.to_dict(),
                "long_horizon_strategy": long_horizon_strategy.to_dict(),
            },
        )
        result = self.arbiter_v2.arbitrate(payload)
        return {
            "input": {
                "rule_candidates": [item.__dict__ for item in payload.rule_candidates],
                "model_candidates": [item.__dict__ for item in payload.model_candidates],
                "tactical_context": payload.tactical_context.__dict__,
                "tactical_state_machine": {
                    "previous_tactical_state": tactical_resolution.previous_tactical_state,
                    "tactical_state": tactical_resolution.tactical_state,
                    "state_transition": tactical_resolution.state_transition,
                    "state_priority_hint": tactical_resolution.state_priority_hint,
                    "state_lock": tactical_resolution.state_lock,
                    "recommended_action": tactical_resolution.recommended_action,
                    "position_lost_recently": tactical_resolution.position_lost_recently,
                    "position_gain_recently": tactical_resolution.position_gain_recently,
                },
                "confidence_context": payload.confidence_context.__dict__,
                "fallback_context": payload.fallback_context.__dict__,
                "output_control": payload.output_control.__dict__,
                "sidecar_scores": payload.sidecar_scores,
                "uncertainty_layer": {
                    "fallback_recommended": confidence_resolution.fallback_recommended,
                    "fallback_reason": confidence_resolution.fallback_reason,
                    "session_mode": confidence_resolution.session_mode,
                },
                "fallback_policy": {
                    "policy_name": fallback_resolution.policy_name,
                    "policy_reasons": fallback_resolution.policy_reasons,
                },
                "resource_models": resource_models,
                "rival_pressure_models": rival_pressure_models,
                "driving_quality_models": driving_quality_models,
                "tyre_degradation_trend_models": tyre_degradation_trend_models,
                "defence_cost_model": defence_cost_model,
                "pit_window_support": pit_window_support.to_dict(),
                "long_horizon_strategy": long_horizon_strategy.to_dict(),
                "session_route": {
                    "session_mode": session_route.session_mode,
                    "allowed_action_codes": sorted(session_route.allowed_action_codes),
                    "allow_timing_actions": session_route.allow_timing_actions,
                    "allow_race_resource_actions": session_route.allow_race_resource_actions,
                    "route_reason": session_route.route_reason,
                },
            },
            "output": {
                "final_hud_action": result.final_hud_action.__dict__,
                "final_voice_action": result.final_voice_action.__dict__ if result.final_voice_action is not None else None,
                "final_strategy_stack": result.final_strategy_stack.__dict__,
                "ordered_actions": [item.__dict__ for item in result.ordered_actions],
                "suppressed_actions": [item.__dict__ for item in result.suppressed_actions],
            },
        }

    def _coerce_tactical_resolution(self, payload: dict[str, object]):
        from .state_machine import TacticalStateResolution

        return TacticalStateResolution(
            previous_tactical_state=str(payload.get("previous_tactical_state") or "neutral"),
            tactical_state=str(payload.get("tactical_state") or "neutral"),
            state_transition=str(payload.get("state_transition") or "stable"),
            state_priority_hint=str(payload.get("state_priority_hint")) if payload.get("state_priority_hint") is not None else None,
            state_lock=bool(payload.get("state_lock", False)),
            recommended_action=str(payload.get("recommended_action") or "NONE"),
            position_lost_recently=bool(payload.get("position_lost_recently", False)),
            position_gain_recently=bool(payload.get("position_gain_recently", False)),
            history_hold_applied=bool(payload.get("history_hold_applied", False)),
            history_anchor_action=str(payload.get("history_anchor_action")) if payload.get("history_anchor_action") is not None else None,
        )

    def _build_strategy_action_model_candidates(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        session_route: SessionRoute,
    ) -> list[ModelCandidate]:
        """Build top-k model candidates from the local strategy-action baseline, if available."""

        if not self.strategy_action_runtime.enabled:
            return []
        candidates = self.strategy_action_runtime.predict_top_k(state=state, context=context, k=2)
        fuel_source = str(state.raw.get("fuel_laps_remaining_source", ""))
        fuel_in_tank = float(state.raw.get("fuel_in_tank", 0.0))
        fuel_capacity = float(state.raw.get("fuel_capacity", 0.0))
        tank_ratio = (fuel_in_tank / fuel_capacity) if fuel_capacity > 0.0 else 0.0
        derived_fuel_available = state.lap_number > 1 and fuel_source == "derived_from_sample_consumption"
        fuel_mainline_allowed = (
            derived_fuel_available
            or tank_ratio <= 0.08
        )
        filtered = [candidate for candidate in candidates if candidate.code in session_route.allowed_action_codes]
        if fuel_mainline_allowed:
            return filtered
        return [candidate for candidate in filtered if candidate.code != "LOW_FUEL"]

    def _apply_session_route(
        self,
        candidates: list[StrategyCandidate],
        *,
        session_route: SessionRoute,
    ) -> list[StrategyCandidate]:
        """Filter rule candidates against the current session-mode route."""

        return [candidate for candidate in candidates if candidate.code in session_route.allowed_action_codes]

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

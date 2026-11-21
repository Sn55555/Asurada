from __future__ import annotations

from .pit_shadow import PitShadow

from .assessment import assess_fuel, assess_domain
from .context_window import context_samples, input_means
from .model_temporal_features import preview_segments, closing_rate_from_recent_history, PREVIEW_OFFSETS_M
from .models import DecisionRecord
from copy import deepcopy

from .arbiter import (
    ArbiterInput,
    ModelCandidate,
    OutputControl,
    RuleCandidate,
    StrategyArbiterV2,
    TacticalContext,
)
from .attack_forecast import AttackForecast
from .attack_taxonomy import (
    infer_attack_commit_method,
    infer_attack_setup_method,
    infer_corner_overtake_class,
)
from .confidence import StrategyUncertaintyLayer
from .config import StrategyThresholds, load_usage_hooks
from .wheel_telemetry import tyre_alert
from .wing_damage import FRONT_WING_DAMAGE, SIDES, confirmed_wing_damage, wing_radio_text, wing_values
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
from .model_admission import MODEL_NAMES, ModelAdmissionPolicy
from .contributor_admission import ContributorPolicy, SCORING_FIELDS
from .observation_lane import ObservationLane
from .planning_lane import PlanningLane, planning_event_key
from dataclasses import replace
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

    def __init__(self, thresholds: StrategyThresholds, usage_hooks_path=None, *, model_policy: ModelAdmissionPolicy | None = None, contributor_policy: ContributorPolicy | None = None) -> None:
        self.pit_shadow = PitShadow()
        self.attack_forecast = AttackForecast()
        self.defence_forecast = AttackForecast(rear=True)
        self.thresholds = thresholds
        self.model_policy = model_policy or ModelAdmissionPolicy()
        if any(self.model_policy.mode(name) == 'active' for name in MODEL_NAMES) and self.model_policy.context_window_version != 'source-time-weighted-v1':
            raise ValueError('active_models_require_current_context_window_evaluation')
        self.contributor_policy = contributor_policy or ContributorPolicy()
        self.observation_lane = None
        self.planning_lane = None
        modes = {name: self.model_policy.mode(name) for name in MODEL_NAMES}
        self.usage_hooks = load_usage_hooks(usage_hooks_path) if usage_hooks_path is not None else {}
        self.arbiter_v2 = StrategyArbiterV2()
        self.strategy_action_runtime = StrategyActionModelRuntime(mode=modes["strategy_action"])
        self.resource_risk_runtime = ResourceRiskRuntimeSet(modes=modes)
        self.rival_pressure_runtime = RivalPressureRuntimeSet(modes=modes)
        self.driving_quality_runtime = DrivingQualityRuntimeSet(modes=modes)
        self.tyre_degradation_trend_runtime = TyreDegradationTrendRuntimeSet(modes=modes)
        self.pit_window_support = PitWindowSupport()
        self.long_horizon_strategy = LongHorizonStrategyBaseline()
        self.defence_cost_runtime = ResourceRiskModelRuntime(
            name="defence_cost",
            report_path=DEFAULT_DEFENCE_COST_REPORT,
            mode=modes["defence_cost"],
        )
        admission_runtimes = {'strategy_action': self.strategy_action_runtime, 'defence_cost': self.defence_cost_runtime}
        for group in (self.resource_risk_runtime, self.rival_pressure_runtime,
                      self.driving_quality_runtime, self.tyre_degradation_trend_runtime):
            admission_runtimes.update(group._runtimes)
        self._verified_model_evidence = self.model_policy.validate_assets(admission_runtimes)
        self.uncertainty_layer = StrategyUncertaintyLayer()
        self.fallback_policy = StrategyFallbackPolicy()
        self.session_mode_router = SessionModeRouter()
        self.tactical_state_machine = TacticalStateMachine()
        self._last_tactical_resolution_by_session: dict[str, object] = {}
        self._last_primary_action_by_session: dict[str, str] = {}

    def enable_background_observations(self) -> None:
        if self.observation_lane is None:
            self.observation_lane = ObservationLane()
        else:
            self.observation_lane.reopen()

    def enable_background_planning(self) -> None:
        if self.planning_lane is None:
            self.planning_lane = PlanningLane()
        else:
            self.planning_lane.reopen()

    def _plan(self, state, session_route, context, resources, rivals, trends, task=None):
        if task is not None:
            task.remaining()
        pit_result = None
        if self.contributor_policy.mode("pit_window_support") != "disabled":
            pit_result = self.pit_window_support.evaluate(
                state=state, session_route=session_route, context=context,
                resource_models=resources, rival_pressure_models=rivals,
                tyre_degradation_trend_models=trends)
        if task is not None:
            task.remaining()
        long_result = None
        if pit_result is not None and self.contributor_policy.mode("long_horizon_strategy") != "disabled":
            long_result = self.long_horizon_strategy.plan(
                state=state, session_route=session_route, support=pit_result,
                resource_models=resources, rival_pressure_models=rivals)
        if task is not None:
            task.remaining()
        return {
            "pit_window_support": pit_result.to_dict() if pit_result is not None else {"enabled": False, "reason": "contributor_disabled"},
            "long_horizon_strategy": long_result.to_dict() if long_result is not None else {"enabled": False, "reason": "contributor_or_dependency_disabled"},
        }

    def _predict_group(self, runtime, *, state, context):
        if self.observation_lane is None:
            return runtime.predict_all(state=state, context=context)
        return {name: model.predict_score(state=state, context=context)
                for name, model in runtime._runtimes.items() if self.model_policy.mode(name) == "active"}

    def _offer_observation(self, state, context, session_route):
        if self.observation_lane is None:
            return None
        def build_work(task_context):
            frozen_state = deepcopy(replace(state, assessment=None, decision_record=None))
            frozen_context = deepcopy(context)
            def work():
                results = {}
                def predict(model):
                    task_context.remaining()
                    result = model.predict_score(state=frozen_state, context=frozen_context)
                    task_context.remaining()
                    return result
                for label, runtime in (("resources", self.resource_risk_runtime), ("rivals", self.rival_pressure_runtime),
                                       ("driving", self.driving_quality_runtime), ("trends", self.tyre_degradation_trend_runtime)):
                    results[label] = {name: predict(model)
                                      for name, model in runtime._runtimes.items() if self.model_policy.mode(name) == "observe"}
                if self.model_policy.mode("defence_cost") == "observe":
                    results["defence_cost"] = predict(self.defence_cost_runtime)
                if self.model_policy.mode("strategy_action") == "observe":
                    task_context.remaining()
                    results["strategy_action"] = [item.__dict__ for item in self._build_strategy_action_model_candidates(
                        state=frozen_state, context=frozen_context, session_route=session_route)]
                    results["strategy_action_quality"] = self._strategy_action_quality()
                return results
            return work
        return self.observation_lane.offer(binding={"session_uid": state.session_uid, "epoch": state.session_epoch,
                                                     "source_timestamp_ms": state.source_timestamp_ms,
                                                     "snapshot_id": state.assessment.snapshot_id}, build_work=build_work)

    def evaluate(self, state: SessionState, history: list[SessionState] | None = None) -> StrategyDecision:
        """Evaluate one frame and return ranked strategy messages plus debug data."""

        # 备注:
        # 这里保留稳定的四层流程，后续接趋势模型、对手建模、进站收益评估时，
        # 直接插入对应层即可，不需要再把整套策略引擎推倒重写。
        history = [item for item in (history or [state])
                   if (item.session_uid, item.session_epoch) == (state.session_uid, state.session_epoch)]
        context = self._build_context(state, history or [state])
        session_route = self.session_mode_router.resolve(state)
        assessment = self._assess_state(state)
        risk_profile, risk_explain = self._score_risks(state, assessment, context)
        candidates = self._apply_session_route(
            self._build_candidates(state, assessment, risk_profile, context),
            session_route=session_route,
        )
        wing_sides = confirmed_wing_damage(state, history)
        if (wing_sides and FRONT_WING_DAMAGE in session_route.allowed_action_codes
                and assessment.dynamics_state != "unstable" and assessment.race_state != "controlled"):
            subject = "、".join(SIDES[side] for side in wing_sides)
            title = f"{subject}受损，可能影响转向。"
            detail = wing_radio_text(wing_sides, levels=wing_values(state))
            candidates.append(StrategyCandidate(FRONT_WING_DAMAGE, 71, title, detail, "risk_response"))
        arbiter_sidecar = self._build_arbiter_sidecar(
            state,
            history or [state],
            context,
            candidates,
            assessment,
            session_route,
        )
        self._attach_long_horizon_debug_text(arbiter_sidecar)
        messages = self._resolve_final_messages(arbiter_sidecar)
        session_key = f"{state.session_uid}:{state.session_epoch}"
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
        domain = assess_domain(state, self.thresholds)
        from dataclasses import replace
        from .decision_identity import VERSION, decision_content_id
        arbitration = deepcopy(arbiter_sidecar.get("output", {}))
        admitted_inputs = arbiter_sidecar.get("input", {}).get("sidecar_scores", {})
        # Persist the input contract even when the verbose debug log is omitted.
        # These are arbitration inputs, not a claim that each changed an action.
        arbitration["planner_inputs"] = {
            "policy": self.contributor_policy.snapshot(),
            "contributions": {
                name: {
                    "scores": {key: value[key] for key in fields},
                    "binding": deepcopy(value.get("contribution_binding", {
                        "session_uid": state.session_uid, "epoch": state.session_epoch,
                        "snapshot_id": domain.snapshot_id,
                        "source_timestamp_ms": state.source_timestamp_ms,
                    })),
                    "validity": deepcopy(value.get("validity", {"scope": "snapshot_only"})),
                }
                for name, fields in SCORING_FIELDS.items()
                for value in [admitted_inputs.get(name, {})] if value
            },
        }
        record = DecisionRecord(
            decision_id='', identity_version=VERSION,
            snapshot_id=domain.snapshot_id, session_uid=state.session_uid,
            session_epoch=state.session_epoch, source_timestamp_ms=state.source_timestamp_ms,
            assessment=deepcopy(domain), actions=tuple(deepcopy(messages)),
            candidates=tuple(deepcopy(candidate.__dict__) for candidate in candidates),
            arbitration=arbitration,
            model_admission=deepcopy(arbiter_sidecar.get('input', {}).get('model_admission', {})),
        )
        record = replace(record, decision_id=decision_content_id(record))
        state.decision_record = record
        attack = self.attack_forecast.observe(state, session_route.allow_timing_actions)
        defence = self.defence_forecast.observe(state, session_route.allow_timing_actions, sections=self.attack_forecast.sections)
        return StrategyDecision(
            messages=messages,
            record=record,
            debug={
                "pit_broadcast_muted": state.raw.get("tyre_rule_settings", {}).get("session_type") in (15, 16, 17),
                "pit_timing_shadow": self.pit_shadow.observe(state),
                "attack_forecast": attack,
                "defence_forecast": defence,
                "player_position": state.player.position,
                "lap": state.lap_number,
                "track": state.track,
                "context": context.__dict__,
                "assessment": assessment.__dict__,
                "fuel_assessment": assess_fuel(state).to_dict(),
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
            if sidecar_scores.get("pit_window_support"):
                sidecar_scores["pit_window_support"] = pit_window_support
            if sidecar_scores.get("long_horizon_strategy"):
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
        if compound_rule_state != "unknown" and isinstance(remaining_required_stops, (int, float)):
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
            parts.append("可用胎组尚未确认")

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

        recent, coverage_ms = context_samples(state, history or [state])
        total = sum(weight for _, weight in recent)
        unstable_count = 0
        overload_count = 0

        for item, weight in recent:
            tags = set(item.player.status_tags)
            unstable_count += int("unstable" in tags)*weight
            overload_count += int("front_tyre_overload" in tags)*weight

        lap_distance = float(state.raw.get("lap_distance_m", 0.0))
        track_profile = load_track_profile(state.track)
        if track_profile is not None:
            classified = track_profile.classify(lap_distance)
            next_segment = track_profile.next_segment(lap_distance)
            track_zone = classified.zone_type
            track_segment = classified.zone_name
            track_usage = classified.usage
            next_track_segment = next_segment.zone_name
            next_track_usage = next_segment.usage
        else:
            track_zone = self._classify_track_zone(lap_distance)
            track_segment = "Generic Segment"
            track_usage = ""
            next_track_segment = "UNKNOWN"
            next_track_usage = "UNKNOWN"
        means, input_quality = input_means(recent, coverage_ms)
        avg_throttle, avg_brake, avg_steer = (means[name] for name in ('throttle','brake','steer'))
        corner_overtake_class = infer_corner_overtake_class(
            track_zone=track_zone,
            track_segment=track_segment,
            track_usage=track_usage,
        )
        attack_setup_method = infer_attack_setup_method(
            track_zone=track_zone,
            track_usage=track_usage,
            corner_overtake_class=corner_overtake_class,
        )
        attack_commit_method = infer_attack_commit_method(
            track_zone=track_zone,
            track_usage=track_usage,
            corner_overtake_class=corner_overtake_class,
        )

        if any(value is None for value in (avg_throttle, avg_brake, avg_steer)):
            driving_mode = 'unknown'
        elif avg_brake > 0.45:
            driving_mode = "brake_loaded"
        elif avg_throttle > 0.72 and avg_steer > 0.18:
            driving_mode = "push_exit"
        elif avg_steer > 0.28:
            driving_mode = "cornering"
        else:
            driving_mode = "straightline"

        tyre_age = state.player.tyre.age_laps
        tyre_age_factor = 12 if tyre_age >= 10 else 8 if tyre_age >= 6 else 2
        brake_phase_factor = 0 if avg_brake is None else 10 if avg_brake > 0.45 else 4 if avg_brake > 0.2 else 0
        throttle_phase_factor = 0 if avg_throttle is None else 8 if avg_throttle > 0.78 else 4 if avg_throttle > 0.55 else 0
        steering_phase_factor = 0 if avg_steer is None else 8 if avg_steer > 0.30 else 4 if avg_steer > 0.18 else 0

        return ContextProfile(
            gap_closing_rate_behind=closing_rate_from_recent_history(recent_states=history,
                current_gap=state.player.gap_behind_s,current_session_time_s=state.raw.get('session_time_s'),gap_side='behind'),
            next_two_segments=preview_segments(track_profile=track_profile,lap_distance_m=lap_distance,offsets=PREVIEW_OFFSETS_M)[2],
            history_coverage_ms=coverage_ms,
            input_quality=input_quality,
            recent_unstable_ratio=unstable_count / total,
            recent_front_overload_ratio=overload_count / total,
            driving_mode=driving_mode,
            track_zone=track_zone,
            track_segment=track_segment,
            track_usage=track_usage,
            corner_overtake_class=corner_overtake_class,
            attack_setup_method=attack_setup_method,
            attack_commit_method=attack_commit_method,
            next_track_segment=next_track_segment,
            next_track_usage=next_track_usage,
            tyre_age_factor=tyre_age_factor,
            brake_phase_factor=brake_phase_factor,
            throttle_phase_factor=throttle_phase_factor,
            steering_phase_factor=steering_phase_factor,
        )

    def _assess_state(self, state: SessionState) -> StateAssessment:
        """Convert the current frame into discrete state labels."""

        return assess_domain(state, self.thresholds).labels

    def _score_risks(
        self,
        state: SessionState,
        assessment: StateAssessment,
        context: ContextProfile,
    ) -> tuple[RiskProfile, dict[str, dict[str, int | str]]]:
        """Score numeric risks and opportunities from state plus context."""

        usage_bias = self._usage_bias(context.track_usage)
        tyre_context_bonus = context.tyre_age_factor
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
                "base": 72 if assessment.dynamics_state == "unstable" else 10,
                "recent_unstable_bonus": int(context.recent_unstable_ratio * 25) if assessment.dynamics_state == "unstable" else int(context.recent_unstable_ratio * 12),
                "steering_phase_factor": context.steering_phase_factor,
                "track_zone_bonus": dynamics_zone_bonus,
                "usage_hook": usage_bias["dynamics"] if assessment.dynamics_state == "unstable" else max(usage_bias["dynamics"], 0),
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
        front_rival = self._closest_rival(state, player.position - 1)
        rear_rival = self._closest_rival(state, player.position + 1)
        candidates: list[StrategyCandidate] = []
        completed_laps = max(state.lap_number - 1, 0)
        remaining_race_laps = max(state.total_laps - completed_laps, 0)
        fuel_margin_laps = player.fuel_laps_remaining - remaining_race_laps

        if (state.raw.get("marshal_zone_flag") == 3 and not state.raw.get("session_paused")
                and assessment.race_state != "controlled" and assessment.dynamics_state != "unstable"):
            candidates.append(StrategyCandidate("LOCAL_YELLOW", 99, "本区黄旗，减速，禁止超车。",
                                                "当前所在裁判区为黄旗。", "risk_response"))
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
                    detail=assess_fuel(state).describe(),
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
                    detail=self._attack_window_detail(
                        state=state,
                        context=context,
                        front_rival=front_rival,
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
                    detail=self._defend_window_detail(
                        state=state,
                        context=context,
                        rear_rival=rear_rival,
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
                    detail=self._dynamics_unstable_detail(state=state, context=context),
                    layer="dynamics",
                )
            )
        else:
            raw = state.raw
            alert = tyre_alert(raw.get("tyres_damage_pct"), raw.get("tyres_wear_pct"))
            if alert and not raw.get("session_paused") and raw.get("result_status", 2) == 2:
                code, title = alert
                candidates.append(StrategyCandidate(
                    code=code, priority=72, title=title,
                    detail=title,
                    layer="risk_response",
                ))

        return candidates

    def _closest_rival(self, state: SessionState, target_position: int):
        if target_position <= 0:
            return None
        for rival in state.rivals:
            if rival.position == target_position:
                return rival
        return None

    def _attack_window_detail(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        front_rival,
    ) -> str:
        method_parts: list[str] = []
        if context.attack_setup_method != "none":
            method_parts.append(f"铺垫方式 {context.attack_setup_method}")
        if context.attack_commit_method != "none":
            method_parts.append(f"兑现方式 {context.attack_commit_method}")
        if context.corner_overtake_class != "general":
            method_parts.append(f"弯道类型 {context.corner_overtake_class}")
        method_text = "，".join(method_parts)
        gap = state.player.gap_ahead_s
        base = (
            f"前车差距 {gap:.1f}s，DRS 可用，"
            f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}）"
            f"{'，' + method_text if method_text else ''}，准备完成压迫。"
        )
        if front_rival is None:
            return base
        if getattr(front_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
            return (
                f"前车 {front_rival.name} 已进入 {front_rival.pit_status}，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），先准备抓窗口变化。"
            )
        if getattr(front_rival, "gap_confidence_behind", None) == "medium":
            return (
                f"前车 {front_rival.name} 当前窗口差距约 {gap:.1f}s，但进攻依据只有中可信度估算，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}）"
                f"{'，' + method_text if method_text else ''}，先压迫再确认兑现。"
            )
        return base

    def _defend_window_detail(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        rear_rival,
    ) -> str:
        gap = state.player.gap_behind_s
        base = (
            f"后车差距 {gap:.1f}s，当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
            "出弯牵引和电量配置进入防守模式。"
        )
        if rear_rival is None:
            return base
        if getattr(rear_rival, "drs_available", False):
            return (
                f"后车 {rear_rival.name} 差距 {gap:.1f}s 且已具备 DRS，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
                "出弯牵引和电量配置进入防守模式。"
            )
        if getattr(rear_rival, "pit_status", None) in {"PITTING", "IN_PIT_AREA"}:
            return (
                f"后车 {rear_rival.name} 已进入 {rear_rival.pit_status}，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
                "防守压力可能自行回落，但先守住出弯。"
            )
        if isinstance(getattr(rear_rival, "engine_damage_pct", None), int) and rear_rival.engine_damage_pct >= 35:
            return (
                f"后车 {rear_rival.name} 差距 {gap:.1f}s，但发动机损伤约 {rear_rival.engine_damage_pct}%，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
                "先稳住防守窗口，等待它自己掉速。"
            )
        if getattr(rear_rival, "gap_confidence_ahead", None) == "medium":
            return (
                f"后车 {rear_rival.name} 当前压力差距约 {gap:.1f}s，但依据只有中可信度估算，"
                f"当前区段 {context.track_segment}（{context.track_zone} / {context.track_usage or 'general'}），"
                "先按防守模式准备。"
            )
        return base

    def _dynamics_unstable_detail(self, *, state: SessionState, context: ContextProfile) -> str:
        raw = state.raw
        max_slip_angle = self._max_abs(raw.get("wheel_slip_angle"))
        yaw_rate = self._angular_rate(raw, "yaw")
        yaw_accel = self._angular_accel(raw, "yaw")
        roll_balance = self._roll_balance(raw)
        if max_slip_angle is not None and max_slip_angle >= 0.12:
            return (
                f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
                f"当前侧滑角峰值约 {max_slip_angle:.3f}，用途 {context.track_usage or 'general'}，"
                "压 curb 与转向输入需要收敛。"
            )
        if yaw_rate is not None and yaw_rate >= 0.85:
            return (
                f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
                f"当前偏航角速度约 {yaw_rate:.3f}，用途 {context.track_usage or 'general'}，"
                "先把车尾姿态稳定住。"
            )
        if yaw_accel is not None and yaw_accel >= 2.4:
            return (
                f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
                f"当前偏航角加速度约 {yaw_accel:.3f}，用途 {context.track_usage or 'general'}，"
                "转向节奏需要更平顺。"
            )
        if roll_balance is not None and roll_balance >= 1.0:
            return (
                f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
                f"当前前后滚转角差约 {roll_balance:.3f}，用途 {context.track_usage or 'general'}，"
                "载荷转移需要更平滑。"
            )
        return (
            f"车辆姿态进入 unstable 标签，最近窗口不稳占比 {context.recent_unstable_ratio:.2f}，"
            f"当前用途 {context.track_usage or 'general'}，压 curb 与转向输入需要收敛。"
        )

    def _scalar(self, value: object) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _angular_rate(self, raw: dict[str, object], axis: str) -> float | None:
        angular_velocity = raw.get("angular_velocity")
        if not isinstance(angular_velocity, dict):
            return None
        try:
            return abs(float(angular_velocity.get(axis, 0.0) or 0.0))
        except (TypeError, ValueError):
            return None

    def _angular_accel(self, raw: dict[str, object], axis: str) -> float | None:
        angular_acceleration = raw.get("angular_acceleration")
        if not isinstance(angular_acceleration, dict):
            return None
        try:
            return abs(float(angular_acceleration.get(axis, 0.0) or 0.0))
        except (TypeError, ValueError):
            return None

    def _roll_balance(self, raw: dict[str, object]) -> float | None:
        front_roll = self._scalar(raw.get("front_roll_angle"))
        rear_roll = self._scalar(raw.get("rear_roll_angle"))
        if front_roll is None or rear_roll is None:
            return None
        return abs(front_roll - rear_roll)

    def _max_abs(self, values: object) -> float | None:
        if not isinstance(values, list):
            return None
        normalized: list[float] = []
        for item in values:
            try:
                normalized.append(abs(float(item)))
            except (TypeError, ValueError):
                continue
        if not normalized:
            return None
        return max(normalized)

    def _resolve_final_messages(self, arbiter_sidecar: dict[str, object]) -> list[StrategyMessage]:
        """Use the arbiter as the single authority, including an empty result.

        A legacy sort cannot recover a malformed arbiter contract: it would
        bypass confidence, deduplication and model-admission decisions.
        """
        output = arbiter_sidecar.get("output") if isinstance(arbiter_sidecar, dict) else None
        actions = output.get("ordered_actions") if isinstance(output, dict) else None
        if not isinstance(actions, list):
            raise ValueError("invalid_arbiter_output")
        resolved = []
        for item in actions[:3]:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                raise ValueError("invalid_arbiter_action")
            resolved.append(StrategyMessage(
                code=item["code"], priority=int(item.get("priority") or 0),
                title=str(item.get("title") or item["code"]), detail=str(item.get("detail") or "")))
        return resolved

    def _build_arbiter_sidecar(
        self,
        state: SessionState,
        history: list[SessionState],
        context: ContextProfile,
        candidates: list[StrategyCandidate],
        assessment: StateAssessment,
        session_route: SessionRoute,
    ) -> dict[str, object]:
        """Build arbitration inputs, admitting only explicitly approved model outputs."""
        previous_state = history[-2] if len(history) >= 2 else None
        session_key = f"{state.session_uid}:{state.session_epoch}"
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

        observed_model_candidates = self._build_strategy_action_model_candidates(
            state=state, context=context, session_route=session_route,
        ) if self.observation_lane is None or self.model_policy.mode("strategy_action") == "active" else []
        strategy_action_quality = (self._strategy_action_quality()
            if self.observation_lane is None or self.model_policy.mode("strategy_action") == "active"
            else {'input': None, 'output': {'valid': None, 'reason': 'background_observation'}})
        model_candidates = observed_model_candidates if self.model_policy.mode("strategy_action") == "active" else []
        confidence_resolution = self.uncertainty_layer.evaluate(
            state=state,
            context=context,
            model_candidates=model_candidates,
            tactical_state=tactical_resolution.tactical_state,
        )
        resource_models = self._predict_group(self.resource_risk_runtime, state=state, context=context)
        rival_pressure_models = self._predict_group(self.rival_pressure_runtime, state=state, context=context)
        driving_quality_models = self._predict_group(self.driving_quality_runtime, state=state, context=context)
        tyre_degradation_trend_models = self._predict_group(self.tyre_degradation_trend_runtime, state=state, context=context)
        defence_cost_model = self.defence_cost_runtime.predict_score(state=state, context=context) if self.observation_lane is None or self.model_policy.mode("defence_cost") == "active" else {}
        observation_debug = self._offer_observation(state, context, session_route)
        admitted_resources = self.model_policy.active_scores(resource_models)
        admitted_rivals = self.model_policy.active_scores(rival_pressure_models)
        admitted_trends = self.model_policy.active_scores(tyre_degradation_trend_models)
        planning_debug = None
        if self.planning_lane is None:
            plans = self._plan(state, session_route, context, admitted_resources, admitted_rivals, admitted_trends)
        else:
            def build_plan(task):
                frozen = deepcopy(replace(state, assessment=None, decision_record=None))
                inputs = deepcopy((session_route, context, admitted_resources, admitted_rivals, admitted_trends))
                return lambda: self._plan(frozen, *inputs, task=task)
            planning_debug = self.planning_lane.offer(
                key=planning_event_key(state, session_route, self.contributor_policy),
                binding={"session_uid": state.session_uid, "epoch": state.session_epoch,
                         "snapshot_id": state.assessment.snapshot_id,
                         "source_timestamp_ms": state.source_timestamp_ms},
                build_work=build_plan)
            latest = planning_debug["latest"]
            plans = latest["results"] if latest else {
                name: {"enabled": False, "reason": "planner_pending_or_expired"}
                for name in ("pit_window_support", "long_horizon_strategy")}
            if latest:
                for plan in plans.values():
                    plan["contribution_binding"] = dict(latest["binding"])
                    plan["validity"] = {"event_key": latest["key"], "ttl_s": planning_debug["ttl_s"]}
        pit_window_support = plans["pit_window_support"]
        long_horizon_strategy = plans["long_horizon_strategy"]
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
                "resource_models": admitted_resources,
                "rival_pressure_models": admitted_rivals,
                "driving_quality_models": self.model_policy.active_scores(driving_quality_models),
                "tyre_degradation_trend_models": admitted_trends,
                "defence_cost_model": self.model_policy.active_scores({"defence_cost": defence_cost_model}).get("defence_cost", {}),
                "pit_window_support": self.contributor_policy.admit("pit_window_support", pit_window_support),
                "long_horizon_strategy": self.contributor_policy.admit("long_horizon_strategy", long_horizon_strategy),
            },
        )
        result = self.arbiter_v2.arbitrate(payload)
        return {
            "input": {
                "model_admission": {**self.model_policy.snapshot(), 'verified_evidence': deepcopy(self._verified_model_evidence)},
                "contributor_admission": self.contributor_policy.snapshot(),
                "background_observations": observation_debug,
                "background_planning": planning_debug,
                "observed_model_candidates": [item.__dict__ for item in observed_model_candidates],
                "strategy_action_quality": strategy_action_quality,
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
                "pit_window_support": pit_window_support,
                "long_horizon_strategy": long_horizon_strategy,
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

    def _strategy_action_quality(self):
        from copy import deepcopy
        return deepcopy({'input': self.strategy_action_runtime.last_input_quality,
                         'output': self.strategy_action_runtime.last_output_quality})

    def _build_strategy_action_model_candidates(
        self,
        *,
        state: SessionState,
        context: ContextProfile,
        session_route: SessionRoute,
    ) -> list[ModelCandidate]:
        """Build top-k model candidates from the local strategy-action baseline, if available."""

        candidates = self.strategy_action_runtime.predict_top_k(state=state, context=context, k=2)
        if not candidates:
            return []
        fuel_mainline_allowed = assess_fuel(state).verdict == 'critical'
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

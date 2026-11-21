"""Deterministic pit-window support and rejoin-risk assessment."""
from __future__ import annotations

from typing import Any

from .race_control import race_control_active
from .models import ContextProfile, DriverState, SessionState
from .session_router import SessionRoute
from .track_model import load_track_profile
from .long_horizon_types import PitWindowSupportState
from .long_horizon_shared import (
    ACTUAL_COMPOUNDS,
    _COMPOUND_TARGET_LIFE,
    _COMPOUND_BASE_RISK,
    _WEATHER_NAMES,
    _DRY_WEATHER,
    _WET_WEATHER,
    _DRY_COMPOUND_BY_STINT,
    _DRY_COMPOUND_ORDER,
    _TRACK_COMPOUND_BIAS,
    _used_completed_dry_compounds,
    _clamp,
    _clamp01,
)


def tyre_rule_scope(settings):
    race = settings.get("session_type")
    if settings.get("rule_set") == 0 or race in range(1, 15) or race == 18:
        return "not_applicable"
    if (settings.get("rule_set") != 1 or race not in {15, 16}
            or settings.get("formula") != 0 or settings.get("game_mode") not in {4, 27, 28, 29}):
        return "unknown"

    length = settings.get("session_length")
    if length in {2, 3}:
        return "not_applicable"
    if length not in {4, 5, 6, 7}:
        return "unknown"
    weekend = settings.get("weekend_structure") or []
    if race not in weekend:
        return "unknown"
    if race == 15 and 16 in weekend:
        return "not_applicable"

    return "standard"


class PitWindowSupport:
    """Deterministic long-horizon support layer for pit-window planning."""

    def evaluate(
        self,
        *,
        state: SessionState,
        session_route: SessionRoute,
        context: ContextProfile,
        resource_models: dict[str, dict[str, Any]],
        rival_pressure_models: dict[str, dict[str, Any]],
        tyre_degradation_trend_models: dict[str, dict[str, Any]],
    ) -> PitWindowSupportState:
        if not session_route.allow_race_resource_actions or state.total_laps <= 0:
            return PitWindowSupportState(
                enabled=False,
                lap_life_remaining_est=None,
                remaining_required_stops=0,
                compound_rule_state="not_applicable",
                pit_window_open_prob=0.0,
                compound_risk_score=0.0,
                rejoin_traffic_penalty=0.0,
                estimated_rejoin_position_loss=0.0,
                undercut_defence_score=0.0,
                pit_loss_now_score=0.0,
                pit_loss_under_control_state=1.0,
                rationale=["当前 session route 不启用进站窗口支持"],
            )
        remaining_race_laps = max(state.total_laps - max(state.lap_number - 1, 0), 0)
        wear_trend = self._extract_score(tyre_degradation_trend_models, "future_tyre_wear_delta")
        grip_drop = self._extract_score(tyre_degradation_trend_models, "future_grip_drop_score")
        fuel_risk = self._extract_score(resource_models, "fuel_risk")
        rear_pressure = self._extract_score(rival_pressure_models, "rear_pressure")
        compound = state.player.tyre.compound
        tyre_wear_pct = float(state.player.tyre.wear_pct)
        tyre_age_laps = float(state.player.tyre.age_laps)
        player_position = int(state.player.position or 0)
        grid_position = int(state.raw.get("grid_position", 0) or 0)
        pit_status = str(state.raw.get("pit_status") or "NONE")
        pit_lane_timer_active = bool(state.raw.get("pit_lane_timer_active", False))
        ahead_gap = self._gap_value(state.raw.get("official_gap_ahead_s"), state.raw.get("estimated_gap_ahead_s"))
        behind_gap = self._gap_value(state.raw.get("official_gap_behind_s"), state.raw.get("estimated_gap_behind_s"))
        front_rival = self._closest_rival(state, player_position - 1)
        rear_rival = self._closest_rival(state, player_position + 1)
        forecast_outlook = self._forecast_outlook(state.raw, state.weather)
        compound_rule_state, remaining_required_stops = self._compound_rule_state(
            state=state,
            current_compound=compound,
        )

        base_life = _COMPOUND_TARGET_LIFE.get(compound, 18.0)
        life_from_age = max(base_life - tyre_age_laps, 0.0)
        life_from_wear = max(base_life * (1.0 - tyre_wear_pct / 100.0), 0.0)
        trend_penalty = (wear_trend * 8.0) + (grip_drop * 0.6)
        lap_life_remaining_est = round(max(min(life_from_age, life_from_wear) - trend_penalty, 0.0), 2)

        compound_risk_score = _clamp(
            _COMPOUND_BASE_RISK.get(compound, 18.0)
            + max(0.0, tyre_wear_pct - 55.0) * 0.9
            + (wear_trend * 30.0)
            + (grip_drop * 4.0)
            + self._weather_mismatch_penalty(state.weather, compound),
            0.0,
            100.0,
        )
        if forecast_outlook["incoming_wet_risk"] > 0.0:
            compound_risk_score = _clamp(compound_risk_score + (forecast_outlook["incoming_wet_risk"] * 18.0), 0.0, 100.0)
        if forecast_outlook["drying_opportunity"] > 0.0:
            compound_risk_score = _clamp(compound_risk_score - (forecast_outlook["drying_opportunity"] * 12.0), 0.0, 100.0)
        if compound_rule_state == "unmet":
            compound_risk_score = _clamp(compound_risk_score + 12.0, 0.0, 100.0)
        elif compound_rule_state == "pending_validation":
            compound_risk_score = _clamp(compound_risk_score + 6.0, 0.0, 100.0)

        open_score = 0.0
        if lap_life_remaining_est <= 1.5:
            open_score += 0.45
        elif lap_life_remaining_est <= 3.0:
            open_score += 0.32
        elif lap_life_remaining_est <= 5.0:
            open_score += 0.18
        open_score += _clamp01((tyre_wear_pct - 55.0) / 25.0) * 0.25
        open_score += _clamp01((compound_risk_score - 50.0) / 40.0) * 0.15
        if remaining_required_stops > 0:
            race_progress = _clamp01(max(state.lap_number - 1, 0) / max(state.total_laps, 1))
            open_score += 0.10 + (race_progress * 0.14)
        if race_control_active(state.safety_car):
            open_score += 0.20
        if forecast_outlook["incoming_wet_risk"] > 0.0:
            open_score += 0.08 + (forecast_outlook["incoming_wet_risk"] * 0.10)
        if forecast_outlook["drying_opportunity"] > 0.0:
            open_score += 0.05 + (forecast_outlook["drying_opportunity"] * 0.08)
        if front_rival and ahead_gap is not None and ahead_gap <= 2.5:
            if str(front_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
                open_score += 0.06
            elif self._rival_gap_confidence_weight(front_rival, "front") >= 0.85:
                open_score += 0.04
        if rear_rival and behind_gap is not None and behind_gap <= 1.4:
            if rear_rival.drs_available:
                open_score += 0.08
            if str(rear_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
                open_score -= 0.06
            elif (rear_rival.engine_damage_pct or 0) >= 35:
                open_score -= 0.05
        if str(state.raw.get("pit_status") or "NONE") in {"PITTING", "IN_PIT_AREA"}:
            open_score = 1.0
        pit_window_open_prob = round(_clamp(open_score, 0.0, 1.0), 3)

        ahead_gap_confidence = str(
            state.raw.get("official_gap_confidence_ahead")
            or state.raw.get("estimated_gap_confidence_ahead")
            or "none"
        )
        behind_gap_confidence = str(
            state.raw.get("official_gap_confidence_behind")
            or state.raw.get("estimated_gap_confidence_behind")
            or "none"
        )
        confidence_weight = max(
            self._gap_confidence_weight(ahead_gap_confidence),
            self._gap_confidence_weight(behind_gap_confidence),
            0.6,
        )
        train_density = self._train_density_penalty(state.raw)
        rejoin_traffic_penalty = 8.0 + (rear_pressure * 0.10) + train_density
        if ahead_gap is not None:
            if ahead_gap < 1.2:
                rejoin_traffic_penalty += 20.0 * confidence_weight
            elif ahead_gap < 2.5:
                rejoin_traffic_penalty += 10.0 * confidence_weight
        if behind_gap is not None:
            if behind_gap < 1.0:
                rejoin_traffic_penalty += 24.0 * confidence_weight
            elif behind_gap < 2.0:
                rejoin_traffic_penalty += 12.0 * confidence_weight
        if front_rival is not None:
            front_confidence_weight = self._rival_gap_confidence_weight(front_rival, "front")
            if str(front_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
                rejoin_traffic_penalty -= 8.0 * front_confidence_weight
            elif ahead_gap is not None and ahead_gap < 1.5:
                rejoin_traffic_penalty += 6.0 * front_confidence_weight
        if rear_rival is not None:
            rear_confidence_weight = self._rival_gap_confidence_weight(rear_rival, "rear")
            if rear_rival.drs_available and behind_gap is not None and behind_gap < 1.5:
                rejoin_traffic_penalty += 10.0 * rear_confidence_weight
            if str(rear_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
                rejoin_traffic_penalty -= 10.0 * rear_confidence_weight
            elif (rear_rival.engine_damage_pct or 0) >= 35:
                rejoin_traffic_penalty -= 8.0 * rear_confidence_weight
        if player_position >= 15:
            rejoin_traffic_penalty += 8.0
        elif player_position >= 10:
            rejoin_traffic_penalty += 4.0
        if state.lap_number <= 2 and grid_position > 0 and player_position >= max(grid_position, 10):
            rejoin_traffic_penalty += 6.0
        if pit_status in {"PITTING", "IN_PIT_AREA"} or pit_lane_timer_active:
            rejoin_traffic_penalty -= 6.0
        rejoin_traffic_penalty = round(_clamp(rejoin_traffic_penalty, 0.0, 100.0), 2)

        estimated_rejoin_position_loss = round(_clamp((rejoin_traffic_penalty / 18.0), 0.0, 6.0), 1)

        undercut_defence_score = 0.0
        if ahead_gap is not None and ahead_gap <= 2.5:
            undercut_defence_score += (2.5 - ahead_gap) / 2.5 * 40.0
        if front_rival is not None:
            front_confidence_weight = self._rival_gap_confidence_weight(front_rival, "front")
            if str(front_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
                undercut_defence_score -= 14.0 * front_confidence_weight
            elif ahead_gap is not None and ahead_gap <= 2.5:
                undercut_defence_score += 10.0 * front_confidence_weight
            if (front_rival.engine_damage_pct or 0) >= 35:
                undercut_defence_score -= 8.0 * front_confidence_weight
        if lap_life_remaining_est <= 2.5:
            undercut_defence_score += 25.0
        if wear_trend >= 0.25 or grip_drop >= 2.5:
            undercut_defence_score += 15.0
        if race_control_active(state.safety_car):
            undercut_defence_score -= 10.0
        undercut_defence_score = round(_clamp(undercut_defence_score, 0.0, 100.0), 2)

        pit_loss_under_control_state = self._pit_loss_under_control_state(
            safety_car=state.safety_car,
            player_position=player_position,
            pit_status=pit_status,
            pit_lane_timer_active=pit_lane_timer_active,
        )
        pit_loss_now_score = round(
            _clamp(
                58.0
                - (rejoin_traffic_penalty * 0.45)
                + ((1.0 - pit_loss_under_control_state) * 42.0)
                + (5.0 if pit_status in {"PITTING", "IN_PIT_AREA"} else 0.0),
                0.0,
                100.0,
            ),
            2,
        )

        rationale: list[str] = []
        if lap_life_remaining_est <= 2.5:
            rationale.append(f"预计当前胎仅剩 {lap_life_remaining_est:.1f} 圈有效寿命")
        if compound_rule_state in {"unmet", "sets_unmet"}:
            rationale.append(f"比赛用胎要求尚未满足，至少还需 {remaining_required_stops} 次有效换胎")
        elif compound_rule_state == "unknown":
            rationale.append("比赛设置或本车用胎历史不足，必要换胎次数待确认")
        if race_control_active(state.safety_car):
            rationale.append(f"{state.safety_car} 阶段进站损失折减")
        if forecast_outlook["incoming_wet_risk"] > 0.0:
            rationale.append(f"{forecast_outlook['transition_minutes']} 分钟内有降雨窗口，当前 stint 价值正在下降")
        elif forecast_outlook["drying_opportunity"] > 0.0:
            rationale.append(f"{forecast_outlook['transition_minutes']} 分钟内赛道有转干趋势，可提前准备切回干胎窗口")
        if ahead_gap is not None and ahead_gap <= 2.5:
            rationale.append(f"前车时差 {ahead_gap:.2f}s，存在 undercut 防守压力")
        if front_rival and str(front_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
            rationale.append(f"前车 {front_rival.name} 已在进站流程，当前窗口更像跟进而不是单纯 undercut 防守")
        if behind_gap is not None and behind_gap <= 2.0:
            rationale.append(f"后车时差 {behind_gap:.2f}s，当前回场交通代价偏高")
        if rear_rival and rear_rival.drs_available and behind_gap is not None and behind_gap <= 1.5:
            rationale.append(f"后车 {rear_rival.name} 已具备 DRS，继续留在外面更容易把回场压力放大")
        if rear_rival and (rear_rival.engine_damage_pct or 0) >= 35:
            rationale.append(f"后车 {rear_rival.name} 发动机损伤偏高，后续追击压力存在自然回落空间")
        if rear_rival and str(rear_rival.pit_status or "NONE") in {"PITTING", "IN_PIT_AREA"}:
            rationale.append(f"后车 {rear_rival.name} 已在进站流程，当前回场交通压力可适度下调")
        if train_density >= 10.0:
            rationale.append("前后车列较密，回场后进入车阵的概率更高")
        if fuel_risk >= 80.0:
            rationale.append("燃油风险高，长周期规划需偏保守")

        return PitWindowSupportState(
            enabled=True,
            lap_life_remaining_est=lap_life_remaining_est,
            remaining_required_stops=remaining_required_stops,
            compound_rule_state=compound_rule_state,
            pit_window_open_prob=pit_window_open_prob,
            compound_risk_score=compound_risk_score,
            rejoin_traffic_penalty=rejoin_traffic_penalty,
            estimated_rejoin_position_loss=estimated_rejoin_position_loss,
            undercut_defence_score=undercut_defence_score,
            pit_loss_now_score=pit_loss_now_score,
            pit_loss_under_control_state=pit_loss_under_control_state,
            rationale=rationale,
        )

    def _extract_score(self, payload: dict[str, Any], key: str) -> float:
        if not isinstance(payload, dict):
            return 0.0
        item = payload.get(key)
        if not isinstance(item, dict):
            return 0.0
        try:
            return float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _gap_value(self, official: Any, estimated: Any) -> float | None:
        value = official if official is not None else estimated
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    def _weather_mismatch_penalty(self, weather: str, compound: str) -> float:
        if weather in {"LightRain", "HeavyRain", "Storm"} and compound not in {"Intermediate", "Wet"}:
            return 20.0
        if weather in {"Clear", "LightCloud", "Overcast"} and compound in {"Intermediate", "Wet"}:
            return 25.0
        return 0.0

    def _gap_confidence_weight(self, confidence: str) -> float:
        return {
            "high": 1.0,
            "medium": 0.85,
            "low": 0.7,
            "none": 0.55,
        }.get(confidence, 0.6)

    def _forecast_outlook(self, raw: dict[str, Any], current_weather: str) -> dict[str, float | int]:
        samples = raw.get("weather_forecast_samples") or []
        if not isinstance(samples, list):
            return {
                "incoming_wet_risk": 0.0,
                "drying_opportunity": 0.0,
                "transition_minutes": 0,
            }
        wet_candidates: list[tuple[int, float]] = []
        dry_candidates: list[tuple[int, float]] = []
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            try:
                offset_minutes = int(sample.get("time_offset_minutes", 0) or 0)
            except (TypeError, ValueError):
                continue
            if offset_minutes <= 0 or offset_minutes > 20:
                continue
            weather_name = _WEATHER_NAMES.get(int(sample.get("weather", -1)), "")
            rain_percentage = max(0.0, min(float(sample.get("rain_percentage", 0) or 0), 100.0))
            imminence = _clamp01((20.0 - float(offset_minutes)) / 20.0)
            if current_weather in _DRY_WEATHER and (weather_name in _WET_WEATHER or rain_percentage >= 35.0):
                wet_candidates.append((offset_minutes, _clamp01((rain_percentage / 100.0) * 0.65 + imminence * 0.35)))
            if current_weather in _WET_WEATHER and weather_name in _DRY_WEATHER and rain_percentage <= 20.0:
                dry_candidates.append((offset_minutes, _clamp01(((100.0 - rain_percentage) / 100.0) * 0.55 + imminence * 0.45)))
        if wet_candidates:
            transition_minutes, risk = max(wet_candidates, key=lambda item: item[1])
            return {
                "incoming_wet_risk": round(risk, 3),
                "drying_opportunity": 0.0,
                "transition_minutes": transition_minutes,
            }
        if dry_candidates:
            transition_minutes, opportunity = max(dry_candidates, key=lambda item: item[1])
            return {
                "incoming_wet_risk": 0.0,
                "drying_opportunity": round(opportunity, 3),
                "transition_minutes": transition_minutes,
            }
        return {
            "incoming_wet_risk": 0.0,
            "drying_opportunity": 0.0,
            "transition_minutes": 0,
        }

    def _closest_rival(self, state: SessionState, target_position: int) -> DriverState | None:
        if target_position <= 0:
            return None
        for rival in state.rivals:
            if rival.position == target_position:
                return rival
        return None

    def _rival_gap_confidence_weight(self, rival: DriverState, direction: str) -> float:
        if direction == "front":
            confidence = (
                rival.gap_confidence_behind
                or rival.gap_confidence
                or rival.estimated_gap_confidence
                or "none"
            )
        else:
            confidence = (
                rival.gap_confidence_ahead
                or rival.gap_confidence
                or rival.estimated_gap_confidence
                or "none"
            )
        return self._gap_confidence_weight(str(confidence))

    def _train_density_penalty(self, raw: dict[str, Any]) -> float:
        penalty = 0.0
        for key in (
            "front_rival_car_gap_ahead_s",
            "front_rival_car_gap_behind_s",
            "rear_rival_car_gap_ahead_s",
            "rear_rival_car_gap_behind_s",
        ):
            value = raw.get(key)
            try:
                gap = float(value)
            except (TypeError, ValueError):
                continue
            if gap <= 0.8:
                penalty += 5.0
            elif gap <= 1.5:
                penalty += 2.5
        return penalty

    def _pit_loss_under_control_state(
        self,
        *,
        safety_car: str,
        player_position: int,
        pit_status: str,
        pit_lane_timer_active: bool,
    ) -> float:
        if pit_status in {"PITTING", "IN_PIT_AREA"} or pit_lane_timer_active:
            return 0.35
        base = {
            "FULL": 0.52,
            "FORMATION": 0.60,
            "VSC": 0.76,
        }.get(safety_car, 1.0)
        if safety_car == "FULL" and player_position >= 12:
            base -= 0.05
        return _clamp(base, 0.30, 1.0)

    def _used_dry_compounds(self, *, state: SessionState, current_compound: str) -> set[str]:
        return _used_completed_dry_compounds(state=state, current_compound=current_compound)

    def _compound_rule_state(
        self,
        *,
        state: SessionState,
        current_compound: str,
    ) -> tuple[str, int]:
        settings = state.raw.get("tyre_rule_settings") or {}
        scope = tyre_rule_scope(settings)
        if scope != "standard":
            return scope, 0

        history = state.raw.get("session_history") or {}
        if history.get("car_index") != state.player.car_index:
            history = {}
        count = history.get("num_tyre_stints", 0)
        stints = (history.get("tyre_stints_history_data") or [])[:count]
        completed = [s for s in stints if 0 < s.get("end_lap", 0) <= state.lap_number]
        compounds = {s.get("tyre_actual_compound") for s in completed}
        used_wets = current_compound in {"Wet", "Intermediate"} or bool(compounds & {7, 8})
        different_dry = len(self._used_dry_compounds(state=state, current_compound=current_compound)) >= 2
        stops = state.raw.get("num_pit_stops")
        if type(stops) is not int or stops < 0:
            return "unknown", 0

        monaco = state.track.casefold() == "monaco"
        if monaco and settings.get("num_red_flag_periods") and stops < 2:
            # A tyre change during a stoppage can break the pit-count proxy.
            return "unknown", 0
        extra = max(0, 2 - stops) if monaco else 0
        if monaco and stops and len(completed) < stops:
            # Lane visits alone do not prove that new sets were used.
            return "unknown", 0
        if used_wets or different_dry:
            return ("sets_unmet", extra) if extra else ("satisfied", 0)
        if (current_compound not in _DRY_COMPOUND_ORDER or len(completed) < stops
                or any(code not in ACTUAL_COMPOUNDS for code in compounds)
                or (settings.get("num_red_flag_periods") and not completed)):
            return "unknown", 0
        return "unmet", max(extra, 1)

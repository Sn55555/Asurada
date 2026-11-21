"""Long-horizon candidate planning; preserves the original public imports."""
from __future__ import annotations

from typing import Any

from .race_control import race_control_active
from .models import ContextProfile, DriverState, SessionState
from .session_router import SessionRoute
from .track_model import load_track_profile
from .long_horizon_types import LongHorizonCandidate, LongHorizonStrategyState, PitWindowSupportState
from .pit_window_support import PitWindowSupport
from .long_horizon_shared import (
    _COMPOUND_TARGET_LIFE,
    _COMPOUND_BASE_RISK,
    _WEATHER_NAMES,
    _DRY_WEATHER,
    _WET_WEATHER,
    ACTUAL_COMPOUNDS,
    _DRY_COMPOUND_BY_STINT,
    _DRY_COMPOUND_ORDER,
    _TRACK_COMPOUND_BIAS,
    _used_completed_dry_compounds,
    _clamp,
    _clamp01,
)


class LongHorizonStrategyBaseline:
    """Enumerate short pit windows and surface a long-horizon planning sidecar."""

    def plan(
        self,
        *,
        state: SessionState,
        session_route: SessionRoute,
        support: PitWindowSupportState,
        resource_models: dict[str, dict[str, Any]],
        rival_pressure_models: dict[str, dict[str, Any]],
    ) -> LongHorizonStrategyState:
        if not session_route.allow_race_resource_actions or state.total_laps <= 0:
            return LongHorizonStrategyState(
                enabled=False,
                session_mode=session_route.session_mode,
                recommended_pit_lap=None,
                pit_window_start_lap=None,
                pit_window_end_lap=None,
                recommended_compound=None,
                recommended_set_index=None,
                recommended_set_available=False,
                lap_life_remaining_est=support.lap_life_remaining_est,
                remaining_required_stops=support.remaining_required_stops,
                compound_rule_state=support.compound_rule_state,
                pit_window_open_prob=support.pit_window_open_prob,
                stint_risk_score=0.0,
                compound_risk_score=support.compound_risk_score,
                strategy_confidence=0.0,
                aggression_bias=0.0,
                rationale=["当前 session route 不启用长周期进站规划"],
                candidates=[],
            )

        remaining_race_laps = max(state.total_laps - max(state.lap_number - 1, 0), 0)
        fuel_risk = self._extract_score(resource_models, "fuel_risk")
        rear_pressure = self._extract_score(rival_pressure_models, "rear_pressure")
        used_dry_compounds = self._used_dry_compounds(state=state, current_compound=state.player.tyre.compound)
        available_set_options = self._available_set_options(state)
        available_dry_compound_quality = self._available_dry_compound_quality(available_set_options)
        session_history_summary = dict(state.raw.get("session_history_summary") or {})
        candidates: list[LongHorizonCandidate] = []

        stay_out_risk = max(0.0, 2.0 - float(support.lap_life_remaining_est or 0.0)) * 18.0
        compound_rule_penalty = 0.0
        if support.compound_rule_state == "unmet":
            compound_rule_penalty += 16.0
        elif support.compound_rule_state == "pending_validation":
            compound_rule_penalty += 8.0
        stay_out_score = (
            58.0
            - (support.pit_window_open_prob * 52.0)
            - stay_out_risk
            - compound_rule_penalty
            - (fuel_risk * 0.08)
            + ((100.0 - support.rejoin_traffic_penalty) * 0.10)
        )
        candidates.append(
            LongHorizonCandidate(
                code="stay_out",
                target_lap=None,
                recommended_compound=None,
                recommended_set_index=None,
                recommended_set_available=False,
                total_score=round(stay_out_score, 2),
                components={
                    "window_pressure": round(-(support.pit_window_open_prob * 52.0), 2),
                    "stint_end_risk_penalty": round(-stay_out_risk, 2),
                    "compound_rule_penalty": round(-compound_rule_penalty, 2),
                    "fuel_penalty": round(-(fuel_risk * 0.08), 2),
                    "traffic_hold_bonus": round(((100.0 - support.rejoin_traffic_penalty) * 0.10), 2),
                },
                rationale=["保持当前 stint，继续观察 pit window 是否继续打开"],
            )
        )

        # Leave enough racing laps for each outstanding mandatory tyre change.
        last_stop_lap = state.total_laps - max(1, support.remaining_required_stops)
        if last_stop_lap < state.lap_number < state.total_laps:
            last_stop_lap = state.lap_number
        offsets = range(min(6, last_stop_lap - state.lap_number + 1))
        for offset in offsets:
            target_lap = state.lap_number + offset
            remaining_after_pit = max(remaining_race_laps - offset - 1, 0)
            recommended_compound = self._recommended_compound(
                current_lap=state.lap_number,
                target_lap=target_lap,
                remaining_after_pit=remaining_after_pit,
                track_name=state.track,
                weather=state.weather,
                current_compound=state.player.tyre.compound,
                compound_rule_state=support.compound_rule_state,
                remaining_required_stops=support.remaining_required_stops,
                used_dry_compounds=used_dry_compounds,
                available_dry_compound_quality=available_dry_compound_quality,
            )
            recommended_set_index = self._recommended_set_index(
                recommended_compound=recommended_compound,
                set_options=available_set_options,
                target_lap=target_lap,
                remaining_after_pit=remaining_after_pit,
            )
            recommended_set_available = bool(available_set_options.get(recommended_compound))
            tyre_end_risk_penalty = max(0.0, (offset + 1) - float(support.lap_life_remaining_est or 0.0)) * 12.0
            window_score = (support.pit_window_open_prob * 100.0) - (offset * 8.0)
            fuel_penalty = (fuel_risk * 0.10) if offset > 1 else (fuel_risk * 0.04)
            traffic_penalty = support.rejoin_traffic_penalty * (1.0 if offset == 0 else 0.82 if offset <= 2 else 0.70)
            control_bonus = ((1.0 - support.pit_loss_under_control_state) * 25.0) if offset == 0 else 0.0
            undercut_bonus = support.undercut_defence_score * (1.0 if offset <= 1 else 0.55 if offset <= 3 else 0.25)
            compound_rule_bonus = self._compound_choice_adjustment(
                recommended_compound=recommended_compound,
                current_compound=state.player.tyre.compound,
                compound_rule_state=support.compound_rule_state,
            )
            total_score = (
                window_score
                - tyre_end_risk_penalty
                - fuel_penalty
                - traffic_penalty
                + control_bonus
                + undercut_bonus
                + compound_rule_bonus
            )
            candidates.append(
                LongHorizonCandidate(
                    code="pit_now" if offset == 0 else f"pit_in_{offset}",
                    target_lap=target_lap,
                    recommended_compound=recommended_compound,
                    recommended_set_index=recommended_set_index,
                    recommended_set_available=recommended_set_available,
                    total_score=round(total_score, 2),
                    components={
                        "window_score": round(window_score, 2),
                        "tyre_end_risk_penalty": round(-tyre_end_risk_penalty, 2),
                        "fuel_penalty": round(-fuel_penalty, 2),
                        "rejoin_traffic_penalty": round(-traffic_penalty, 2),
                        "control_state_bonus": round(control_bonus, 2),
                        "undercut_bonus": round(undercut_bonus, 2),
                        "compound_rule_bonus": round(compound_rule_bonus, 2),
                    },
                    rationale=[
                        f"目标进站圈 {target_lap}",
                        f"推荐换胎 {recommended_compound}",
                        *([f"推荐轮胎组 #{recommended_set_index}"] if recommended_set_index is not None else []),
                        *(["未确认可用胎组，暂按理论胎种规划"] if recommended_set_index is None and recommended_set_available is False else []),
                    ],
                )
            )

        if support.remaining_required_stops and last_stop_lap == state.lap_number:
            candidates = [candidate for candidate in candidates if candidate.code == "pit_now"]
        candidates = sorted(candidates, key=lambda item: item.total_score, reverse=True)
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        recommended_pit_lap, pit_window_start_lap, pit_window_end_lap = self._resolve_window(
            current_lap=state.lap_number,
            best=best,
            candidates=candidates,
            lap_life_remaining_est=support.lap_life_remaining_est,
            pit_window_open_prob=support.pit_window_open_prob,
            remaining_required_stops=support.remaining_required_stops,
            current_compound=state.player.tyre.compound,
        )
        if (best.code == "stay_out" and support.compound_rule_state in {"not_applicable", "satisfied"}
                and (support.lap_life_remaining_est or 0) >= remaining_race_laps
                and support.pit_window_open_prob < 0.10):
            recommended_pit_lap = pit_window_start_lap = pit_window_end_lap = None
        recommended_compound = best.recommended_compound
        recommended_set_index = best.recommended_set_index
        recommended_set_available = best.recommended_set_available
        if recommended_compound is None and recommended_pit_lap is not None:
            recommended_compound = next(
                (
                    candidate.recommended_compound
                    for candidate in candidates
                    if candidate.target_lap == recommended_pit_lap and candidate.recommended_compound is not None
                ),
                None,
            )
        if recommended_set_index is None and recommended_pit_lap is not None:
            recommended_set_index = next(
                (
                    candidate.recommended_set_index
                    for candidate in candidates
                    if candidate.target_lap == recommended_pit_lap and candidate.recommended_set_index is not None
                ),
                None,
            )
        if recommended_compound is not None and recommended_pit_lap is not None:
            recommended_set_available = any(
                candidate.target_lap == recommended_pit_lap
                and candidate.recommended_compound == recommended_compound
                and candidate.recommended_set_available
                for candidate in candidates
            )
        score_gap = best.total_score - (second.total_score if second is not None else best.total_score)
        history_coverage = self._history_coverage_ratio(
            current_lap=state.lap_number,
            session_history_summary=session_history_summary,
        )
        recorded_stints = int(session_history_summary.get("num_tyre_stints", 0) or 0)
        confidence = _clamp01(
            0.32
            + min(max(score_gap, 0.0), 20.0) / 70.0
            + (0.15 if state.raw.get("official_gap_ahead_s") is not None else 0.05)
            + (0.10 if state.raw.get("official_gap_behind_s") is not None else 0.05)
        )
        if history_coverage >= 0.8:
            confidence = _clamp01(confidence + 0.05)
        elif state.lap_number >= 8 and history_coverage < 0.4:
            confidence = _clamp01(confidence - 0.08)
        if support.remaining_required_stops > 0 and recorded_stints > 0:
            confidence = _clamp01(confidence + 0.03)
        if best.code == "stay_out":
            confidence = _clamp01(
                confidence
                - 0.10
                - (support.pit_window_open_prob * 0.08)
                - (0.05 if support.remaining_required_stops > 0 else 0.0)
            )
        else:
            confidence = _clamp01(confidence + (support.pit_window_open_prob * 0.18))
        if recommended_compound is not None and not recommended_set_available:
            confidence = min(_clamp01(confidence - 0.18), 0.55)
        aggression_bias = _clamp(
            0.0
            + (0.18 if rear_pressure <= 25.0 else -0.22 if rear_pressure >= 60.0 else 0.0)
            + (0.10 if support.undercut_defence_score < 30.0 else -0.10)
            + (-0.18 if fuel_risk >= 80.0 else 0.0),
            -1.0,
            1.0,
        )
        rationale = list(best.rationale)
        if support.remaining_required_stops > state.total_laps - state.lap_number:
            rationale.append("剩余正常进站机会不足以完成全部用胎要求")
        if recommended_pit_lap is not None:
            rationale.append(f"当前推荐进站圈 {recommended_pit_lap}")
        if recommended_compound is not None:
            rationale.append(f"推荐换胎 {recommended_compound}")
        if recommended_set_index is not None:
            rationale.append(f"推荐轮胎组 #{recommended_set_index}")
        elif recommended_compound is not None and not recommended_set_available:
            rationale.append("未确认可用胎组，暂按理论胎种规划")
            rationale.append("当前推荐可执行性不足，下调策略置信度")
        if state.lap_number >= 8 and history_coverage < 0.4:
            rationale.append("session history 覆盖偏薄，长周期规划置信度已保守下调")
        elif recorded_stints > 0:
            rationale.append(f"session history 已记录 {recorded_stints} 段 tyre stint，可用于修正长周期判断")
        if support.rationale:
            rationale.extend(support.rationale[:2])

        return LongHorizonStrategyState(
            enabled=True,
            session_mode=session_route.session_mode,
            recommended_pit_lap=recommended_pit_lap,
            pit_window_start_lap=pit_window_start_lap,
            pit_window_end_lap=pit_window_end_lap,
            recommended_compound=recommended_compound,
            recommended_set_index=recommended_set_index,
            recommended_set_available=recommended_set_available,
            lap_life_remaining_est=support.lap_life_remaining_est,
            remaining_required_stops=support.remaining_required_stops,
            compound_rule_state=support.compound_rule_state,
            pit_window_open_prob=support.pit_window_open_prob,
            stint_risk_score=round(
                _clamp(
                    support.compound_risk_score * 0.45
                    + max(0.0, (remaining_race_laps - float(support.lap_life_remaining_est or 0.0))) * 6.0
                    + fuel_risk * 0.10,
                    0.0,
                    100.0,
                )
                + (support.remaining_required_stops * 18.0),
                2,
            ),
            compound_risk_score=round(support.compound_risk_score, 2),
            strategy_confidence=round(confidence, 3),
            aggression_bias=round(
                _clamp(
                    aggression_bias
                    + (-0.18 if support.remaining_required_stops > 0 else 0.0)
                    + (-0.08 if support.compound_rule_state == "unmet" else 0.0)
                    + (-0.08 if support.compound_rule_state == "pending_validation" else 0.0),
                    -1.0,
                    1.0,
                ),
                3,
            ),
            rationale=rationale,
            candidates=candidates,
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

    def _recommended_compound(
        self,
        *,
        current_lap: int,
        target_lap: int,
        remaining_after_pit: int,
        track_name: str,
        weather: str,
        current_compound: str,
        compound_rule_state: str,
        remaining_required_stops: int,
        used_dry_compounds: set[str],
        available_dry_compound_quality: dict[str, float],
    ) -> str:
        if weather in {"HeavyRain", "Storm"}:
            return "Wet"
        if weather == "LightRain":
            return "Intermediate"
        if remaining_after_pit <= 0:
            return "C3"

        stint_target_laps = max(1.0, remaining_after_pit / max(remaining_required_stops, 1))
        early_stop = target_lap <= current_lap + 2
        late_stop = remaining_after_pit <= 10
        stop_offset = max(target_lap - current_lap, 0)
        ranked: list[tuple[float, str]] = []
        candidate_compounds = [c for c in available_dry_compound_quality if c in _DRY_COMPOUND_ORDER] or ["C5", "C4", "C3", "C2", "C1"]

        if compound_rule_state == "unmet" and len(used_dry_compounds) == 1:
            # If no legal spare is confirmed, describe a theoretical alternative
            # without attaching an unavailable or already fitted set number.
            alternatives = [c for c in candidate_compounds if c not in used_dry_compounds]
            candidate_compounds = alternatives or [c for c in ("C5", "C4", "C3", "C2", "C1") if c not in used_dry_compounds]

        for compound in candidate_compounds:
            target_life = _COMPOUND_TARGET_LIFE.get(compound, 18.0)
            overshoot = target_life - stint_target_laps
            if overshoot >= 0:
                score = 18.0 - (overshoot * 0.45)
            else:
                score = 18.0 - (abs(overshoot) * 1.8)

            if remaining_after_pit >= 24 and compound in {"C5", "C4", "C3"}:
                score -= 10.0 if compound == "C3" else 16.0
            elif remaining_after_pit >= 18 and compound in {"C5", "C4"}:
                score -= 12.0 if compound == "C5" else 6.0

            if late_stop and compound in {"C1", "C2"}:
                score -= 8.0 if compound == "C1" else 4.0
            elif remaining_after_pit <= 12 and compound == "C1":
                score -= 5.0

            if early_stop and remaining_after_pit >= 16 and compound == "C5":
                score -= 10.0
            if early_stop and remaining_after_pit >= 20 and compound == "C4":
                score -= 4.0

            score += self._compound_window_profile_score(
                compound=compound,
                remaining_after_pit=remaining_after_pit,
                stop_offset=stop_offset,
            )
            score += self._track_compound_profile_score(track_name=track_name, compound=compound)
            score += available_dry_compound_quality.get(compound, 0.0)

            if compound_rule_state == "unmet":
                if compound not in used_dry_compounds:
                    score += 12.0
                else:
                    score -= 5.0
                if compound == current_compound:
                    score -= 14.0
            elif compound_rule_state == "pending_validation":
                if compound not in used_dry_compounds:
                    score += 6.0
                if compound == current_compound:
                    score -= 5.0
            elif compound == current_compound and remaining_after_pit <= _COMPOUND_TARGET_LIFE.get(compound, 18.0):
                score += 1.5

            if compound == "C3":
                score += 1.0

            ranked.append((score, compound))

        ranked.sort(key=lambda item: (item[0], -_DRY_COMPOUND_ORDER.index(item[1])), reverse=True)
        return ranked[0][1]

    def _compound_window_profile_score(
        self,
        *,
        compound: str,
        remaining_after_pit: int,
        stop_offset: int,
    ) -> float:
        if remaining_after_pit >= 34:
            table = {"C1": 8.0, "C2": 4.0, "C3": 0.0, "C4": -6.0, "C5": -12.0}
        elif remaining_after_pit >= 24:
            table = {"C1": 4.0, "C2": 6.0, "C3": 2.0, "C4": -4.0, "C5": -10.0}
        elif remaining_after_pit >= 16:
            table = {"C1": -2.0, "C2": 4.0, "C3": 6.0, "C4": 2.0, "C5": -6.0}
        elif remaining_after_pit >= 10:
            table = {"C1": -8.0, "C2": 0.0, "C3": 4.0, "C4": 6.0, "C5": 2.0}
        else:
            table = {"C1": -12.0, "C2": -4.0, "C3": 2.0, "C4": 6.0, "C5": 5.0}

        score = table.get(compound, 0.0)
        if stop_offset >= 3 and remaining_after_pit <= 20 and compound in {"C4", "C5"}:
            score += 1.5 if compound == "C4" else 1.0
        if stop_offset == 0 and remaining_after_pit >= 20 and compound == "C1":
            score -= 4.0
        if stop_offset == 0 and remaining_after_pit >= 18 and compound == "C2":
            score -= 1.5
        return score

    def _track_compound_profile_score(self, *, track_name: str, compound: str) -> float:
        normalized = track_name.strip().lower()
        explicit = _TRACK_COMPOUND_BIAS.get(normalized)
        if explicit is not None:
            return explicit.get(compound, 0.0)

        profile = load_track_profile(track_name)
        if profile is None or profile.lap_length_m <= 0.0:
            return 0.0

        high_load_len = 0.0
        braking_len = 0.0
        for segment in profile.semantic_segments:
            seg_len = max(segment.end_m - segment.start_m, 0.0)
            if segment.zone_type == "high_load_management":
                high_load_len += seg_len
            elif segment.zone_type == "braking_entry":
                braking_len += seg_len

        high_load_ratio = high_load_len / profile.lap_length_m
        braking_ratio = braking_len / profile.lap_length_m

        score = 0.0
        if high_load_ratio >= 0.18:
            score += {"C1": 3.0, "C2": 2.0, "C3": 0.5, "C4": -1.5, "C5": -3.5}.get(compound, 0.0)
        elif high_load_ratio <= 0.08 and braking_ratio >= 0.05:
            score += {"C1": -1.0, "C2": 0.5, "C3": 2.0, "C4": 1.0, "C5": -1.0}.get(compound, 0.0)
        return score

    def _alternate_dry_compound(self, *, current_compound: str, remaining_after_pit: int) -> str:
        if current_compound not in _DRY_COMPOUND_ORDER:
            return "C3"
        index = _DRY_COMPOUND_ORDER.index(current_compound)
        if remaining_after_pit > _COMPOUND_TARGET_LIFE.get(current_compound, 18.0) and index < len(_DRY_COMPOUND_ORDER) - 1:
            return _DRY_COMPOUND_ORDER[index + 1]
        if index > 0:
            return _DRY_COMPOUND_ORDER[index - 1]
        if index < len(_DRY_COMPOUND_ORDER) - 1:
            return _DRY_COMPOUND_ORDER[index + 1]
        return current_compound

    def _compound_choice_adjustment(
        self,
        *,
        recommended_compound: str,
        current_compound: str,
        compound_rule_state: str,
    ) -> float:
        if compound_rule_state == "unmet":
            return 10.0 if recommended_compound != current_compound else -14.0
        if compound_rule_state == "pending_validation":
            return 4.0 if recommended_compound != current_compound else -4.0
        return 0.0

    def _used_dry_compounds(self, *, state: SessionState, current_compound: str) -> set[str]:
        return _used_completed_dry_compounds(state=state, current_compound=current_compound)

    def _available_dry_compound_quality(self, set_options: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
        quality_by_compound: dict[str, float] = {}
        for compound_name, options in set_options.items():
            if not options:
                continue
            quality_by_compound[compound_name] = round(max(float(item.get("quality", 0.0)) for item in options), 2)
        return quality_by_compound

    def _available_set_options(self, state: SessionState) -> dict[str, list[dict[str, Any]]]:
        tyre_sets = state.raw.get("tyre_sets") or {}
        if tyre_sets.get("car_index") != state.player.car_index:
            return {}
        sets = tyre_sets.get("sets") or []
        options: dict[str, list[dict[str, Any]]] = {}
        for item in sets:
            if not isinstance(item, dict) or not item.get("available") or item.get("fitted") or item.get("set_index") == tyre_sets.get("fitted_idx"):
                continue
            compound_name = ACTUAL_COMPOUNDS.get(item.get("actual_tyre_compound"))
            if compound_name is None:
                continue
            usable_life = float(item.get("usable_life_laps", 0) or 0.0)
            life_span = float(item.get("life_span_laps", 0) or 0.0)
            wear_pct = float(item.get("wear_pct", 0) or 0.0)
            lap_delta_time_ms = float(item.get("lap_delta_time_ms", 0) or 0.0)
            recommended_session = int(item.get("recommended_session", 0) or 0)
            quality = _clamp(
                (usable_life * 0.35)
                + (life_span * 0.10)
                - (wear_pct * 0.05)
                - (max(lap_delta_time_ms, 0.0) / 4000.0)
                + (0.5 if recommended_session else 0.0),
                -4.0,
                4.0,
            )
            options.setdefault(compound_name, []).append(
                {
                    "set_index": int(item.get("set_index", -1)),
                    "quality": round(quality, 2),
                    "usable_life_laps": usable_life,
                    "life_span_laps": life_span,
                    "wear_pct": wear_pct,
                    "lap_delta_time_ms": lap_delta_time_ms,
                    "recommended_session": recommended_session,
                    "fitted": bool(item.get("fitted")),
                }
            )
        for items in options.values():
            items.sort(key=lambda item: (item["quality"], item["usable_life_laps"], -item["wear_pct"]), reverse=True)
        return options

    def _history_coverage_ratio(self, *, current_lap: int, session_history_summary: dict[str, Any]) -> float:
        try:
            recorded_laps = int(session_history_summary.get("num_laps", 0) or 0)
        except (TypeError, ValueError):
            recorded_laps = 0
        if current_lap <= 0:
            return 0.0
        return _clamp01(recorded_laps / max(current_lap, 1))

    def _recommended_set_index(
        self,
        *,
        recommended_compound: str,
        set_options: dict[str, list[dict[str, Any]]],
        target_lap: int,
        remaining_after_pit: int,
    ) -> int | None:
        options = list(set_options.get(recommended_compound) or [])
        if not options:
            return None
        best = None
        best_score = None
        early_stop = target_lap <= 2
        for item in options:
            score = float(item.get("quality", 0.0))
            usable_life = float(item.get("usable_life_laps", 0.0))
            wear_pct = float(item.get("wear_pct", 0.0))
            if usable_life < remaining_after_pit:
                score -= min(12.0, (remaining_after_pit - usable_life) * 0.8)
            else:
                score += min(4.0, (usable_life - remaining_after_pit) * 0.15)
            if early_stop and wear_pct > 12.0:
                score -= 2.0
            if not early_stop and wear_pct <= 8.0:
                score += 0.8
            if best_score is None or score > best_score:
                best = item
                best_score = score
        if not best:
            return None
        return int(best.get("set_index", -1)) if int(best.get("set_index", -1)) >= 0 else None

    def _resolve_window(
        self,
        *,
        current_lap: int,
        best: LongHorizonCandidate,
        candidates: list[LongHorizonCandidate],
        lap_life_remaining_est: float | None,
        pit_window_open_prob: float,
        remaining_required_stops: int,
        current_compound: str,
    ) -> tuple[int | None, int | None, int | None]:
        pit_candidates = [candidate for candidate in candidates if candidate.target_lap is not None]
        if not pit_candidates:
            return None, None, None

        if best.code == "stay_out":
            if pit_window_open_prob >= 0.35:
                start_offset = 1
            elif lap_life_remaining_est is not None and lap_life_remaining_est <= 3.0:
                start_offset = 1
            else:
                projected = int(round(min(max((lap_life_remaining_est or 4.0) / 3.0, 2.0), 5.0)))
                if remaining_required_stops > 0 and current_compound in {"C5", "C4"}:
                    projected = max(2, min(projected, 3))
                else:
                    projected = max(3, projected)
                if remaining_required_stops == 0 and pit_window_open_prob < 0.10 and (lap_life_remaining_est or 0.0) >= 8.0:
                    projected = max(projected, 4)
                start_offset = projected
            last_candidate = max(candidate.target_lap for candidate in pit_candidates)
            if last_candidate <= current_lap:
                return None, None, None
            start = min(current_lap + start_offset, last_candidate)
            end_offset = max(start_offset, min(5, start_offset + 2))
            end = min(current_lap + end_offset, last_candidate)
            return start, start, end

        best_pit = max(pit_candidates, key=lambda item: item.total_score)
        score_floor = best_pit.total_score - 8.0
        viable = sorted(
            [candidate for candidate in pit_candidates if candidate.total_score >= score_floor],
            key=lambda item: item.target_lap or current_lap,
        )
        if not viable:
            viable = [best_pit]

        start = viable[0].target_lap
        end = viable[-1].target_lap
        if start is None or end is None:
            return None, None, None

        recommended = best.target_lap if best.target_lap is not None else start
        if recommended is None and lap_life_remaining_est is not None:
            recommended = current_lap + max(1, min(5, int(round(lap_life_remaining_est))))
        return recommended, start, end

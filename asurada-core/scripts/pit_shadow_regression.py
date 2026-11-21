"""Check causal shadow choices and the proactive speech boundary."""
from asurada.config import StrategyThresholds
from asurada.output_envelopes import OutputEnvelopeBuilder
from asurada.pit_shadow import PitShadow, calibration, game_window, price_changes
from asurada.strategy import StrategyEngine
from phase1_long_horizon_forecast_history_regression import _build_state
from regression_support import emit_result


def run():
    state = _build_state()
    state.track, state.weather, state.safety_car = "Shanghai", "Clear", "NONE"
    state.lap_number, state.total_laps = 8, 10
    state.player.aero_damage_pct = 0
    state.player.tyre.compound = "C4"
    state.raw.update(tyre_rule_settings=dict(rule_set=1, session_type=16, session_length=4,
                     formula=0, game_mode=28, weekend_structure=[16]), sector=1, result_status=2,
                     pit_status_code=0, num_pit_stops=0, tyres_damage_pct=[0]*4,
                     shadow_session=dict(spectating=False, ideal=8, latest=9, forecast=[(0, 0)]))
    def tyre(idx, code, life, delta):
        return dict(set_index=idx, actual_tyre_compound=code, life_span_laps=life,
                    lap_delta_time_ms=delta, available=True, fitted=idx == 0)
    sets = [tyre(0, 17, 8, 0), tyre(1, 18, 2, -900)]
    state.raw["tyre_sets"] = dict(car_index=state.player.car_index, fitted_idx=0, sets=sets)
    state.source_timestamp_ms = 1000
    observer = PitShadow()
    row = observer.observe(state)
    checks = dict(only_past_races=not calibration(state)["prior_uids"],
                  faster_legal_set_now=row["nominal"] == "now" and row["verdict"] == "uncertain",
                  no_duplicate=observer.observe(state) is None)
    state.raw["shadow_session"].update(ideal=0, latest=0)
    updated = observer.assess(state)
    checks["game_window_blind"] = {k:v for k,v in row.items() if k != "game"} == {k:v for k,v in updated.items() if k != "game"}
    checks["zero_window_unavailable"] = updated["game"]["action"] is None
    duplicate = dict(sets[1], set_index=2)
    sets.append(duplicate)
    plans = observer.assess(state)["routes_by_stop_count"]
    doubles = [p for p in plans if len(p["stints"]) == 2]
    checks["two_stop_distinct_inventory"] = bool(doubles) and all(
        len({s["set_index"] for s in p["stints"]}) == 2 for p in doubles)
    sets.pop()
    checks["stop_price_changes_first_action"] = price_changes({
        ("stay", 1): dict(stops=1, pace_delta_s=-28),
        ("next", 2): dict(stops=2, pace_delta_s=-48)}) == [
            dict(above_pit_s=0., action="next"), dict(above_pit_s=20., action="stay")]
    del sets[1]["lap_delta_time_ms"]
    checks["partial_legacy_inventory"] = observer.assess(state)["missing"] == ["player_inventory"]
    sets[1]["lap_delta_time_ms"] = -900
    sets[1]["life_span_laps"] = 1
    checks["delay_for_tyre_life"] = observer.assess(state)["nominal"] == "next"
    state.safety_car = "VSC"
    checks["neutralisation_invalidates"] = "controlled_pit_loss_and_restart" in observer.observe(state)["missing"]
    state.safety_car = "NONE"
    state.lap_number = 9
    checks["last_legal_lap"] = observer.observe(state)["verdict"] == "now"
    state.raw["pit_status_code"] = 1
    checks["no_call_in_lane"] = observer.observe(state) is None
    state.raw["pit_status_code"] = 0
    state.session_epoch += 1
    checks["rewind_rechecks"] = observer.observe(state) is not None
    state.weather = "HeavyRain"
    checks["wet_crossover_unknown"] = "wet_crossover" in observer.assess(state)["missing"]
    state.session_uid = "9372756052161398147"
    state.source_timestamp_ms = 1774784796085
    checks["whole_race_held_out"] = not calibration(state)["prior_uids"]
    checks["overdue_separate"] = game_window(dict(ideal=3, latest=5), 6, 10)["action"] == "past_latest"
    engine = StrategyEngine(StrategyThresholds())
    decision = engine.evaluate(state)
    checks["normal_runtime_shadow"] = decision.debug["pit_timing_shadow"]["verdict"] == "uncertain" and decision.debug["pit_broadcast_muted"]
    from asurada.models import StrategyMessage
    decision.messages = [StrategyMessage(code="BOX_WINDOW", title="进站", detail="test", priority=90)]
    checks["legacy_box_voice_muted"] = OutputEnvelopeBuilder()._build_strategy_envelope(
        decision=decision, interaction_input_event={}, task_handle={}, final_voice_action=dict(code="BOX_WINDOW"), state=state) is None
    return dict(passed=all(checks.values()), checks=checks)


if __name__ == "__main__":
    emit_result(run())

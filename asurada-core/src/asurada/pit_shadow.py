"""Silent pit timing assessment, sampled before the final sector."""
from statistics import median

from .long_horizon_shared import ACTUAL_COMPOUNDS, _DRY_COMPOUND_ORDER, _DRY_WEATHER
from .pit_window_support import PitWindowSupport


# Phase 2 labels. Release a race only after its last captured packet.
# Each row has one race's median pit loss and median net lap-time slopes by compound.
_PRIORS = (
    ("9372756052161398147", 1774784796084, "Shanghai", 25.2595, {"C3": .10150}),
    ("3466132923986383695", 1774790554427, "Suzuka", 22.3140, {"C3": .13040, "C2": .027875}),
    ("3882909580368997235", 1775506082458, "Austria", 17.70725, {"C3": .14575, "C4": .25405}),
)


def game_window(session, lap, total):
    ideal, latest = session.get("ideal"), session.get("latest")
    valid = all(type(n) is int and 1 <= n <= total for n in (ideal, latest)) and ideal <= latest
    category = None
    if valid:
        if lap > latest:
            category = "past_latest"
        elif lap >= ideal:
            category = "now"
        elif lap + 1 == ideal:
            category = "next"
        else:
            category = "stay"
    return dict(ideal=ideal, latest=latest, action=category)


def calibration(state):
    prior = [row for row in _PRIORS if row[0] != str(state.session_uid) and
             row[1] < state.source_timestamp_ms]
    local = [row for row in prior if row[2] == state.track]
    costs = local or prior
    slopes = {}
    for compound in _DRY_COMPOUND_ORDER:
        values = [row[4][compound] for row in (local or prior) if compound in row[4]]
        if values:
            slopes[compound] = median(values)
    return dict(pit_s=median(row[3] for row in costs) if costs else None,
                observed_pit_range_s=[min(r[3] for r in costs), max(r[3] for r in costs)] if costs else None,
                same_track=bool(local), slopes=slopes, prior_uids=[row[0] for row in prior])


def alternatives(state, inventory, rule, required, prior):
    """Keep the fastest route per first action and stop count, over a common finish."""
    lap = state.lap_number
    laps = state.total_laps - lap
    current = state.player.tyre.compound
    fitted = inventory["sets"][inventory["fitted_idx"]]
    old_life = fitted["life_span_laps"]
    curves = prior["slopes"]
    old_slope = curves.get(current, 0)
    frontier = {}
    if required == 0 and old_life >= laps + 1:
        frontier["stay", 0] = dict(stints=[], pace_delta_s=0., stops=0, stop_lap=None)

    tyres = [t for t in inventory["sets"] if t["available"] and not t["fitted"]
             and ACTUAL_COMPOUNDS.get(t["actual_tyre_compound"]) in _DRY_COMPOUND_ORDER]

    def stint(t, delay, n):
        target = ACTUAL_COMPOUNDS[t["actual_tyre_compound"]]
        if current not in curves or target not in curves:
            return n * t["lap_delta_time_ms"] / 1000
        slope = curves[target]
        return (n * (t["lap_delta_time_ms"] / 1000 - delay * old_slope)
                + n * (n - 1) / 2 * (slope - old_slope))

    def record(action, path, pace):
        key = action, len(path)
        if key not in frontier or pace < frontier[key]["pace_delta_s"]:
            stints = [dict(stop_lap=lap + offset, set_index=t["set_index"],
                           compound=ACTUAL_COMPOUNDS[t["actual_tyre_compound"]]) for offset, t in path]
            frontier[key] = dict(stints=stints, pace_delta_s=pace, stops=len(path), stop_lap=stints[0]["stop_lap"])

    for delay in range(min(laps, old_life)):
        action = ("now", "next")[delay] if delay < 2 else "stay"
        n = laps - delay
        for first in tyres:
            first_differs = ACTUAL_COMPOUNDS[first["actual_tyre_compound"]] != current
            if required <= 1 and (rule != "unmet" or first_differs) and first["life_span_laps"] >= n:
                record(action, [(delay, first)], stint(first, delay, n))
            for second in tyres:
                if (first["set_index"] == second["set_index"] or (rule == "unmet" and not first_differs
                        and ACTUAL_COMPOUNDS[second["actual_tyre_compound"]] == current)):
                    continue
                for length in range(max(1, n - second["life_span_laps"]), min(n - 1, first["life_span_laps"]) + 1):
                    pace = stint(first, delay, length) + stint(second, delay + length, n - length)
                    record(action, [(delay, first), (delay + length, second)], pace)
    return frontier


def ranked(frontier, pit):
    plans = {}
    for (action, count), plan in frontier.items():
        time = plan["pace_delta_s"] + pit * count
        if action not in plans or time < plans[action][0]:
            plans[action] = time, plan
    return sorted(plans.items(), key=lambda item: item[1][0])


def price_changes(frontier):
    # A lower envelope of affine costs can change winner only at an intersection.
    lines = list(frontier.values())
    cuts = {0.}
    for a in lines:
        for b in lines:
            if a["stops"] != b["stops"]:
                price = (b["pace_delta_s"] - a["pace_delta_s"]) / (a["stops"] - b["stops"])
                if price > 0:
                    cuts.add(price)
    cuts = sorted(cuts)
    probes = [(a + b) / 2 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + 1]
    scenarios = []
    for lower, price in zip(cuts, probes):
        winner = ranked(frontier, price)[0][0]
        if not scenarios or winner != scenarios[-1]["action"]:
            scenarios.append(dict(above_pit_s=round(lower, 3), action=winner))
    return scenarios


def rejoin(state, loss):
    if loss is None:
        return None
    gap = 0.
    position = state.player.position
    for car in sorted((c for c in state.rivals if c.position > position), key=lambda c: c.position):
        if (car.position != position + 1 or car.lap != state.lap_number or car.pit_status != "NONE"
                or car.gap_source_ahead != "official_lapdata_adjacent" or not car.gap_ahead_s):
            return dict(at_least_position=position, complete=False)
        gap += car.gap_ahead_s
        if gap >= loss:
            return dict(position=position, following_gap_s=round(gap - loss, 3), complete=True)
        position = car.position
    return dict(at_least_position=position, complete=False)


class PitShadow:
    def __init__(self):
        self.last = None

    def checkpoint(self, state):
        raw = state.raw
        if (raw.get("tyre_rule_settings", {}).get("session_type") not in (15, 16, 17)
                or raw.get("sector") != 1 or raw.get("result_status") != 2
                or raw.get("pit_status_code") != 0 or raw.get("session_paused")
                or not 1 <= state.lap_number <= state.total_laps
                or raw.get("shadow_session", {}).get("spectating") not in (False, 0)):
            return False
        # Recheck within sector two when the strategic context changes. Numeric tyre
        # wear and target-lap updates are deliberately excluded from the trigger.
        key = (state.session_uid, state.session_epoch, state.lap_number, state.safety_car,
               state.weather, bool(state.player.aero_damage_pct), raw.get("marshal_zone_flag") == 3,
               tuple(tuple(sample) for sample in raw["shadow_session"].get("forecast", ())),
               raw.get("num_unserved_drive_through_pens"), raw.get("num_unserved_stop_go_pens"),
               (raw.get("tyre_sets") or {}).get("fitted_idx"))
        if key == self.last:
            return False
        self.last = key
        return True

    def observe(self, state):
        return self.assess(state) if self.checkpoint(state) else None

    @staticmethod
    def assess(state):
        raw = state.raw
        session = raw["shadow_session"]
        compound = state.player.tyre.compound
        rule, required = PitWindowSupport()._compound_rule_state(state=state, current_compound=compound)
        prior = calibration(state)
        result = dict(game=game_window(session, state.lap_number, state.total_laps),
                      rule=rule, required=required, prior=prior, options={}, nominal=None,
                      next_review="sector_two_context_change_or_next_lap",
                      verdict="uncertain", margin_s=None, missing=[])
        missing = result["missing"]
        if rule == "unknown" or required > 2:
            missing.append("rule_or_multiple_required_stops")
        if state.safety_car != "NONE" or raw.get("marshal_zone_flag") == 3:
            missing.append("controlled_pit_loss_and_restart")
        if state.weather not in _DRY_WEATHER or compound not in _DRY_COMPOUND_ORDER:
            missing.append("wet_crossover")
        forecast = session.get("forecast") or []
        last_lap_ms = raw.get("last_lap_time_ms") or 0
        horizon_min = (state.total_laps - state.lap_number + 1) * last_lap_ms / 60000 if last_lap_ms else None
        if not forecast or any(weather >= 3 and (horizon_min is None or minutes <= horizon_min)
                               for minutes, weather in forecast):
            missing.append("weather_transition_timing")
        if state.player.aero_damage_pct or max(raw.get("tyres_damage_pct") or [0]) >= 100:
            missing.append("repair_time_and_damaged_pace")
        if raw.get("num_unserved_drive_through_pens") or raw.get("num_unserved_stop_go_pens"):
            missing.append("penalty_service")
        if missing:
            return result
        if state.total_laps == state.lap_number:
            if required:
                missing.append("no_remaining_racing_stint")
            else:
                result.update(nominal="stay", verdict="stay")
            return result
        inventory = raw.get("tyre_sets") or {}
        sets, idx = inventory.get("sets") or [], inventory.get("fitted_idx")
        if (inventory.get("car_index") != state.player.car_index or type(idx) is not int
                or not 0 <= idx < len(sets)
                or any(not isinstance(t, dict) or type(t.get("life_span_laps")) is not int
                       or type(t.get("lap_delta_time_ms")) is not int or t.get("set_index") != i
                       or "actual_tyre_compound" not in t or "available" not in t or "fitted" not in t
                       for i, t in enumerate(sets)) or not sets[idx].get("fitted")
                or ACTUAL_COMPOUNDS.get(sets[idx]["actual_tyre_compound"]) != compound):
            missing.append("player_inventory")
            return result
        frontier = alternatives(state, inventory, rule, required, prior)
        if not frontier:
            missing.append("viable_stint_or_multistop_plan")
            return result
        pit = prior["pit_s"]
        scenarios = price_changes(frontier)
        result["pit_price_sensitivity"] = scenarios
        result["routes_by_stop_count"] = [dict(plan, action=action, pace_delta_s=round(plan["pace_delta_s"], 3))
                                          for (action, _), plan in frontier.items()]
        if pit is not None:
            result["extra_stop_break_even_s_per_lap"] = round(pit / (state.total_laps - state.lap_number), 3)
        result["rejoin_if_now"] = rejoin(state, pit)
        if prior["observed_pit_range_s"]:
            result["rejoin_at_observed_cost_extremes"] = [rejoin(state, s) for s in prior["observed_pit_range_s"]]
        # Unknown price: display conditional routes at the positive-price limit near zero.
        # Only report a first-action preference if it holds for every positive price.
        order = ranked(frontier, pit if pit is not None else 1e-9)
        for action, (time, plan) in order:
            result["options"][action] = dict(plan, pace_delta_s=round(plan["pace_delta_s"], 3),
                                             nominal_delta_s=round(time, 3) if pit is not None or not plan["stops"] else None)
        if prior["observed_pit_range_s"]:
            for action, option in result["options"].items():
                candidates = [plan for (a, _), plan in frontier.items() if a == action]
                option["observed_cost_only_range_s"] = [
                    round(min(p["pace_delta_s"] + p["stops"] * price for p in candidates), 3)
                    for price in prior["observed_pit_range_s"]]
        if pit is not None or len(scenarios) == 1:
            result["nominal"] = order[0][0] if pit is not None else scenarios[0]["action"]
        if len(order) > 1 and (pit is not None or (len({p["stops"] for p in frontier.values()}) == 1)):
            result["margin_s"] = round(order[1][1][0] - order[0][1][0], 3)
        if result["margin_s"] == 0:
            result["nominal"] = None
        if required == 1 and state.lap_number + 1 == state.total_laps:
            result["verdict"] = "now"
            return result
        if not prior["same_track"] and len({p["stops"] for p in frontier.values()}) > 1:
            missing.append("same_track_green_pit_loss")
        compared = {compound}
        for plan in result["options"].values():
            compared.update(stint["compound"] for stint in plan["stints"])
        result["compounds_without_prior_slope"] = sorted(compared.difference(prior["slopes"]))
        missing.extend(["matched_stint_pace_and_life", "warmup_and_rejoin_traffic"])
        return result

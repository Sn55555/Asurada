"""Pre-race tyre strategy using only the race settings, forecast and player's grid inventory."""
from itertools import combinations

from .long_horizon_shared import ACTUAL_COMPOUNDS
from .pit_window_support import tyre_rule_scope


def split_lengths(laps, lives):
    """All positive integer stint lengths summing to the race distance."""
    if len(lives) == 1:
        if 1 <= laps <= lives[0]:
            yield (laps,)
        return
    for n in range(max(1, laps - sum(lives[1:])), min(lives[0], laps - len(lives) + 1) + 1):
        for tail in split_lengths(laps - n, lives[1:]):
            yield (n, *tail)


def grid_inputs(session, inventory, player):
    return dict(laps=session.get("total_laps"), track_id=session.get("track_id"),
                player=player, spectating=session.get("is_spectating"), weather=session.get("weather"),
                forecast=[{k: v.get(k) for k in ("time_offset_minutes", "weather", "rain_percentage")}
                          for v in session.get("weather_forecast_samples", ())
                          if v.get("session_type") == session.get("session_type")],
                rules={k: session.get(k) for k in ("rule_set", "session_type", "formula", "game_mode",
                                                   "session_length", "weekend_structure")},
                owner=inventory.get("car_index"), fitted=inventory.get("fitted_idx"),
                sets=[{k: t.get(k) for k in ("set_index", "actual_tyre_compound", "wear_pct", "available",
                                             "fitted", "life_span_laps", "lap_delta_time_ms")}
                      for t in inventory.get("sets", ())])


def wet(code):
    return code in (7, 8)


def valid_inventory(grid):
    sets, fitted = grid["sets"], grid["fitted"]
    return (type(grid["player"]) is int and 0 <= grid["player"] < 22 and grid["owner"] == grid["player"]
            and type(fitted) is int and 0 <= fitted < len(sets)
            and all(t["set_index"] == i and type(t["life_span_laps"]) is int
                    and type(t["lap_delta_time_ms"]) is int and type(t["available"]) is bool
                    and t["fitted"] is (i == fitted) for i, t in enumerate(sets))
            and sets[fitted]["actual_tyre_compound"] in ACTUAL_COMPOUNDS)


def transition_capacity(grid, crossover_lap, *, fixed_start=False):
    """Feasibility if the suitable tyre family switches at the start of this lap.

    Switching must coincide with a stop. A measured pace differential for the
    second weather regime would be needed to assign times to these routes.
    """
    laps = grid["laps"]
    if not 2 <= crossover_lap <= laps:
        raise ValueError("crossover lap must be between 2 and race distance")
    eligible = [t for t in grid["sets"] if (t["available"] or t["fitted"])
                and t["actual_tyre_compound"] in ACTUAL_COMPOUNDS and t["life_span_laps"] > 0]
    groups = [[t for t in eligible if wet(t["actual_tyre_compound"]) == w]
              for w in (grid["weather"] >= 3, grid["weather"] < 3)]

    def covers(sets, n, stint_count, require_fitted=False):
        return n >= stint_count and any(
            sum(t["life_span_laps"] for t in group) >= n and
            (not require_fitted or any(t["fitted"] for t in group))
            for group in combinations(sets, stint_count))

    result = {}
    for stops in (1, 2):
        ok = any(covers(groups[0], crossover_lap - 1, a, fixed_start)
                 and covers(groups[1], laps - crossover_lap + 1, stops + 1 - a)
                 for a in range(1, stops + 1))
        if grid["track_id"] == 5 and tyre_rule_scope(grid["rules"]) == "standard" and stops < 2:
            ok = False
        result[str(stops)] = ok
    return result


def optimise(grid, degradation_ms=0, pit_s=None):
    """A symbolic pit price. Incremental tyre-age slope is an explicit scenario, in ms/lap."""
    if type(degradation_ms) is not int or degradation_ms < 0:
        raise ValueError("degradation_ms must be a nonnegative integer")
    if pit_s is not None and not 0 <= pit_s < float("inf"):
        raise ValueError("pit_s must be finite and nonnegative")
    laps = grid["laps"]
    scope = tyre_rule_scope(grid["rules"])
    missing = []
    if grid["spectating"] is not False or grid["rules"].get("session_type") not in (15, 16, 17):
        missing.append("player_race_session")
    if (scope == "unknown" or type(grid["track_id"]) is not int or grid["track_id"] < 0
            or type(laps) is not int or not 1 <= laps <= 255):
        missing.append("race_rules_or_distance")
    if not valid_inventory(grid):
        missing.append("owned_fitted_inventory")
    if grid["weather"] not in range(6):
        missing.append("current_weather")
    if missing:
        return dict(status="insufficient", missing=missing)
    is_wet = grid["weather"] >= 3
    change = any((f["weather"] >= 3) != is_wet for f in grid["forecast"] if f["weather"] in range(6))
    tyre_sets = [t for t in grid["sets"] if (t["available"] or t["fitted"]) and t["life_span_laps"] > 0
                 and t["actual_tyre_compound"] in ACTUAL_COMPOUNDS and wet(t["actual_tyre_compound"]) == is_wet]
    modes = {"free_start": {}, "fitted_start": {}}
    for count in (0, 1, 2):
        if scope == "standard" and (count < (2 if grid["track_id"] == 5 else 0) or (not is_wet and count < 1)):
            continue
        for tyres in combinations(tyre_sets, count + 1):
            if scope == "standard" and not is_wet and len({t["actual_tyre_compound"] for t in tyres}) < 2:
                continue
            for lengths in split_lengths(laps, tuple(t["life_span_laps"] for t in tyres)):
                pace = sum(n*t["lap_delta_time_ms"] + degradation_ms*n*(n-1)//2 for n,t in zip(lengths, tyres))
                for mode, routes in modes.items():
                    starts = [i for i,t in enumerate(tyres) if mode == "free_start" or t["fitted"]]
                    if not starts:
                        continue
                    entry = routes.get(str(count))
                    if entry and entry["pace_ms"] < pace:
                        continue
                    if not entry or entry["pace_ms"] > pace:
                        # With a stationary forecast every permutation of these stints costs the same.
                        i = min(starts, key=lambda j: (not tyres[j]["fitted"], tyres[j]["lap_delta_time_ms"], tyres[j]["set_index"]))
                        order = [i] + [j for j in range(len(tyres)) if j != i]
                        end = 0
                        stints = []
                        for j in order:
                            end += lengths[j]
                            t = tyres[j]
                            stints.append(dict(set=t["set_index"], compound=ACTUAL_COMPOUNDS[t["actual_tyre_compound"]],
                                               laps=lengths[j], end=end))
                        entry = routes[str(count)] = dict(pace_ms=pace, stints=stints, starts=set(), first_stops=set())
                    entry["starts"].update(tyres[i]["set_index"] for i in starts)
                    if count:
                        entry["first_stops"].update(lengths[i] for i in starts)
    output = {}
    for mode, routes in modes.items():
        for r in routes.values():
            r["starts"] = sorted(r["starts"])
            r["first_stops"] = sorted(r["first_stops"])
        crossing = None
        if "1" in routes and "2" in routes:
            crossing = (routes["1"]["pace_ms"] - routes["2"]["pace_ms"]) / 1000
        best = []
        if routes and pit_s is not None:
            cost = {k:r["pace_ms"] + int(k)*pit_s*1000 for k,r in routes.items()}
            best = [int(k) for k,v in cost.items() if abs(v-min(cost.values())) < 1e-6]
        dominant = None
        if routes:
            least = min(routes, key=int)
            if routes[least]["pace_ms"] == min(route["pace_ms"] for route in routes.values()):
                dominant = int(least)
        output[mode] = dict(routes=routes, one_two_break_even_s=crossing,
                            best_for_every_positive_price=dominant, best_at_price=best)
    return dict(status="conditional", weather_case="unchanged_wet" if is_wet else "unchanged_dry",
                forecast_changes_family=change, forecast_available=bool(grid["forecast"]), degradation_ms=degradation_ms,
                pit_s=pit_s, **output)

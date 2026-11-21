"""Independent exhaustive grid oracle, eligibility and frozen start-boundary checks."""
from copy import deepcopy
from itertools import combinations, permutations
from types import SimpleNamespace

from asurada.grid_strategy import optimise, transition_capacity
from asurada.grid_feed import GridPlanFeed
from regression_support import emit_result


def fixture():
    sets = []
    for i,(code,life,delta) in enumerate([(17,3,0),(18,4,800),(17,3,-200),(7,4,4000),(7,4,4100)]):
        sets.append(dict(set_index=i, fitted=i==0, available=True, actual_tyre_compound=code,
                         life_span_laps=life, lap_delta_time_ms=delta, wear_pct=0))
    return dict(laps=7, track_id=2, player=0, owner=0, spectating=False, weather=0, forecast=[],
                rules=dict(formula=0, session_type=16, rule_set=1, game_mode=28, session_length=5,
                           weekend_structure=[16]), fitted=0, sets=sets)


def oracle(g, count, fixed, slope):
    best, starts, cuts = None, set(), set()
    dry = [t for t in g["sets"] if t["actual_tyre_compound"] > 8 and (t["available"] or t["fitted"])]
    for order in permutations(dry, count + 1):
        if fixed and not order[0]["fitted"] or len({t["actual_tyre_compound"] for t in order}) < 2:
            continue
        for pit_laps in combinations(range(1, g["laps"]), count):
            ends = (0, *pit_laps, g["laps"])
            ns = [b-a for a,b in zip(ends, ends[1:])]
            if any(n > t["life_span_laps"] for n,t in zip(ns, order)):
                continue
            cost = sum(t["lap_delta_time_ms"] + age*slope for n,t in zip(ns,order) for age in range(n))
            if best is None or cost < best:
                best, starts, cuts = cost, set(), set()
            if cost == best:
                starts.add(order[0]["set_index"])
                cuts.add(pit_laps[0])
    return best, sorted(starts), sorted(cuts)


def run():
    g = fixture()
    checks = {}
    for slope in (0, 117):
        plan = optimise(g, slope)
        for fixed, mode in ((True,"fitted_start"),(False,"free_start")):
            for count in (1,2):
                r = plan[mode]["routes"][str(count)]
                checks[f"oracle_{mode}_{count}_{slope}"] = (
                    r["pace_ms"], r["starts"], r["first_stops"]) == oracle(g,count,fixed,slope)
                assert sum(s["laps"] for s in r["stints"]) == 7
                assert len({s["set"] for s in r["stints"]}) == count+1
    p = optimise(g)["fitted_start"]["one_two_break_even_s"]
    checks["price_flips_both_ways_and_ties"] = all(
        optimise(g,pit_s=price)["fitted_start"]["best_at_price"] == expected
        for price,expected in ((p-.001,[2]),(p,[1,2]),(p+.001,[1])))
    withheld = deepcopy(g)
    withheld["sets"][2]["available"] = False
    checks["reserved_spare_excludes_two_stop"] = "2" not in optimise(withheld)["free_start"]["routes"]
    checks["weather_timing_changes_feasibility"] = (
        transition_capacity(g,4)["1"] and transition_capacity(g,7) == {"1":False,"2":True})
    checks["monaco_requires_two_changes"] = set(optimise(dict(g, track_id=5))["free_start"]["routes"]) == {"2"}
    checks["missing_inventory_owner"] = optimise(dict(g, owner=1))["status"] == "insufficient"
    checks["unverified_rules"] = optimise(dict(g,rules=dict(g["rules"],formula=9)))["status"] == "insufficient"
    short = dict(g, laps=3, rules=dict(g["rules"],session_length=3))
    checks["short_race_zero_stop"] = optimise(short)["free_start"]["best_for_every_positive_price"] == 0
    checks["incoming_rain_conditional"] = optimise(dict(g,forecast=[dict(weather=3)]))["forecast_changes_family"]
    feed = GridPlanFeed()
    session = dict(g["rules"],total_laps=7,track_id=2,weather=0,is_spectating=False)
    asm = SimpleNamespace(accepted_epoch=0,packet_epochs={"x":0},latest_session_by_uid={"x":session},
            latest_session_header_by_uid={"x":dict(overall_frame_identifier=10)},player_packet_frames={("x","TyreSets"):11},
            _player_context=lambda *args:dict(car_index=0,sets=g["sets"],fitted_idx=0))
    def event(name,frame):
        return SimpleNamespace(kind="Event",session_uid="x",payload=dict(body=dict(event_code=name),
            header=dict(player_car_index=0, overall_frame_identifier=frame,session_time_s=0)))
    feed.observe(event("STLG",11),asm)
    checks["same_frame_set_excluded"] = feed.entries["x"]["plan"]["status"] == "insufficient"
    feed.observe(event("LGOT",12),asm)
    frozen = deepcopy(feed.entries["x"])
    session["weather"] = 4
    feed.observe(event("STLG",15),asm)
    checks["post_start_cannot_replace_grid"] = frozen == feed.entries["x"]
    feed.selected_stops = 1
    state = SimpleNamespace(session_uid="x",session_epoch=0,raw=dict(num_pit_stops=0,overall_frame_identifier=13))
    decision = SimpleNamespace(debug=dict(pit_timing_shadow=dict(nominal="next",verdict="uncertain",missing=[],
                                       options=dict(next=dict(stop_lap=4)))))
    feed.annotate(state,decision)
    review = decision.debug["grid_plan_review"]["selected"]
    checks["selected_plan_survives_start"] = review["stop_count"] == 1 and review["planned_lap"] == 3 and review["shadow_lap"] == 4
    return dict(passed=all(checks.values()), checks=checks)


if __name__ == "__main__":
    emit_result(run())

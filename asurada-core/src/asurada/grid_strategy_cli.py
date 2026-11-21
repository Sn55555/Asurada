"""Inspect a confirmed grid input, or one grid from the historical replay export."""
import argparse
import json
from pathlib import Path

from .grid_strategy import optimise, transition_capacity


def route_text(route):
    return " → ".join(f'{s["compound"]}（#{s["set"]}，{s["laps"]}圈）' for s in route["stints"])


def describe(plan, mode):
    if plan["status"] != "conditional":
        return "赛前资料不足：" + ", ".join(plan["missing"])
    group = plan[mode]
    lines = []
    for count, route in group["routes"].items():
        lines.append(f'{count} 停  {route_text(route)}')
    threshold = group["one_two_break_even_s"]
    if threshold is not None and threshold <= 0:
        lines.append("额外停车代价为正时，一停快于两停。")
    elif threshold is not None:
        lines.append(f'一停／两停分界 {threshold:.3f} 秒，额外一停的综合代价低于分界时两停更快。')
    if plan["forecast_changes_family"] or not plan["forecast_available"]:
        lines.append("以上按当前干湿状态维持至终点计算，天气转换仍待确认。")
    if pit_choice := group["best_at_price"]:
        lines.append("按给定停车成本排名第一的停数：" + "、".join(map(str, pit_choice)))
    elif group["best_for_every_positive_price"] is not None:
        lines.append(f'在每停代价为正时，首选 {group["best_for_every_positive_price"]} 停。')
    return "\n".join(lines) or "库存与赛制下没有可跑完的候选。"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("grid", type=Path, help="confirmed grid inputs or replay export grid.json")
    cli.add_argument("--uid", help="select a race from a replay export")
    cli.add_argument("--pit-seconds", type=float, help="scenario effective cost for each stop")
    cli.add_argument("--degradation-ms", default=0, type=int, help="extra lap time per lap of tyre age")
    cli.add_argument("--crossover-lap", type=int, help="first lap requiring the opposite tyre family")
    args = cli.parse_args()
    data = json.loads(args.grid.read_text())
    if isinstance(data, list):
        data = next((r for r in data if r.get("uid") == args.uid), None)
        if data is None:
            cli.error("choose a recorded race using --uid")
    grid = data.get("inputs", data)
    plan = optimise(grid, args.degradation_ms, args.pit_seconds)
    for mode, label in (("free_start", "可重选起步胎"), ("fitted_start", "保持当前起步胎")):
        print(label, describe(plan, mode), sep="\n")
    if args.crossover_lap is not None and plan["status"] == "conditional":
        print("指定干湿切换圈后可完成的停数（起步胎可选）",
              [k for k,v in transition_capacity(grid, args.crossover_lap).items() if v])


if __name__ == "__main__":
    main()

"""Audit confirmed losses by epoch and continuous rear identity, after both forward runs."""

import argparse
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

from asurada.attack_opportunity import forecast_primary

from score_defence_radio import side_geometry, target_row


def read_pair(prefix, prior, track):
    current = Path(f"{prefix}-{track}.jsonl")
    old = Path(f"{prior}-{track}.jsonl")
    rows = []
    with current.open() as a, old.open() as b:
        for c, p in zip(a, b):
            row, prev = json.loads(c), json.loads(p)
            assert row["src"] == prev["src"]
            state = SimpleNamespace(raw=dict(wing_damage_pct=prev["wing"],
                                    result_status=row["result"], session_paused=row["paused"]))
            row["old_primary"] = forecast_primary(state, prev["code"], prev["spoken_wing"])
            rows.append(row)
    return rows


def rear_rows(rows, event):
    """At most 12 s of the final uninterrupted tenure as the unique next car."""
    recent = []
    next_t = event["t"]
    for i in range(event["i"] - 1, -1, -1):
        r = rows[i]
        cars = [v for v in r["rivals"] if v[2] == r["pos"] + 1]
        if (r["epoch"] != rows[event["i"]]["epoch"] or not 0 <= next_t - r["t"] <= 0.65
                or event["t"] - r["t"] > 12 or len(cars) != 1
                or cars[0][0] != event["target"] or cars[0][3] != "NONE"):
            break
        next_t = r["t"]
        recent.append(r)
    return recent[::-1]


def first_overlap(samples, rows, event):
    target, i = event["target"], event["i"]
    since = None
    end = i
    # A pair can first become level just before the event. Allow later frames
    # to validate persistence, but never move onset forward beyond the event.
    while end + 1 < len(rows):
        following = rows[end + 1]
        if (following["epoch"] != rows[i]["epoch"]
                or not 0 <= following["t"] - rows[end]["t"] <= 0.35
                or following["t"] - event["t"] > 0.4):
            break
        end += 1
    for row in [*samples, *rows[i:end + 1]]:
        if side_geometry(target_row(row, target)):
            if since is None:
                since = row["t"]
            if since <= event["t"] and row["t"] - since >= 0.25:
                return since
        else:
            since = None
    return None


def fast_overlap(rows, samples, event):
    """Bound the first sampled entry of a fast, side-by-side crossing near a confirmed pass."""
    if not samples:
        return None
    i = event["i"]
    seq = [*samples, *rows[i:i + 5]]
    for j in range(1, len(seq) - 1):
        prev, inside = seq[j - 1:j + 1]
        if not 0 <= event["t"] - prev["t"] <= 1 or inside["t"] > event["t"]:
            continue
        pair = []
        for row in seq[j - 1:]:
            if (row["epoch"] != rows[i]["epoch"] or row["t"] - prev["t"] > 0.5
                    or pair and not 0 < row["t"] - pair[-1][0] <= 0.2):
                break
            car = target_row(row, event["target"])
            geo = car[4] if car and car[3] == "NONE" else None
            if not geo or not 1.7 <= abs(geo[1]) <= 5:
                break
            if pair and (geo[0] <= pair[-1][1] or geo[1] * pair[-1][2] <= 0):
                break
            pair.append((row["t"], *geo))
            if geo[0] > 4:
                if len(pair) >= 3 and pair[0][1] < -4 and -4 <= pair[1][1] <= 4:
                    return [prev["t"], inside["t"]]
                break
    return None


def physical_signal(samples, target, deadline):
    # Independent descriptive check, less demanding than the production prediction.
    # At least four metres gained during 0.5–0.8 s, with usable geometry in between.
    track = []
    for row in samples:
        car = target_row(row, target)
        if row["t"] > deadline:
            break
        if not car[4] or car[4][0] >= -4 or row["rear_confidence"] != "high":
            track.clear()
            continue
        track = [p for p in track if row["t"] - p[0] <= 0.8]
        track.append((row["t"], -car[4][0]))
        if (row["t"] - track[0][0] >= 0.5 and track[0][1] - track[-1][1] >= 4
                and track[-1][1] <= 150):
            yield row


def safety(row, version):
    return (row["effective_primary" if version == "新" else "old_primary"] not in ("NONE", "DEFEND_WINDOW", "ATTACK_WINDOW")
            or row["race_state"] != "green" or row["dynamics"] != "stable"
            or row["flag"] not in (0, 1, None) or row["pit"] != 0 or row["paused"]
            or row["result"] != 2 or row["safety_car"] != "NONE")


def stop_context(rows, call):
    if call["cut"] is None:
        return ""
    row = next((r for r in rows[call["i"]:call["i"] + 160] if r["t"] == call["cut"]), None)
    if row is None:
        return "缺少中断帧"
    car = target_row(row, call["target"])
    if car is None or car[2] != row["pos"] + 1:
        return "目标已非直接后车"
    if safety(row, call["version"]):
        return "安全或优先车况 " + row["effective_primary" if call["version"] == "新" else "old_primary"]
    if not (0 < (row["rear_gap"] or 0) < 10):
        return "间隔缺失或跳变"
    if call.get("closing") and not call["forecast"]:
        geo = car[4]
        if geo is None:
            return "同目标相对几何缺失"
        if -geo[0] > call["closing"]["distance_m"] + 5:
            return "后车间距已重新拉开"
    if call["forecast"] and (not row["defence"] or not row["defence"]["recommended"]
                             or row["defence"]["id"] != call["forecast"]["id"]):
        return "弯段预测撤回或切换"
    return "其余适用条件变化"


def verdict(event, samples, side, race, version, rows):
    e = event
    target = e["target"]
    start_i = samples[0]["i"] if samples else e["i"]
    calls = []
    for c in race["cases"]:
        if (c["version"] != version or c["target"] != target or c["i"] >= e["i"]
                or e["ms"] < rows[c["i"]]["wall"] * 1000 - 1 or rows[c["i"]]["epoch"] != rows[e["i"]]["epoch"]):
            continue
        if c["i"] < start_i:
            # A pass may settle several seconds after the first overlap. Keep an
            # earlier call only when its *own* horizon verifies the same overlap
            # and the target was the immediate rear continuously into this tenure.
            if side is None or c["alongside_s"] != side:
                continue
            intervening = rows[c["i"]:start_i + 1]
            if any(len([v for v in r["rivals"] if v[2] == r["pos"] + 1]) != 1
                   or not (car := target_row(r, target)) or car[2] != r["pos"] + 1 or car[3] != "NONE"
                   for r in intervening):
                continue
            if any(b["epoch"] != a["epoch"] or not 0 <= b["t"] - a["t"] <= 0.65
                   for a, b in zip(intervening, intervening[1:])):
                continue
        calls.append(c)
    deadline = e["t"] if side is None else side
    # Do not attach a call past its own forecast horizon to a later exchange.
    calls = [c for c in calls if c["through_s"] >= deadline]
    complete = [c for c in calls if c["end"] is not None and c["end"] < e["t"]]
    early = [c for c in complete if side is not None and c["end"] < side]
    selected = (early or complete or calls or [None])[-1]
    outcome = None
    if early:
        outcome = "并排前完播"
    elif complete:
        outcome = "被超前完播·并排未知" if side is None else "开口太晚"
    elif selected:
        if selected["cut"] is not None and selected["cut"] < e["t"] + 0.001:
            outcome = "被打断"
        else:
            outcome = "开口太晚"
    budget_end = deadline - 1.34  # Measured short line, rounded up. For diagnosis only.
    usable = [r for r in samples if r["t"] <= budget_end]
    signals = []
    for signal in physical_signal(samples, target, budget_end):
        distance = -target_row(signal, target)[4][0]
        later = [target_row(r, target)[4] for r in samples if signal["t"] < r["t"] <= deadline]
        if not any(geo and -geo[0] > distance + 12 for geo in later):
            signals.append(signal)
    final_geometry = [target_row(r, target)[4] for r in samples if 0 <= deadline - r["t"] <= 0.65]
    confirmed_approach = any(geo and abs(geo[0]) <= 12 for geo in final_geometry)
    named = [r for r in usable if r["defence"] and r["defence"]["recommended"]
             and r["defence"]["target"] == target]
    gaps = [r["rear_gap"] for r in usable if r["rear_confidence"] == "high" and r["rear_gap"] is not None]
    reason = ""
    if outcome is None:
        if not usable:
            reason = "连续成为直接后车时，已不足一条短句"
        elif all(safety(r, version) for r in usable):
            outcome = "安全或车况优先"
            reason = "可提前开口的帧均有更高优先级或非绿旗稳定状态"
        elif any(not safety(r, version) for r in named):
            outcome, reason = "已有预判未开口", "提前出现同目标弯段候选，电台未开口"
        elif any(not safety(r, version) for r in signals):
            if confirmed_approach:
                outcome, reason = "漏判", "提前出现持续逼近，后续几何确认贴近，但电台未开口"
            else:
                reason = "见到逼近趋势，但最后 0.65 秒缺同车贴近的几何佐证"
        elif not gaps:
            reason = "提前量范围内没有高置信后车间隔"
        elif not any(target_row(r, target)[4] for r in usable):
            reason = "提前量范围内缺同车相对几何"
        elif (sum(target_row(r, target)[4] is not None for r in usable) >= 0.8 * len(usable)
              and usable[-1]["t"] - usable[0]["t"] >= 0.6):
            outcome, reason = "事前未见持续逼近", "提前量内几何覆盖充分，但逼近未保持、车距重新拉开，或后车已在身侧"
        else:
            reason = "可提前开口的帧未建立持续逼近证据"
        outcome = outcome or "证据不足"
    if selected:
        reason = selected["text"]
        # Use wall time for an uncut sentence even if it actually stopped early.
        reference = next((r for r in samples if r["t"] >= deadline), rows[e["i"]])
        if (selected["cut"] is not None and rows[selected["i"]]["wall"] + selected["duration"]
                >= reference["wall"]):
            reason += " / 开口时整句已来不及"
        if selected["cut"] is not None:
            reason += " / 中断帧：" + stop_context(rows, selected)
    return dict(category=outcome, reason=reason, call=selected and selected["start"],
                finish=selected and selected["end"], interrupted=selected and selected["cut"],
                margin=side - selected["end"] if early else None,
                usable_frames=len(usable), geometry_frames=sum(target_row(r, target)[4] is not None for r in usable),
                eligible_frames=sum(not safety(r, version) for r in usable), gap_frames=len(gaps),
                geometry_signal=signals[0]["t"] if signals else None,
                recommended=named[0]["t"] if named else None)


def fmt(value):
    return "—" if value is None else f"{value:.2f}"


def main(prefix, prior, directory):
    scored = json.loads((directory / "逐窗口证据.json").read_text())
    records = {}
    lines = ["# 防守播报与被超事件逐次核对", "",
             "每个事件按归档序号和回退代数区分；时间和余量均为比赛秒。", "",
             "|赛道|版本|开播 / 完播 / 中断|其中短报|末段未接近 / 无法判定（开播）|确认被超|旧观察口径被超前完播|连续同一后车、并排前完播|",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for track, en in (("铃鹿", "Suzuka"), ("吉达", "Jeddah")):
        race = scored[track]
        rows = read_pair(prefix, prior, en)
        records[track] = []
        for e in race["passes"]:
            if not e["verified"]:
                continue
            samples = rear_rows(rows, e)
            side = first_overlap(samples, rows, e)
            bracket = fast_overlap(rows, samples, e) if side is None else None
            records[track].append(dict(event=e, epoch=rows[e["i"]]["epoch"], fast_entry=bracket,
                rear_s=e["t"] - samples[0]["t"] if samples else 0, side=side,
                **{v: verdict(e, samples, side, race, v, rows) for v in ("旧", "新")}))
            q = records[track][-1]
            for v in ("旧", "新"):
                end = q[v]["finish"]
                if bracket and end is not None and end < bracket[0]:
                    q[v]["fast_margin"] = [t - end for t in bracket]
        for v in ("旧", "新"):
            cases = [c for c in race["cases"] if c["version"] == v]
            narrowly_matched = {e["i"] for c in cases for e in c["passes"]
                                if c["end"] is not None and c["end"] < e["t"]}
            lines.append(f"|{track}|{v}|{len(cases)} / {sum(c['end'] is not None for c in cases)} / "
                         f"{sum(c['cut'] is not None for c in cases)}|{sum(not c['forecast'] for c in cases)}|"
                         f"{sum(c['verdict']=='末段未接近' for c in cases)} / {sum(c['verdict']=='不确定' for c in cases)}|"
                         f"{len(records[track])}|{len(narrowly_matched)}|"
                         f"{sum(q[v]['margin'] is not None for q in records[track])}|")
    lines += ["", "## 为什么会开口，为什么会中断", "",
              "旧版在主策略选中防守，或已有前翼提示且防守入选时，可以直接报「注意后车」。这条路检查名次、间隔和紧迫度，未要求同一后车持续追近。带弯段的预判另行放行，两类都计开播。下表按每条实际开播的后续结果计数。中断原因按中断帧可见的条件变化归类，同时变化的条件可能不止一个。", "",
              "|赛道 / 版本|同车反超 / 仅并排|末段未接近（其中短报）|不确定|中断时帧上可见的变化|",
              "|---|---:|---:|---:|---|"]
    for track, en in (("铃鹿", "Suzuka"), ("吉达", "Jeddah")):
        rows = read_pair(prefix, prior, en)
        for v in ("旧", "新"):
            cases = [c for c in scored[track]["cases"] if c["version"] == v]
            cuts = Counter(stop_context(rows, c) for c in cases if c["cut"] is not None)
            totals = Counter(c["verdict"] for c in cases)
            negative_short = sum(c["verdict"] == "末段未接近" and not c["forecast"] for c in cases)
            lines.append(f"|{track} / {v}|{totals['同车反超']} / {totals['同车并排']}|"
                         f"{totals['末段未接近']}（{negative_short}）|{totals['不确定']}|"
                         + ("，".join(f"{k} {n}" for k,n in cuts.items()) or "—") + "|")
    for track, events in records.items():
        lines += ["", f"## {track}", ""]
        for v in ("旧", "新"):
            lines.append(f"- {v}版：" + "，".join(f"{k} {n}" for k,n in Counter(q[v]["category"] for q in events).items()))
        lines += ["", "|圈 / 回退代数|后车|被超|连续直接后车秒数（上限12）|首次可核并排|旧版归因|新版归因|新版开口 / 完播 / 提前秒数|",
                  "|---|---|---:|---:|---:|---|---|---|"]
        for q in events:
            e=q["event"]
            annotated = [q[v]["category"] + " · " + q[v]["reason"] for v in ("旧","新")]
            ends = " / ".join(fmt(q["新"][k]) for k in ("call","finish","margin"))
            lines.append(f"|{e['lap']} / {q['epoch']}|{e['name']}|{fmt(e['t'])}|{fmt(q['rear_s'])}|"
                         f"{fmt(q['side'])}|{annotated[0]}|{annotated[1]}|{ends}|")
    lines += ["", "## 快速并排的独立核对", "",
              "上一版使用持续 0.25 秒的并排口径。高速掠过可能只留下 1–2 帧，此表另列可核实的入界时间区间，不加进主表的严格计数。要求相同回退代数、同一侧横距持续处于 1.7–5 米、纵距连续由小于 −4 米经过界内再大于 4 米。相邻样本至多隔 0.20 秒，且有同车反超事件。提前量给上下界，不将插值当实测。", "",
              "|赛道 / 圈 / 代数|后车|进入并排区间|旧版完播提前量|新版完播提前量|",
              "|---|---|---|---|---|"]
    for tr, events in records.items():
        for q in events:
            if q["fast_entry"]:
                margin = ["–".join(fmt(t) for t in q[v]["fast_margin"]) if q[v].get("fast_margin") else "—"
                          for v in ("旧", "新")]
                lines.append(f"|{tr} / {q['event']['lap']} / {q['epoch']}|{q['event']['name']}|"
                             + "–".join(fmt(t) for t in q["fast_entry"]) + "|" + "|".join(margin) + "|")
    lines += ["", "## 本版电台放行条件", "",
              "- 短报使用同一直接后车最近 0.6–1 秒的纵向距离。两半都要在逼近，平常各至少 9 米/秒，玩家重刹时各至少 20 米/秒。保留能在预计并排前说完的 1.7 秒下界，同时要求按较慢速度计算也在 4.5 秒之内。换车、掉帧过久或几何不可信时重新积累证据。",
              "- 同一后车的短报默认间隔 30 秒。若从上一条提醒后的实测最近点重新拉开至少 25 米，且连续 1 秒达到至少 50 米，此后出现至少 20 米/秒的再逼近，可在上一条 8 秒后重新提醒；车群换位还有 4 秒全局间隔。",
              "- 有可信几何时，后车纵距不足 12 米、或可用时间不足 3.8 秒，长句不再开口。排队等待会消耗这个预算。播出的弯段句可跨过最多半秒的预测波动，仍需同车、可信近距与有效车况。黄旗、紧急失稳、新增前翼损伤仍优先。",
              "", "## 读数方法", "",
              "- 两版在相同文件顺序与同一份实测语句时长表上运行。数据校验包括原始文件摘要、逐帧主决策和进攻预判。标签只在比赛回放结束后关联。",
              "- “末段未接近”是误报代理。具体弯段观察至制动点后 80 米，短句观察 10 秒；期间无已证实的同车并排或反超，且截止前一秒该车持续落后至少 0.60 秒。威胁后来解除也可能落在这一栏。不确定单列。全部语句、时刻和候选见[逐窗口明细](回放报告.md)。",
              "- 旧观察口径沿用从播报往后找事件。逐次归因从 OVTK 及至少 0.4 秒持续领先往前找，最多 12 秒，要求同一回退代数、连续为同一直接后车。若一句话早于这 12 秒，只在其原定观察范围已独立命中完全相同的首次并排、且中间始终是同一直接后车时关联；从已播语句往后的观察范围也须覆盖被超或已验证并排时刻。每次被超和每条播报各自只在对应统计中计一次。",
              "- 并排要求相对纵距绝对值 ≤4 米、横距绝对值 1.7–5 米，连续至少 0.25 秒。提前秒数用首个可核并排减去按音频时长插值得到的完播时刻。并排无法验证时仅比较被超时刻。",
              "- 主因互斥。被打断优先标出，并另记中断帧实际车况；“漏判”要求至少提前一条短句，在高置信车距下连续 0.5–0.8 秒追近至少 4 米，且距玩家不超过 150 米、有绿旗稳定帧，且后续可见几何没有比该点重新拉开超过 12 米；并排或被超前最后 0.65 秒内另需实测纵距在 12 米内。它是有迹可查的复盘线索，不能推出每次都应该播。第一次成为后车就已并排、临时换位、无有效几何等均保留证据边界。安全或车况优先另列。旧版总计的中断中，若开口时余量本已不足，会在同一行另标「开口时整句已来不及」。",
              "- 两场是已知历史样本上的顺序回归。真实耳机首音、设备延迟与玩家能否听清仍待实跑。"]
    (directory / "被超逐次归因.md").write_text("\n".join(lines)+"\n")
    (directory / "被超逐次归因.json").write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("prior")
    parser.add_argument("output", type=Path)
    args=parser.parse_args()
    main(args.prefix, args.prior, args.output)

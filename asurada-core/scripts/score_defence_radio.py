"""Join frozen defence radio starts with subsequent same-car telemetry after a forward replay."""

import argparse
import json
from pathlib import Path

from score_attack_forecast_replay import blend


def read(path):
    return json.loads(path.read_text())


def target_row(row, target):
    return next((r for r in row["rivals"] if r[0] == target), None)


def observed_passes(rows):
    events = []
    seen = set()
    for r in rows:
        e, stamp = r["event"], r["event_ms"]
        if not e or e["being_overtaken_vehicle_idx"] != r["player"] or stamp is None:
            continue
        target = e["overtaking_vehicle_idx"]
        key = r["epoch"], stamp, target
        if key in seen or not 0 <= r["wall"] * 1000 - stamp <= 1500:
            continue
        seen.add(key)
        # Require the same opponent ahead, outside the pit lane, continuously after the event.
        end = r
        for later in rows[r["i"] : r["i"] + 45]:
            opponent = target_row(later, target)
            if (
                later["epoch"] != r["epoch"]
                or not 0 <= later["t"] - end["t"] <= 0.65
                or not opponent
                or opponent[2] >= later["pos"]
                or opponent[3] != "NONE"
            ):
                break
            end = later
            if end["t"] - r["t"] >= 0.4:
                break
        opponent = target_row(r, target)
        events.append(
            dict(
                i=r["i"],
                t=r["t"],
                ms=stamp,
                lap=r["lap"],
                target=target,
                name=opponent[1] if opponent else str(target),
                source=r["src"],
                verified=end["t"] - r["t"] >= 0.4,
            )
        )
    return events


def finish_time(rows, job):
    if "cut" in job:
        return None
    i = job["i"]
    end = job["wall"] + job["duration"]
    for j in range(i + 1, min(i + 200, len(rows))):
        before, after = rows[j - 1], rows[j]
        if (
            after["epoch"] != before["epoch"]
            or not 0 <= after["t"] - before["t"] <= 0.65
            or not 0 <= after["wall"] - before["wall"] <= 0.8
        ):
            break
        if before["wall"] < end <= after["wall"]:
            return blend(before, after, "wall", end)
    return None


def side_geometry(rival):
    geometry = rival[4] if rival and rival[3] == "NONE" else None
    return geometry and abs(geometry[0]) <= 4 and 1.7 <= abs(geometry[1]) <= 5


def grade(rows, events, start, target, forecast):
    first = rows[start]
    stop = (forecast["gate_lap"] - 1) * forecast["length_m"] + forecast["gate_m"] if forecast else None
    gate = side_start = alongside = None
    # A late call may begin during an existing overlap. Preserve its actual onset.
    if side_geometry(target_row(first, target)):
        side_start = first["t"]
        for i in range(start - 1, -1, -1):
            prev = rows[i]
            if (
                prev["epoch"] != first["epoch"]
                or not 0 <= side_start - prev["t"] <= 0.65
                or not side_geometry(target_row(prev, target))
            ):
                break
            side_start = prev["t"]
    last = first
    previous_dist = None
    final_gaps = []
    covered = False
    for row in rows[start : start + 700]:
        if row["epoch"] != first["epoch"] or not 0 <= row["t"] - last["t"] <= 0.65:
            break
        if forecast:
            absolute = (row["lap"] - 1) * forecast["length_m"] + row["dist"]
            if previous_dist is not None:
                if not -4 <= absolute - previous_dist <= 125 * (row["t"] - last["t"]) + 4:
                    break
                if previous_dist < stop <= absolute:
                    gate = last["t"] + (row["t"] - last["t"]) * (stop - previous_dist) / (
                        absolute - previous_dist
                    )
            previous_dist = absolute
        rival = target_row(row, target)
        side = side_geometry(rival)
        if not side:
            side_start = None
        elif side_start is None:
            side_start = row["t"]
        if side_start is not None and row["t"] - side_start >= 0.25 and alongside is None:
            alongside = side_start
        matched_gap = (
            row["rear_gap"]
            if (
                rival
                and rival[2] == row["pos"] + 1
                and rival[3] == "NONE"
                and row["rear_confidence"] == "high"
            )
            else None
        )
        final_gaps.append((row["t"], matched_gap))
        last = row
        if (forecast and absolute >= stop + 80) or (not forecast and row["t"] >= first["t"] + 10):
            covered = True
            break
    passes = [
        e
        for e in events
        if e["verified"]
        and e["target"] == target
        and start <= e["i"] <= last["i"]
        and e["ms"] >= first["wall"] * 1000 - 1
    ]
    end = gate if gate is not None else last["t"]
    tail = [g for t, g in final_gaps if end - 1 <= t <= end]
    distant = covered and len(tail) >= 3 and all(g is not None and g >= 0.60 for g in tail)
    verdict = (
        "同车反超"
        if passes
        else "同车并排"
        if alongside is not None
        else "末段未接近"
        if distant
        else "不确定"
    )
    return dict(
        verdict=verdict,
        alongside_s=alongside,
        passes=passes,
        gate_s=gate,
        complete_coverage=covered,
        through_s=last["t"],
        last_second_gaps=tail,
    )


def score(prefix, prior):
    rows = list(map(json.loads, prefix.with_suffix(".jsonl").open()))
    meta = read(prefix.with_suffix(".json"))
    prior_meta = read(prior.with_suffix(".json"))
    assert (
        prior_meta["frames"] == len(rows) == meta["frames"]
        and prior_meta["archive_sha256"] == meta["archive_sha256"]
    )
    with prior.with_suffix(".jsonl").open() as src:
        for r, line in zip(rows, src):
            before = json.loads(line)
            if "defence" in before:
                assert r["defence"] == before["defence"]
            assert (r["src"], r["t"], r["code"], r["forecast"]) == (
                before["src"],
                before["t"],
                before["code"],
                before["forecast"],
            )
    events = observed_passes(rows)
    cases = []
    starts = {}
    for version, record in (("旧", prior_meta), ("新", meta)):
        for job in record["starts"]:
            if job["code"] != "DEFEND_WINDOW":
                continue
            row = rows[job["i"]]
            bound = job.get("defence")
            behind = [v for v in row["rivals"] if v[2] == row["pos"] + 1]
            rival = target_row(row, bound["target"]) if bound else (behind[0] if len(behind) == 1 else None)
            target = rival[0] if rival else None
            f = bound.get("forecast") if bound else None
            end = finish_time(rows, job)
            grade_result = grade(rows, events, job["i"], target, f)
            beside = grade_result["alongside_s"]
            cases.append(
                dict(
                    version=version,
                    lap=row["lap"],
                    start=row["t"],
                    duration=job["duration"],
                    i=row["i"],
                    text=job["text"],
                    source=row["src"],
                    target=target,
                    name=rival[1] if rival else "?",
                    forecast=f,
                    closing=bound.get("closing") if bound else None,
                    approach=bound.get("approach") if bound else None,
                    gap=row["rear_gap"],
                    end=end,
                    cut=rows[job["cut"]]["t"] if "cut" in job else None,
                    margin=beside - end if beside is not None and end is not None else None,
                    **grade_result,
                )
            )
            if version == "新" and bound and bound["gate"]:
                starts.setdefault(bound["gate"], []).append(cases[-1])
    windows = {}
    for row in rows:
        f = row["defence"]
        if f and f["recommended"] and f["id"] not in windows:
            jobs = starts.get(f["id"], [])
            windows[f["id"]] = dict(
                first=row["t"],
                lap=row["lap"],
                source=row["src"],
                forecast=f,
                started=jobs[0]["start"] if jobs else None,
                broadcasts=[dict(t=x["start"], text=x["text"], end=x["end"]) for x in jobs],
                **grade(rows, events, row["i"], f["target"], f),
            )
    return dict(
        frames=len(rows),
        archive=meta["archive_sha256"],
        cases=cases,
        windows=list(windows.values()),
        passes=events,
    )


def display(x):
    return "—" if x is None else f"{x:.2f}"


def report(data):
    lines = [
        "# 铃鹿、吉达防守电台回归",
        "",
        "| 赛道 | 帧 | 旧版开播 / 完播 | 新版开播 / 完播 | 新版具体弯段 / 紧急短报 | 后车并排前听完 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tr, r in data.items():
        old = [x for x in r["cases"] if x["version"] == "旧"]
        new = [x for x in r["cases"] if x["version"] == "新"]
        lines.append(
            f"| {tr} | {r['frames']} | {len(old)} / {sum(x['end'] is not None for x in old)} | "
            f"{len(new)} / {sum(x['end'] is not None for x in new)} | "
            f"{sum(bool(x['forecast']) for x in new)} / {sum(not x['forecast'] for x in new)} | "
            f"{sum(x['margin'] is not None and x['margin'] > 0 for x in new)} |"
        )
    lines += [
        "",
        "## 误报和漏报核对",
        "",
        "| 赛道 | 前瞻候选 | 末段未接近的候选 | 其中开播 / 完播 | 确认被超 | 观察范围内被超前有同目标完播（旧 / 新） |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for track, race in data.items():
        windows = race["windows"]
        negatives = [w for w in windows if w["verdict"] == "末段未接近"]
        events = [e for e in race["passes"] if e["verified"]]
        counts = [
            len(
                {
                    e["i"]
                    for c in race["cases"]
                    if c["version"] == version
                    for e in c["passes"]
                    if c["end"] is not None and c["end"] < e["t"]
                }
            )
            for version in ("旧", "新")
        ]
        lines.append(
            f"| {track} | {len(windows)} | {len(negatives)} | {sum(bool(w['broadcasts']) for w in negatives)} / "
            f"{sum(any(b['end'] is not None for b in w['broadcasts']) for w in negatives)} | "
            f"{len(events)} | {counts[0]} / {counts[1]} |"
        )
    lines += [
        "",
        "按候选形成时刻核对弯段。后面的开播表从实际开口时刻核对，另含缺少弯段预测时的贴近短报。",
        "",
    ]
    lines += [
        "",
        "## 全部新旧开播",
        "",
        "时间单位为比赛秒。负余量表示说完时两车已并排，空值表示未完播或没有足够的并排证据。",
        "",
        "| 赛道 / 版本 | 圈 | 后车 | 电台原话 | 开播 | 完播 | 中断 | 首次可核并排 | 完播至并排 | 结果 |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for tr, r in data.items():
        for x in r["cases"]:
            lines.append(
                f"| {tr} / {x['version']} | {x['lap']} | {x['name']} | {x['text']} | "
                + " | ".join(display(x[k]) for k in ("start", "end", "cut", "alongside_s", "margin"))
                + f" | {x['verdict']} |"
            )
    lines += [
        "",
        "## 全部达到条件的前瞻窗口",
        "",
        "开播栏按后车、目标圈及地图制动点匹配，含直接报短句的情形。",
        "",
        "| 赛道 | 圈 | 后车 | 地图制动点（米） | 首次建议 | 开播 | 复核 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for tr, r in data.items():
        for w in r["windows"]:
            f = w["forecast"]
            lines.append(
                f"| {tr} | {w['lap']} | {f['name']} | {f['gate_m']:.0f} | {w['first']:.2f} | "
                f"{display(w['started'])} | {w['verdict']} |"
            )
    lines += [
        "",
        "## 确认被超的事件",
        "",
        "下表覆盖归档中能用同一后车身份和持续排名确认的被超事件。每次完播只在已定义的观察范围内关联。",
        "",
        "| 赛道 | 圈 | 后车 | 被超时刻 | 旧版事前完播 | 新版事前完播 |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for tr, race in data.items():
        for e in race["passes"]:
            if not e["verified"]:
                continue
            matched = [x for x in race["cases"] if e in x["passes"]]
            name = e["name"]
            ends = [
                max(
                    (
                        x["end"]
                        for x in matched
                        if x["version"] == v and x["end"] is not None and x["end"] < e["t"]
                    ),
                    default=None,
                )
                for v in ("旧", "新")
            ]
            lines.append(
                f"| {tr} | {e['lap']} | {name} | {e['t']:.2f} | {display(ends[0])} | {display(ends[1])} |"
            )
    lines += [
        "",
        "## 核验口径",
        "",
        "- 按归档顺序输入比赛快照，调用策略引擎和电台调度，结束后才关联同目标的 OVTK。这两份归档也用于排查重复开口；最终版固定规则后从头复跑，属于开发回归。两版本使用相同输入与同一份离线音频实测时长表。比赛时钟由相邻快照插值，未计真实耳麦及合成首音延迟。",
        "- 同车并排要求纵距绝对值不超过 4 米、横向间距 1.7–5 米，持续至少 0.25 秒。反超另需后车超越玩家的事件和至少 0.4 秒持续领先。缺少几何时可确认反超而无法计算并排提前量。多条提醒可能涉及同一事件。",
        "- 对具体弯段观察至制动点后 80 米；对短提醒使用开播后 10 秒。连续观察至截止点，最后一秒保持同一后车且官方间隔始终至少 0.60 秒，又缺少已确认的并排或反超，列为“末段未接近”。它也包括真实威胁后来消退的情形。其余无充分证据的情形保留为“不确定”。",
        "- 跨线圈距用于预判，旧档缺对手官方完整分段和 DRS 激活距离；使用近期可配对的实测同段和实际可见的后车 DRS、ERS。没有按轮胎名称补造固定圈速差。",
        "",
        "[逐窗输入、比赛事件、归档位置及新旧播放结果](逐窗口证据.json)",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", help="Replay prefix followed by -Suzuka / -Jeddah")
    parser.add_argument("prior")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = {
        cn: score(Path(args.current + "-" + en), Path(args.prior + "-" + en))
        for cn, en in (("铃鹿", "Suzuka"), ("吉达", "Jeddah"))
    }
    (args.output / "逐窗口证据.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    (args.output / "回放报告.md").write_text(report(data))

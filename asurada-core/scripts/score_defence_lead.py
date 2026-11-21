"""Score frozen live-entry-point radio jobs against same-opponent overlap and pass evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path

from audit_defence_passes import fast_overlap, first_overlap, read_pair, rear_rows, verdict
from score_defence_radio import display, score


def checked_race(current, previous, track):
    a, b = (Path(f"{prefix}-{track}") for prefix in (current, previous))
    race = score(a, b)
    rows = read_pair(current, previous, track)
    races = [json.loads(p.with_suffix(".json").read_text()) for p in (b, a)]
    safety = {"LOCAL_YELLOW", "DYNAMICS_UNSTABLE", "TYRE_DAMAGE", "FRONT_WING_DAMAGE"}
    race["priority_starts"] = [[(j["i"], j["code"]) for j in v["starts"] if j["code"] in safety] for v in races]
    race["events"] = []
    for event in race["passes"]:
        if not event["verified"]:
            continue
        samples = rear_rows(rows, event)
        side = first_overlap(samples, rows, event)
        bracket = [side, side] if side is not None else fast_overlap(rows, samples, event)
        e = dict(**event, epoch=rows[event["i"]]["epoch"], distance_m=rows[event["i"]]["dist"],
                 side=bracket, sustained=side is not None)
        for v in ("旧", "新"):
            q = verdict(event, samples, side, race, v, rows)
            job = next((x for x in race["cases"] if x["version"] == v and x["target"] == event["target"]
                        and x["start"] == q["call"] and rows[x["i"]]["epoch"] == e["epoch"]), None)
            q["speech"] = job["text"] if job else None
            q["margin_range"] = [t - q["finish"] for t in bracket] if bracket and q["finish"] else None
            q["pass_margin"] = e["t"] - q["finish"] if q["finish"] is not None else None
            e[v] = q
        race["events"].append(e)
    return race


def margin(q):
    values = q["margin_range"]
    if not values:
        return "—"
    if values[0] == values[1]:
        return display(values[0])
    return " 至 ".join(display(n) for n in values)


def main(current, previous, output):
    data = {cn: checked_race(current, previous, en) for cn,en in (("铃鹿","Suzuka"),("吉达","Jeddah"))}
    lines = ["# 防守预判提前量回放", "", "|赛道|版本|帧|开播 / 完播|仅说注意后车|末段未接近 / 不确定|确认被超|持续并排前完播 / 快速并排前完播|",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for cn, r in data.items():
        for v in ("旧","新"):
            cases=[x for x in r["cases"] if x["version"] == v]
            counts=Counter(x["verdict"] for x in cases)
            early=[e for e in r["events"] if e[v]["margin_range"] and min(e[v]["margin_range"]) > 0]
            lines.append(f"|{cn}|{v}|{r['frames']}|{len(cases)} / {sum(x['end'] is not None for x in cases)}|"
                         f"{sum(x['text']=='注意后车。' for x in cases)}|{counts['末段未接近']} / {counts['不确定']}|"
                         f"{len(r['events'])}|{sum(e['sustained'] for e in early)} / {sum(not e['sustained'] for e in early)}|")
    lines += ["", "## 每次确认被超", "", "时间为比赛秒。回退代数用来区分同圈同名事件。并排提前量空白时，可另查被超前的余量。",
              "", "|赛道 / 圈 / 回退代数|后车|被超时刻|旧版原话 / 并排提前量|新版原话|开口 / 完播|并排提前量|完播到被超|",
              "|---|---|---:|---|---|---:|---:|---:|"]
    for cn,r in data.items():
        for e in r["events"]:
            old, q = e["旧"], e["新"]
            lines.append(f"|{cn} / {e['lap']} / {e['epoch']}|{e['name']}|{display(e['t'])}|"
                         f"{old['speech'] or '未播'} / {margin(old)}|{q['speech'] or '未播'}|"
                         f"{display(q['call'])} / {display(q['finish'])}|{margin(q)}|{display(q['pass_margin'])}|")
    lines += ["", "## 全部实际开口", "",
              "|赛道 / 版本|圈|后车|播报|开口 / 完播 / 中断|结果|", "|---|---:|---|---|---:|---|"]
    for cn,r in data.items():
        for x in r["cases"]:
            times=" / ".join(display(x[k]) for k in ("start","end","cut"))
            lines.append(f"|{cn} / {x['version']}|{x['lap']}|{x['name']}|{x['text']}|{times}|{x['verdict']}|")
    lines += ["", "## 核对口径", "",
              "- 归档按原始接收顺序经过策略引擎和实际语音调度。两版逐帧核对源文件摘要、主策略、进攻及防守预判。赛后才关联相同后车的反超事件。两份历史日志均为开发回归，真人耳机延迟待实跑。",
              "- 语句时长来自同一离线 Piper 模型的音频采样点数。既有语句沿用基线时长，新语句见[时长表](播报时长.json)。",
              "- 同一后车连续至少 0.25 秒处于并排范围计为持续并排；快速并排单列，要求相邻采样不超过 0.20 秒，横距始终在同一侧 1.7–5 米内，纵距连续穿过 −4 米至 +4 米。无法核实入界时刻时只给完播至被超余量。",
              "- 误报代理沿用上版口径：具体弯段预测观察到制动点后 80 米，即时提醒观察 10 秒；期间无同车并排或反超，末秒又持续落后至少 0.60 秒，计为末段未接近。新加的地点短句按即时提醒统计。威胁后来消退也可能落在此栏。",
              "- 回放包含真实日志的回退。相同名字及相近的比赛秒不跨回退代数合并。完整输入摘要、播报依据及并排时间区间见[逐帧关联结果](回放证据.json)。"]
    (output/"回放报告.md").write_text("\n".join(lines)+"\n")
    (output/"回放证据.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current")
    parser.add_argument("previous")
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    main(args.current,args.previous,args.output)

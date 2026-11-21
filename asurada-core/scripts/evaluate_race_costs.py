"""Offline race-held-out cost calibration. Input is race_cost_inventory.py JSON."""
import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
from statistics import median

DRY = {16,17,18,19,20,21,22}


def full(r):
    f = r["final"] or {}
    return (not r["spectator"] and r["start"] and f.get("status")==3
            and f["laps"]==r["length"] and len(r["records"])==r["length"])


def green(r, lap):
    return (lap["lap"] not in r["rewound_laps"] and lap["control"]==[0]
            and lap["wing"]==[0] and lap["compound"] in DRY
            and bool(lap["weather"]) and max(lap["weather"])<=2 and not lap["invalid"]
            and lap["sectors"]==[0,1,2] and lap["distance"][1]-lap["distance"][0] > .90*r["track_m"]
            and abs(sum(lap["splits"])-lap["seconds"])<.02 and lap["valid"]&15==15)


def clear_sectors(lap, indices):
    return all(i not in lap["hits"] and lap["free"][i]>0
               and lap["near"][i]/lap["free"][i]<=.20 for i in indices)


def segment(lap, indices):
    return sum(lap["splits"][i] for i in indices)


def extract(r):
    laps = {x["lap"]:x for x in r["records"]}
    stops, stints, eligible = [], [], []
    # Bound stints by observed pit lane timing, including same-compound changes.
    inlaps = [n for n,v in laps.items() if v["pit"] and n+1 in laps and laps[n+1]["pit"] and
              (n-1 not in laps or not laps[n-1]["pit"]) and laps[n+1]["age"]==0]
    for n in inlaps:
        entry, out = laps[n], laps[n+1]
        prior = [x for j,x in laps.items() if 1 < j < n and n-j<=5
                 and x["compound"]==entry["compound"] and x["age"]==entry["age"]-(n-j)
                 and not x["pit"] and green(r,x) and clear_sectors(x,(0,2))]
        post = [x for j,x in laps.items() if n+2 < j <= n+6 and not x["pit"]
                and x["compound"]==out["compound"] and x["age"]==j-n-1 and green(r,x)
                and clear_sectors(x,(1,2))]
        geometry = entry["lane_sectors"] == [2] and out["lane_sectors"] == [0]
        pit=None
        warm=None
        if (geometry and len(prior)>=2 and green(r,entry) and green(r,out)
                and clear_sectors(entry,(2,)) and clear_sectors(out,(0,))):
            pit=entry["splits"][2]+out["splits"][0]-median([segment(x,(0,2)) for x in prior])
        if (geometry and len(post)>=2 and green(r,out) and clear_sectors(out,(1,2))
                and 1 in map(int,out["temp"]) and 2 in map(int,out["temp"])):
            warm=segment(out,(1,2))-median([segment(x,(1,2)) for x in post])
        # Retrospective sensitivity only: hold the observed gross pace benefit
        # fixed while swapping predicted versus labelled pit cost.
        old_laps=[x for x in prior if clear_sectors(x,(0,1,2))]
        new_laps=[x for x in post if clear_sectors(x,(0,1,2))]
        horizon=min(10, r["length"]-n-1)
        gross=None
        if len(old_laps)>=2 and len(new_laps)>=2 and horizon>0:
            gross=horizon*(median(x["seconds"] for x in old_laps)-median(x["seconds"] for x in new_laps))
        stops.append(dict(uid=r["uid"],track=r["track"],local=r["local"],lap=n, geometry=geometry, entry_clear=clear_sectors(entry,(2,)),
                          exit_clear=clear_sectors(out,(0,)), tail_clear=clear_sectors(out,(1,2)),
                          new=out["compound"],pit=pit,warm=warm,horizon=horizon,gross_proxy=gross,
                          raw_cross=entry["splits"][2]+out["splits"][0],
                          in_reference=[x["lap"] for x in prior],out_reference=[x["lap"] for x in post],
                          lane_s=max(entry["lane_ms"],out["lane_ms"])/1000,
                          service_s=max(entry["service_ms"],out["service_ms"])/1000,
                          temp_s2=out["temp"].get("1"),temp_s3=out["temp"].get("2")))
    groups=defaultdict(list)
    for n,x in laps.items():
        if (n<=1 or x["age"] is None or x["age"]<2 or x["pit"] or not green(r,x)
                or not clear_sectors(x,(0,1,2))):
            continue
        groups[(n-x["age"],x["compound"])].append(x)
    for (start,c),group in groups.items():
        if len(group)<5 or group[-1]["age"]-group[0]["age"]<5:
            continue
        slopes=[(b["seconds"]-a["seconds"])/(b["age"]-a["age"])
                for a,b in combinations(group,2)]
        slope=median(slopes)
        stints.append(dict(uid=r["uid"],track=r["track"],local=r["local"],start=start,compound=c,
            laps=[x["lap"] for x in group],slope=slope,normalized=slope/median(x["seconds"] for x in group),
            anchor_seconds=group[0]["seconds"],fuel_start=group[0]["fuel"],fuel_end=group[-1]["fuel"]))
        eligible.extend((a,b,c) for a,b in zip(group,group[1:]) if b["lap"]==a["lap"]+1)
    return stops,stints,eligible


def by_race(rows, value):
    races=defaultdict(list)
    for r in rows:
        races[r["uid"]].append(r[value])
    return median(median(samples) for samples in races.values())


def evaluate(inputs):
    races={}
    for source in inputs:
        for r in source["races"]:
            # Keep the most complete copy. All targets for a UID share a fold.
            old=races.get(r["uid"])
            if old is None or (full(r),len(r["records"]))>(full(old),len(old["records"])):
                races[r["uid"]]=r
    stops,stints,targets=[],[],{}
    for uid,r in races.items():
        if full(r):
            events,trends,targets[uid]=extract(r)
            stops.extend(events);stints.extend(trends)
    scores=[]
    for event in stops:
        for metric in ("pit","warm"):
            if event[metric] is None:
                continue
            train=[s for s in stops if s["uid"]!=event["uid"] and s[metric] is not None]
            matching=[s for s in train if s["track"]==event["track"] and
                      (metric=="pit" or s["new"]==event["new"])]
            for name,rows in (("same_layout",matching),("cross_layout_constant",train)):
                if rows:
                    prediction=by_race(rows,metric)
                    scores.append(dict(metric=metric,model=name,uid=event["uid"],lap=event["lap"],
                        prediction=prediction,observed=event[metric],error=prediction-event[metric],
                        training_uids=sorted({x["uid"] for x in rows})))
    for stint in stints:
        train=[s for s in stints if s["uid"]!=stint["uid"] and s["compound"]==stint["compound"]]
        if train:
            prediction=stint["anchor_seconds"]*by_race(train,"normalized")
            scores.append(dict(metric="slope",model="same_compound_transfer",uid=stint["uid"],
                lap=stint["laps"][0],compound=stint["compound"],prediction=prediction,
                observed=stint["slope"],error=prediction-stint["slope"],training_uids=sorted({x["uid"] for x in train})))
    for uid,pairs in targets.items():
        for a,b,c in pairs:
            train=[s for s in stints if s["uid"]!=uid and s["compound"]==c]
            if not train:
                continue
            prediction=a["seconds"]*(1+by_race(train,"normalized"))
            scores.append(dict(metric="pace",model="same_compound_transfer",uid=uid,lap=b["lap"],
                       compound=c,prediction=prediction,observed=b["seconds"],error=prediction-b["seconds"],
                       persistence_error=a["seconds"]-b["seconds"],training_uids=sorted({x["uid"] for x in train})))
    sensitivity=[]
    for fold in scores:
        if fold["metric"]!="pit" or fold["model"]!="cross_layout_constant":
            continue
        e=next(e for e in stops if (e["uid"],e["lap"])==(fold["uid"],fold["lap"]))
        gross=e["gross_proxy"]
        if gross is not None:
            sensitivity.append(dict(uid=e["uid"],lap=e["lap"],horizon=e["horizon"],gross_proxy=gross,
                predicted_margin=gross-fold["prediction"],label_margin=gross-fold["observed"],
                flip=(gross>fold["prediction"]) != (gross>fold["observed"])))
    # Five-lap forecasts start with only the observed anchor lap. The label is
    # total future green-lap elapsed time, useful for evaluating a stop margin.
    for uid, pairs in targets.items():
        for anchor, first, compound in pairs:
            forward = {a["lap"]: b for a,b,c in pairs if c==compound}
            next_laps = [forward.get(anchor["lap"]+i) for i in range(5)]
            if any(x is None for x in next_laps):
                continue
            train=[s for s in stints if s["uid"]!=uid and s["compound"]==compound]
            if not train:
                continue
            base=5*anchor["seconds"]
            prediction=base+15*anchor["seconds"]*by_race(train,"normalized")
            observed=sum(x["seconds"] for x in next_laps)
            scores.append(dict(metric="five_lap_total",model="same_compound_transfer",uid=uid,lap=anchor["lap"],
                       compound=compound,prediction=prediction,observed=observed,error=prediction-observed,
                       persistence_error=base-observed,training_uids=sorted({x["uid"] for x in train})))
    return dict(sources=len(inputs),unique_race_uids=len(races),complete_uids=[u for u,r in races.items() if full(r)],
                stops=stops,stints=stints,folds=scores,sensitivity=sensitivity)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("inventory",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    report=evaluate(json.loads(args.inventory.read_text()))
    assert all(x["uid"] not in x["training_uids"] for x in report["folds"])
    args.output.write_text(json.dumps(report,indent=2))


if __name__=="__main__":
    main()

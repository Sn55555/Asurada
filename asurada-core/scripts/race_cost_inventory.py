"""Extract player-only official race laps and observable context from local F1 25 captures."""
import argparse
import base64
import json
import struct
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from asurada.pdu_decoder import F125PacketDecoder

ROOT = Path(__file__).resolve().parents[2]
COMMUNITY = ROOT / "output/community-full-coverage-20260915"
DEC = F125PacketDecoder()
SIZES = DEC.PACKET_SIZES


def payloads(path):
    if path.suffix == ".jsonl":
        with path.open("rb") as stream:
            for line in stream:
                yield base64.b64decode(json.loads(line)["payload_base64"])
    elif path.suffix == ".gz":
        sys.path.insert(0, str(COMMUNITY))
        from audit_recordings import packets
        for _, data in packets(path):
            yield data
    else:
        header = struct.Struct("<QH" if path.suffix == ".f1bin" else "<IQ")
        with path.open("rb") as stream:
            while prefix := stream.read(header.size):
                size = header.unpack(prefix)[1 if path.suffix == ".f1bin" else 0]
                data = stream.read(size)
                if len(data) != size or not 29 <= size <= 65536:
                    raise ValueError("invalid UDP record")
                yield data


def lap_summary():
    return dict(samples=0, traffic=0, missing_gap=0, invalid=False, incident=False, pit=False,
                service_ms=0, lane_ms=0, control=set(), weather=set(), wing=set(),
                compounds=Counter(), age=Counter(), fuel=[], distance=[], sectors=set(), near=[0]*3, free=[0]*3, hits=set(), temp={}, lane_sectors=set())


def read_file(path):
    sessions = {}
    for b in payloads(path):
        if len(b) < 29 or b[:3] != b'\xe9\x07\x19' or b[5] != 1:
            continue
        kind = b[6]
        if kind not in {1, 2, 3, 6, 7, 8, 10, 11} or len(b) != SIZES[kind] or b[27] >= 22:
            continue
        uid = str(int.from_bytes(b[7:15], "little"))
        car = b[27]
        time = struct.unpack_from("<f", b, 15)[0]
        s = sessions.setdefault(uid, dict(laps={}, types=set(), start=False, rewind=False, spectator=False,
                                         current=0, latest=-1., history={}, final=None, rewound_laps=set(), flashback_pending=False))
        if kind == 1:
            session = DEC._decode_session(b)
            s["types"].add(session["session_type"])
            s.update(track=session["track_id"], length=session["total_laps"], length_code=session["session_length"],
                     weather=session["weather"], control=session["safety_car_status"], track_m=session["track_length_m"])
            s["spectator"] |= session["is_spectating"]
            continue
        if kind == 3:
            event = b[29:33]
            if event in (b"LGOT", b"SSTA"):
                s["start"] = True
            if event == b"FLBK":
                s["rewind"] = True
                s["flashback_pending"] = True
            row = s["laps"].get(s["current"])
            if row and ((event == b"COLL" and car in b[33:35]) or (event == b"PENA" and b[35] == car)):
                row["incident"] = True
                row["hits"].add(s.get("sector", -1))
            continue
        if not s["types"].intersection({15, 16, 17}):
            continue
        if kind == 8:
            # F1 25 classification has a resultReason byte after resultStatus.
            p = 30 + car * 46
            s["final"] = dict(laps=b[p+1], stops=b[p+4], status=b[p+5])
        elif kind == 11 and b[29] == car:
            s["history"] = DEC._decode_session_history(b)
        elif kind == 6:
            values = struct.unpack_from(DEC.CAR_TELEMETRY_FORMAT,b,29+car*DEC.CAR_TELEMETRY_SIZE)
            s["inner"] = (time, sum(values[18:22])/4)
        elif kind == 7:
            status = DEC._decode_car_status_car(b, car)
            s["tyre"] = (time, status["actual_tyre_compound"], status["tyres_age_laps"], status["fuel_remaining_laps"])
            s["fuel_kg"] = struct.unpack_from("<f", b, 29+car*DEC.CAR_STATUS_SIZE+5)[0]
        elif kind == 10:
            p = 29 + 46*car + 28
            s["damage"] = (time, max(b[p:p+6]))
        elif kind == 2:
            p = 29 + 57*car
            lap = b[p+33]
            if not 1 <= lap <= s.get("length", 0) or b[p+45] != 2:
                continue
            if s["latest"] > time + 3 or s["flashback_pending"]:
                s["rewind"] = True
                s["rewound_laps"].add(lap)
                s["laps"] = {n: item for n,item in s["laps"].items() if n < lap}
                s["flashback_pending"] = False
            s["sector"] = b[p+36]
            s["latest"] = time
            s["current"] = lap
            r = s["laps"].setdefault(lap, lap_summary())
            r["samples"] += 1
            gap = struct.unpack_from("<H", b, p+14)[0] + 60000*b[p+16]
            r["traffic"] += 0 < gap < 1200 and b[p+32] > 1
            sector = b[p+36]
            if sector < 3 and not (b[p+34] or b[p+46]):
                r["near"][sector] += int(b[p+32] > 1 and gap < 1200)
                r["free"][sector] += 1
            if sector < 3 and "inner" in s and 0 <= time - s["inner"][0] <= 1:
                r["temp"].setdefault(sector, s["inner"][1])
            r["missing_gap"] += not gap and b[p+32] > 1
            r["invalid"] |= bool(b[p+37])
            if b[p+46]:
                r["lane_sectors"].add(b[p+36])
            r["pit"] |= bool(b[p+34] or b[p+46])
            r["lane_ms"] = max(r["lane_ms"], struct.unpack_from("<H", b, p+47)[0] if b[p+46] else 0)
            r["service_ms"] = max(r["service_ms"], struct.unpack_from("<H", b, p+49)[0] if b[p+46] else 0)
            r["control"].add(s.get("control"))
            r["weather"].add(s.get("weather"))
            r["sectors"].add(b[p+36])
            dist = struct.unpack_from("<f", b, p+20)[0]
            if not r["distance"]:
                r["distance"] = [dist, dist]
            r["distance"] = [min(r["distance"][0], dist), max(r["distance"][1], dist)]
            if "damage" in s and 0 <= time-s["damage"][0] <= 2:
                r["wing"].add(s["damage"][1])
            if "tyre" in s and 0 <= time-s["tyre"][0] <= 1:
                _, compound, age, _ = s["tyre"]
                r["compounds"][compound] += 1
                r["age"][age] += 1
                if len(r["fuel"]) < 1:
                    r["fuel"].append(s["fuel_kg"])
    result = []
    for uid, s in sessions.items():
        if not s["laps"]:
            continue
        history = s["history"]
        records = []
        for i,r in sorted(s["laps"].items()):
            if i > history.get("num_laps", 0):
                continue
            h = history["lap_history_data"][i-1]
            if h["lap_time_ms"] <= 0:
                continue
            records.append(dict(lap=i, seconds=h["lap_time_ms"]/1000, valid=h["lap_valid_bit_flags"],
                splits=[h[f"sector{k}_time_ms_part"]/1000+60*h[f"sector{k}_time_minutes"] for k in (1,2,3)],
                compound=max(r["compounds"], key=r["compounds"].get, default=None),
                age=max(r["age"], key=r["age"].get, default=None), fuel=next(iter(r["fuel"]),None),
                traffic=round(r["traffic"]/r["samples"],3), missing_gap=round(r["missing_gap"]/r["samples"],3),
                invalid=r["invalid"], incident=r["incident"], pit=r["pit"], wing=sorted(r["wing"]),
                near=r["near"], free=r["free"], lane_sectors=sorted(r["lane_sectors"]), hits=sorted(r["hits"]), temp=r["temp"], lane_ms=r["lane_ms"], service_ms=r["service_ms"], weather=sorted(r["weather"]),
                control=sorted(r["control"]), distance=r["distance"], sectors=sorted(r["sectors"])))
        result.append(dict(uid=uid,track=s.get("track"),length=s.get("length"),length_code=s.get("length_code"),
                           track_m=s.get("track_m"),start=s["start"],rewind=s["rewind"],spectator=s["spectator"],
                           rewound_laps=sorted(s["rewound_laps"]),final=s["final"], source=str(path.relative_to(ROOT)), local=path.suffix==".jsonl",
                           stints=history.get("tyre_stints_history_data",[])[:history.get("num_tyre_stints",0)],
                           records=records))
    return dict(source=str(path.relative_to(ROOT)), races=result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    files = sorted((ROOT/"tools/captures").glob("*.jsonl"))
    files += sorted((ROOT/"asurada-core/data/capture_samples").glob("f1_25_udp_capture*/f1_25_udp_capture*.jsonl"))
    files += sorted((ROOT/"asurada-core/runtime_logs").glob("live_udp_capture*.jsonl"))
    files += sorted((ROOT/"output/user-acceptance/current").glob("capture*.jsonl"))
    files += sorted((COMMUNITY/"raw").glob("*.gz"))
    files += sorted((COMMUNITY/"search-round2/candidates").rglob("*.f1bin"))
    files += sorted((COMMUNITY/"search-round2/candidates").rglob("*.bin"))
    with ProcessPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(read_file,files))
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=1))


if __name__ == "__main__":
    main()

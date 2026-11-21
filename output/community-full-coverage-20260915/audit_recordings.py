"""Read-only structural/field audit. No replay, strategy, or training is executed."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO/'asurada-core/src'))
from asurada.pdu_decoder import F125PacketDecoder

HEADER = struct.Struct('<HBBBBBQfIIBB')
DECODER = F125PacketDecoder()
REQUIRED = {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13}

def packets(path, container=None):
    if container is None:
        container = {}
    with gzip.open(path, 'rb') as src:
        first = src.read(12)
        if len(first) != 12:
            raise ValueError('truncated_container_header')
        magic, flags, version, declared = struct.unpack('<6sBBI', first)
        container.update(declared_packets=declared, version=f'{(version >> 4) & 7}.{version & 15}', internally_compressed=bool(flags & 1))
        if magic != b'F1UDP\0' or (version >> 4) & 7 != 1 or flags & ~1:
            raise ValueError('unsupported_container_header')
        endian = '<' if version & 128 else '>'
        count = 0
        while True:
            h = src.read(8)
            if not h:
                break
            if len(h) != 8:
                raise ValueError('truncated_record_header')
            timestamp, size = struct.unpack(endian+'fI', h)
            if not 0 < size <= 65536:
                raise ValueError('invalid_record_size')
            payload = src.read(size)
            if len(payload) != size:
                raise ValueError('truncated_record_payload')
            if flags & 1:
                decompressor = zlib.decompressobj()
                payload = decompressor.decompress(payload, 65537)
                if len(payload) > 65536 or not decompressor.eof or decompressor.unused_data:
                    raise ValueError('invalid_compressed_packet')
            count += 1
            yield timestamp, payload
        container.update(actual_packets=count, packet_count_matches=(count == declared))

def track_field(session, name, value, low=None, high=None):
    stats = session['fields'].setdefault(name, {'observations':0, 'invalid':0, 'min':None, 'max':None, 'nonzero':0})
    stats['observations'] += 1
    if not isinstance(value, (int,float)) or not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        stats['invalid'] += 1
        return
    stats['min'] = value if stats['min'] is None else min(stats['min'], value)
    stats['max'] = value if stats['max'] is None else max(stats['max'], value)
    stats['nonzero'] += int(value != 0)

def audit(path):
    sessions = {}
    formats = Counter()
    decode_errors = Counter()
    packet_lengths = Counter()
    total = 0
    container = {}
    for received, payload in packets(path, container):
        total += 1
        if len(payload) < HEADER.size:
            decode_errors['short_game_header'] += 1
            continue
        fmt, year, major, minor, pv, pid, uid, seconds, frame, overall, player, secondary = HEADER.unpack_from(payload)
        formats[f'{fmt}/{year}'] += 1
        packet_lengths[f'{fmt}:{pid}:{pv}:{len(payload)}'] += 1
        s = sessions.setdefault(str(uid), {'packet_counts':Counter(), 'track_ids':set(), 'session_types':set(),
            'weather':set(), 'spectating':set(), 'player_indices':set(), 'events':Counter(), 'fields':{},
            'first_session_time':None, 'last_session_time':None, 'min_time':None, 'max_time':None,
            'time_reversals_by_packet':Counter(), 'max_positive_gap_by_packet':{}, 'last_times':{},
            'container_timestamp_min':received, 'container_timestamp_max':received,
            'body_parse_failures':Counter(), 'body_parse_observations':Counter()})
        s['packet_counts'][pid] += 1
        s['player_indices'].add(player)
        s['container_timestamp_min'] = min(s['container_timestamp_min'], received)
        s['container_timestamp_max'] = max(s['container_timestamp_max'], received)
        if math.isfinite(seconds):
            if s['first_session_time'] is None:
                s['first_session_time'] = seconds
            s['last_session_time'] = seconds
            s['min_time'] = seconds if s['min_time'] is None else min(s['min_time'], seconds)
            s['max_time'] = seconds if s['max_time'] is None else max(s['max_time'], seconds)
            previous = s['last_times'].get(pid)
            if previous is not None:
                delta = seconds - previous
                if delta < -0.1:
                    s['time_reversals_by_packet'][pid] += 1
                s['max_positive_gap_by_packet'][pid] = max(s['max_positive_gap_by_packet'].get(pid,0),delta)
            s['last_times'][pid] = seconds
        if fmt != 2025 or year != 25:
            continue
        try:
            if pid == 1:
                v = struct.unpack_from(DECODER.SESSION_PREFIX_FORMAT, payload, HEADER.size)
                s['track_ids'].add(v[6]); s['session_types'].add(v[5]); s['weather'].add(v[0])
                s['spectating'].add(v[12])
                track_field(s,'scheduled_laps',v[3],0,255)
            elif pid == 3:
                s['events'][payload[29:33].decode('ascii',errors='replace')] += 1
            elif player < 22 and pid == 2:
                body = DECODER._decode_lap_data_car(payload,player)
                for key,low,high in [('current_lap_num',0,255),('lap_distance_m',None,None),('delta_to_car_in_front_ms',0,None),('pit_status',0,2),('num_pit_stops',0,255),('result_status',0,7)]:
                    track_field(s,key,body[key],low,high)
            elif player < 22 and pid == 6:
                v = struct.unpack_from(DECODER.CAR_TELEMETRY_FORMAT,payload,29+player*DECODER.CAR_TELEMETRY_SIZE)
                for key,value,low,high in [('speed_kph',v[0],0,450),('throttle',v[1],0,1),('steer',v[2],-1,1),('brake',v[3],0,1),('gear',v[5],-1,8)]:
                    track_field(s,key,value,low,high)
            elif player < 22 and pid == 7:
                v = struct.unpack_from(DECODER.CAR_STATUS_FORMAT,payload,29+player*DECODER.CAR_STATUS_SIZE)
                for key,value,low,high in [('fuel_in_tank',v[5],0,200),('fuel_remaining_laps',v[7],None,None),('ers_store_energy',v[19],0,4100000),('tyres_age_laps',v[15],0,255)]:
                    track_field(s,key,value,low,high)
            elif player < 22 and pid == 10:
                body = DECODER._decode_car_damage_car(payload,player)
                for i,value in enumerate(body['tyres_wear_pct']):
                    track_field(s,'tyre_wear_'+str(i),value,0,100)
            elif player < 22 and pid == 0:
                body=DECODER._decode_motion_car(payload,player)
                for key,value in body['g_force'].items():
                    track_field(s,'g_'+key,value,-100,100)
            elif pid == 13:
                body=DECODER._decode_motion_ex(payload)
                for i,value in enumerate(body['wheel_slip_ratio']):
                    track_field(s,'wheel_slip_ratio_'+str(i),value)
            s['body_parse_observations'][pid] += 1
        except (ValueError,IndexError,KeyError,struct.error) as exc:
            s['body_parse_failures'][pid] += 1
            decode_errors[f'{pid}:{type(exc).__name__}'] += 1
    for s in sessions.values():
        s.pop('last_times')
        for key in ['track_ids','session_types','weather','spectating','player_indices']:
            s[key] = sorted(s[key])
        present=set(s['packet_counts'])
        s['missing_required_packet_types']=[DECODER.PACKET_ID_NAMES[x] for x in sorted(REQUIRED-present)]
        s['all_required_packet_types_present']=not s['missing_required_packet_types']
        # Structural presence and numeric ranges alone do not prove complete training coverage.
        s['complete_training_data_verified']=False
    return {'audit_version':2, 'file':path.name,'packets':total,'container_integrity':'passed' if container['packet_count_matches'] else 'source_header_count_mismatch', 'container':container, 'formats':formats,
            'packet_length_variants':packet_lengths, 'parse_errors':decode_errors,'sessions':sessions,
            'scope':'All container records and common headers checked; selected player fields checked using current Asurada decoder. No per-frame joint completeness, rival privacy, or label acceptance claimed.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw-dir',type=Path,default=ROOT/'raw')
    args=parser.parse_args();out=ROOT/'audits';out.mkdir(exist_ok=True)
    for path in sorted(args.raw_dir.glob('*.f1pcap.gz')):
        dest=out/(path.name+'.json')
        if dest.exists() and json.loads(dest.read_text()).get('audit_version') == 2:
            continue
        try:
            result=audit(path)
        except Exception as exc:
            result={'file':path.name,'container_integrity':'failed','error':str(exc)}
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'file':path.name,'integrity':result['container_integrity'],'packets':result.get('packets'),
                          'tracks':sorted({t for s in result.get('sessions',{}).values() for t in s['track_ids']}),
                          'errors':result.get('parse_errors',result.get('error'))}),flush=True)

if __name__=='__main__':
    main()

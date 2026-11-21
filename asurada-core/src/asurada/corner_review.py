"""Distance-aligned segment timing from observed lap clocks, with coverage gates."""
from collections import defaultdict
import hashlib
import json
import math

from .track_model import load_track_profile
from .race_control import normalize_race_control


def number(value):
    return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def review_segments(data, *, completed_laps, context, max_gap_ms=500, max_gap_m=50):
    digest=hashlib.sha256(data).hexdigest()
    completed={(lap['session_uid'],lap['epoch'],lap['lap']) for lap in completed_laps}
    eligible_samples=0
    groups=defaultdict(list)
    rejected=defaultdict(int)
    for line_number,line in enumerate(data.splitlines(),1):
        context.remaining()
        if not line.strip():continue
        row=json.loads(line);raw=row.get('raw') or {};player=row.get('player') or {}
        if raw.get('result_status')==3 or raw.get('review_exclude_reason') == 'official_finish_transition':
            continue  # Post-finish clock resets are not another traversal of the lap.
        key=(str(row.get('session_uid')),int(row.get('session_epoch',0)),int(row.get('lap_number') or 0))
        if key not in completed:continue
        eligible_samples+=1
        distance=number(raw.get('lap_distance_m',player.get('lap_distance_m')))
        clock=number(raw.get('current_lap_time_ms'))
        speed=number(player.get('speed_kph'))
        if distance is None or distance<0 or clock is None or clock<0 or speed is None or speed<0:
            rejected['missing_distance_clock_or_speed']+=1;continue
        conditions=(row.get('weather'),(player.get('tyre') or {}).get('compound'),
                    normalize_race_control(row.get('safety_car')))
        invalid=bool(raw.get('current_lap_invalid')) or raw.get('pit_status') in {'PITTING','IN_PIT_AREA'}
        groups[(*key,row.get('track'))].append(dict(d=distance,t=clock,speed=speed,line=line_number,
            conditions=conditions,invalid=invalid))
    segments=[]
    for key,points in groups.items():
        context.remaining()
        profile=load_track_profile(key[3] or '')
        if profile is None:
            rejected['unknown_track']+=1;continue
        if any(p['invalid'] for p in points) or len({p['conditions'] for p in points}) != 1:
            rejected['lap_condition_change_or_invalid']+=1;continue
        conditions=points[0]['conditions']
        if None in conditions or conditions[2]!='NONE':
            rejected['uncontrolled_or_unknown_conditions']+=1;continue
        # Preserve source order. Repeated samples may be dropped; a backwards
        # clock/distance without a new epoch invalidates the lap.
        clean=[];bad=False
        for point in points:
            if clean and (point['d'],point['t'])==(clean[-1]['d'],clean[-1]['t']):continue
            if clean and (point['d']<=clean[-1]['d'] or point['t']<=clean[-1]['t']):
                bad=True;break
            clean.append(point)
        if bad:
            rejected['nonmonotonic_lap']+=1;continue
        for segment in profile.semantic_segments:
            if segment.zone_type=='deployment_straight':continue
            start,end=segment.start_m,segment.end_m
            crossing=[]
            relevant=[]
            valid=True
            for left,right in zip(clean,clean[1:]):
                if right['d']<start or left['d']>end:continue
                if right['t']-left['t']>max_gap_ms or right['d']-left['d']>max_gap_m:
                    valid=False;break
                relevant.extend([left,right])
                for boundary in (start,end):
                    if left['d']<=boundary<right['d']:
                        t=left['t']+(boundary-left['d'])/(right['d']-left['d'])*(right['t']-left['t'])
                        crossing.append((boundary,t))
            crossings=dict(crossing)
            if not valid or start not in crossings or end not in crossings:
                rejected['segment_incomplete_or_gap']+=1;continue
            inside=[p for p in relevant if start<=p['d']<=end]
            if len({p['line'] for p in inside})<3:
                rejected['segment_too_few_samples']+=1;continue
            segments.append(dict(session_uid=key[0],epoch=key[1],lap=key[2],track=key[3],segment=segment.name,
                zone_type=segment.zone_type,start_m=start,end_m=end,
                duration_ms=round(crossings[end]-crossings[start],3),min_speed_kph=min(p['speed'] for p in inside),
                conditions=list(conditions),evidence=dict(source_sha256=digest,first_line=min(p['line'] for p in relevant),
                last_line=max(p['line'] for p in relevant),timing='interpolated_current_lap_time_ms')))
    comparisons=[];by_segment=defaultdict(list)
    for segment in segments:
        by_segment[(segment['session_uid'],segment['epoch'],segment['track'],segment['segment'],tuple(segment['conditions']))].append(segment)
    for key,values in by_segment.items():
        recent=sorted(values,key=lambda item:item['lap'])[-3:]
        if len(recent)<2:continue
        comparisons.append(dict(session_uid=key[0],epoch=key[1],track=key[2],segment=key[3],laps=recent,
            change_ms=round(recent[-1]['duration_ms']-recent[0]['duration_ms'],3),
            interpretation='observed_segment_time_change_not_causal_diagnosis'))
    if not eligible_samples:
        rejected['missing_completed_lap_telemetry']+=1
    return dict(version='segment-review-v1',source_sha256=digest,segments=segments,comparisons=comparisons,
                availability='available' if comparisons else 'insufficient_comparable_evidence',
                completed_lap_count=len(completed),eligible_samples=eligible_samples,
                rejected=dict(rejected),quality_policy=dict(max_gap_ms=max_gap_ms,max_gap_m=max_gap_m,min_samples=3),
                limitation='赛道区段边界来自本地语义图；区段耗时为插值估计，未控制交通、燃油、轮胎磨损等因素，不证明驾驶动作因果。')

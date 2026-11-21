"""Rank comparable measured segments, preserving missing-data reasons."""
from copy import deepcopy
import math
from .history import INPUT_SCHEMA as LAP_INPUT, validate_lap_arguments, completed_review, SCOPE_SCHEMA, REFERENCE_SCHEMA

INPUT_SCHEMA=deepcopy(LAP_INPUT)
INPUT_SCHEMA['properties']['top_k']={'type':'integer','minimum':1,'maximum':20,'default':5}
COMPARISON_SCHEMA={'type':'object',
    'required':['segment','lap_numbers','durations_ms','spread_ms','delta_ms','conditions','start_m','end_m','evidence'],
    'properties':{'segment':{'type':'string','minLength':1},
        'lap_numbers':{'type':'array','minItems':2,'maxItems':10,'uniqueItems':True,'items':{'type':'integer','minimum':1}},
        'durations_ms':{'type':'array','minItems':2,'maxItems':10,'items':{'type':'number','exclusiveMinimum':0}},
        'spread_ms':{'type':'number','minimum':0},'delta_ms':{'type':'number'},
        'conditions':{'type':'array','minItems':1},'start_m':{'type':'number','minimum':0},
        'end_m':{'type':'number','exclusiveMinimum':0},
        'evidence':{'type':'array','minItems':2,'maxItems':10,'items':REFERENCE_SCHEMA}}}
OUTPUT_SCHEMA={'type':'object','required':['scope','status','comparisons','excluded','unit','interpretation','eligible_segment_count'],
    'properties':{'scope':SCOPE_SCHEMA,'status':{'enum':['compared','insufficient_data']},
        'comparisons':{'type':'array','maxItems':20,'items':COMPARISON_SCHEMA},'excluded':{'type':'object'},
        'eligible_segment_count':{'type':'integer','minimum':0},'unit':{'const':'ms'},
        'interpretation':{'const':'observed_segment_spread_not_causal_diagnosis'}}}


def compare_segments(*,query_kind,state,arguments,review_store,driver_id,context):
    if not isinstance(arguments,dict):raise ValueError('invalid_segment_arguments')
    args=dict(arguments);top=args.pop('top_k',5)
    if isinstance(top,bool) or not isinstance(top,int) or not 1<=top<=20:raise ValueError('invalid_top_k')
    task_id,numbers=validate_lap_arguments(args)
    task=completed_review(review_store,driver_id,task_id,context)
    reviews=[r['result'] for r in task['results'] if r['step']=='analyze_segments']
    if len(reviews)!=1:raise ValueError('segment_review_unavailable')
    review=reviews[0];scope={'session_uid':state.session_uid,'epoch':state.session_epoch,'track':state.track}
    groups={}
    for row in review['segments']:
        context.remaining()
        if any(row.get(k)!=v for k,v in scope.items()) or row.get('lap') not in numbers:continue
        groups.setdefault(row['segment'],[]).append(row)
    comparisons=[];excluded={}
    for name,rows in groups.items():
        context.remaining()
        if len(rows)!=len(numbers) or {r['lap'] for r in rows}!=set(numbers):
            excluded[name]='missing_or_duplicate_lap';continue
        if any(any(r[k]!=rows[0][k] for k in ('conditions','start_m','end_m')) for r in rows):
            excluded[name]='conditions_or_distance_differ';continue
        if any(isinstance(r['duration_ms'],bool) or not isinstance(r['duration_ms'],(int,float)) or not math.isfinite(r['duration_ms']) or r['duration_ms']<=0 or r.get('evidence',{}).get('source_sha256')!=review.get('source_sha256') or not review.get('source_sha256') for r in rows):
            raise ValueError('invalid_segment_evidence')
        ordered=[next(r for r in rows if r['lap']==n) for n in numbers]
        durations=[r['duration_ms'] for r in ordered]
        comparisons.append({'segment':name,'lap_numbers':list(numbers),'durations_ms':durations,
            'spread_ms':round(max(durations)-min(durations),3),'delta_ms':round(durations[-1]-durations[0],3),
            'conditions':deepcopy(rows[0]['conditions']),'start_m':rows[0]['start_m'],'end_m':rows[0]['end_m'],
            'evidence':[{'review_task_id':task_id,'lap':r['lap'],**deepcopy(r['evidence'])} for r in ordered]})
    comparisons.sort(key=lambda r:(-r['spread_ms'],r['segment']))
    return {'scope':scope,'status':'compared' if comparisons else 'insufficient_data','comparisons':comparisons[:top],
            'excluded':excluded,'eligible_segment_count':len(comparisons),'unit':'ms',
            'interpretation':'observed_segment_spread_not_causal_diagnosis'}

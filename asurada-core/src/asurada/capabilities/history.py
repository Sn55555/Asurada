"""Structured comparisons from completed, owner-scoped review checkpoints."""
import math
from copy import deepcopy
from dataclasses import dataclass, asdict
import hashlib
import json


@dataclass(frozen=True)
class ReviewScope:
    session_uid: str
    session_epoch: int
    track: str

    def __post_init__(self):
        if not isinstance(self.session_uid,str) or not self.session_uid.strip() or not isinstance(self.track,str) or not self.track.strip() or isinstance(self.session_epoch,bool) or not isinstance(self.session_epoch,int) or self.session_epoch<0:
            raise ValueError('invalid_review_scope')

    @classmethod
    def from_payload(cls,payload):
        return cls(payload.get('session_uid'),payload.get('session_epoch'),payload.get('track'))

    def identity(self):
        return 'review-scope-v1:'+hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':')).encode()).hexdigest()

INPUT_SCHEMA={'type':'object','required':['review_task_id','lap_numbers'],'additionalProperties':False,
    'properties':{'review_task_id':{'type':'string','minLength':1,'maxLength':200},
                  'lap_numbers':{'type':'array','minItems':2,'maxItems':10,'uniqueItems':True,'items':{'type':'integer','minimum':1}}}}
SCOPE_SCHEMA={'type':'object','required':['session_uid','epoch','track'],
    'properties':{'session_uid':{'type':'string','minLength':1},'epoch':{'type':'integer','minimum':0},
                  'track':{'type':'string','minLength':1}}}
EVIDENCE_SCHEMA={'type':'object','required':['source_sha256'],
    'properties':{'source_sha256':{'type':'string','minLength':1}}}
REFERENCE_SCHEMA={'type':'object','required':['review_task_id','lap','source_sha256'],
    'properties':{**EVIDENCE_SCHEMA['properties'],'review_task_id':{'type':'string','minLength':1},
                  'lap':{'type':'integer','minimum':1}}}
LAP_SCHEMA={'type':'object','required':['session_uid','epoch','track','lap','time_ms','evidence'],
    'properties':{**SCOPE_SCHEMA['properties'],'lap':{'type':'integer','minimum':1},
                  'time_ms':{'type':'number','exclusiveMinimum':0},'evidence':EVIDENCE_SCHEMA}}
OUTPUT_SCHEMA={'type':'object','required':['scope','laps','delta_ms','unit','evidence','interpretation'],
    'properties':{'scope':SCOPE_SCHEMA,'laps':{'type':'array','minItems':2,'maxItems':10,'items':LAP_SCHEMA},
                  'delta_ms':{'type':'number'},'unit':{'const':'ms'},
                  'evidence':{'type':'array','minItems':2,'maxItems':10,'items':REFERENCE_SCHEMA},
                  'interpretation':{'const':'observed_lap_time_difference_not_causal_effect'}}}


def validate_lap_arguments(arguments):
    if not isinstance(arguments,dict) or set(arguments)!={'review_task_id','lap_numbers'}:
        raise ValueError('invalid_lap_comparison_arguments')
    task_id=arguments['review_task_id'];numbers=arguments['lap_numbers']
    if not isinstance(task_id,str) or not 0<len(task_id.strip())<=200:
        raise ValueError('invalid_review_task_id')
    if not isinstance(numbers,list) or not 2<=len(numbers)<=10 or any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in numbers) or len(set(numbers))!=len(numbers):
        raise ValueError('invalid_lap_numbers')
    return task_id,numbers


def completed_review(review_store,driver_id,task_id,context):
    if review_store is None or not isinstance(driver_id,str) or not driver_id:
        raise ValueError('review_context_required')
    context.remaining();task=review_store.get(task_id);context.remaining()
    if task['request'].get('driver_id')!=driver_id:raise PermissionError('review_owner_mismatch')
    if task['status']!='completed':raise ValueError('review_not_completed')
    return task


def compare_laps(*,query_kind,state,arguments,review_store,driver_id,context):
    task_id,numbers=validate_lap_arguments(arguments)
    task=completed_review(review_store,driver_id,task_id,context)
    indexed=[r['result'] for r in task['results'] if r['step']=='index_official_laps']
    if len(indexed)!=1:raise ValueError('review_lap_index_unavailable')
    scope={'session_uid':state.session_uid,'epoch':state.session_epoch,'track':state.track}
    matched={}
    for lap in indexed[0]:
        context.remaining()
        if any(lap.get(k)!=v for k,v in scope.items()) or lap.get('lap') not in numbers:continue
        number=lap['lap'];duration=lap.get('time_ms');evidence=lap.get('evidence')
        if number in matched or isinstance(duration,bool) or not isinstance(duration,(float,int)) or not math.isfinite(duration) or duration<=0 or not isinstance(evidence,dict) or not evidence.get('source_sha256'):
            raise ValueError('invalid_official_lap_evidence')
        matched[number]=deepcopy(lap)
    if set(matched)!=set(numbers):raise ValueError('requested_laps_unavailable_in_scope')
    laps=[matched[n] for n in numbers]
    return {'scope':scope,'laps':laps,'delta_ms':laps[-1]['time_ms']-laps[0]['time_ms'],'unit':'ms',
        'evidence':[{'review_task_id':task_id,'lap':lap['lap'],**lap['evidence']} for lap in laps],
        'interpretation':'observed_lap_time_difference_not_causal_effect'}

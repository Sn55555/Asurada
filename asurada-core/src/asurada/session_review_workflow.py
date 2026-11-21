"""Evidence-bound initial review workflow; completed official laps only."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from .workflow_store import WorkflowStore
from .training_memory import TrainingMemory
from .corner_review import review_segments
from .training_plans import TrainingPlanStore
from .review_capture import file_digest, project_capture_cached, PROJECTION_VERSION
from .task_runtime import TaskContext


def run_session_review(store: WorkflowStore, *, task_id: str, source: Path, driver_id: str = "local-driver", memory: TrainingMemory | None = None, capture_directory: Path | None = None, timeout_s: float = 300):
    if isinstance(timeout_s,bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError('review_timeout_must_be_finite_positive')
    setup=TaskContext.start(task_id,timeout_s*1000)
    memory = memory or TrainingMemory(store.path.with_suffix(".memory.sqlite3"))
    plans = TrainingPlanStore(store.path.with_suffix(".training.sqlite3"))
    digest=file_digest(source,setup)
    request={'version':'session-review-v7','driver_id':driver_id,'memory_path':str(memory.path.resolve()),'training_path':str(plans.path.resolve()),'source':str(source.resolve()),'sha256':digest,
             'steps':['index_official_laps','compare_recent_laps','analyze_segments','persist_session_facts','training_followup','review_report']}
    if capture_directory is not None:
        request.update(capture_directory=str(capture_directory.resolve()),projection_version=PROJECTION_VERSION)
        request['steps'].insert(0,'project_capture')
    store.create(task_id,request,timeout_s=setup.remaining())
    def value(results,name):
        return next(item['result'] for item in results if item['step']==name)
    def input_ref(request,results):
        if 'capture_directory' in request:
            projection=value(results,'project_capture')
            return Path(projection['projection']),projection['projection_sha256']
        return Path(request['source']),request['sha256']
    def input_data(request,results,context):
        path,expected=input_ref(request,results)
        context.remaining()
        data=path.read_bytes()
        context.remaining()
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('review_input_changed')
        return data,expected
    def project(request,results,context):
        directory=Path(request['capture_directory'])
        projected=project_capture_cached(Path(request['source']),directory/'review-snapshots.jsonl',directory/'projection.json',context=context)
        if projected['capture_sha256']!=request['sha256']:raise ValueError('review_input_changed')
        return projected
    def index(request,results,context):
        data,projection_digest=input_data(request,results,context)
        laps={}
        for line in data.splitlines():
            context.remaining()
            if not line.strip():continue
            row=json.loads(line);raw=row.get('raw') or {}
            if raw.get('review_exclude_reason') == 'official_finish_transition':continue
            # F1 packet contract: result_status=3 is finished. At the flag the
            # lap counter can stay on the final lap while last_lap_time updates.
            lap=int(row.get('lap_number') or 0)-(0 if raw.get('result_status')==3 else 1)
            duration=raw.get('last_lap_time_ms')
            if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not 0<duration<3600000 or lap<1:continue
            key=(str(row['session_uid']),int(row.get('session_epoch',0)),lap)
            record={'session_uid':key[0],'epoch':key[1],'lap':lap,'time_ms':duration,'track':row['track'],
                    'evidence':{'source_sha256':projection_digest,'source_timestamp_ms':row['source_timestamp_ms']}}
            if key in laps and laps[key]['time_ms']!=duration:raise ValueError('conflicting_official_lap_time')
            laps[key]=record
        return list(laps.values())
    def compare(request,results,context):
        groups={}
        for lap in value(results,'index_official_laps'):groups.setdefault((lap['session_uid'],lap['epoch']),[]).append(lap)
        comparisons=[]
        for key,values in groups.items():
            recent=sorted(values,key=lambda item:item['lap'])[-3:]
            comparisons.append({'session_uid':key[0],'epoch':key[1],'laps':recent,
                                'change_ms':recent[-1]['time_ms']-recent[0]['time_ms'] if len(recent)>=2 else None})
        return comparisons
    def segments(request,results,context):
        data,_=input_data(request,results,context)
        return review_segments(data,completed_laps=value(results,'index_official_laps'),context=context)
    def persist(request,results,context):
        ids=[]
        for lap in value(results,'index_official_laps'):
            context.remaining()
            ids.append(memory.put(driver=request['driver_id'],kind='session_fact',
                key=f"{lap['evidence']['source_sha256']}:official-lap:{lap['lap']}",
                value={'track':lap['track'],'lap':lap['lap'],'time_ms':lap['time_ms']},
                evidence=[lap['evidence']], session_uid=lap['session_uid'],epoch=lap['epoch'],
                ttl_s=30*86400,context=context))
        return {'memory_ids':ids,'kind':'session_fact','driver_id':request['driver_id']}
    def followup(request,results,context):
        return plans.process_review(driver=request['driver_id'],review=value(results,'analyze_segments'),context=context)
    def report(request,results,context):
        return {'report_version':'session-review-v7','memory':value(results,'persist_session_facts'),'segment_review':value(results,'analyze_segments'),'source_sha256':input_ref(request,results)[1],'capture_provenance':value(results,'project_capture') if 'capture_directory' in request else None,'comparisons':value(results,'compare_recent_laps'),
                'training_recommendation':value(results,'training_followup')['draft'],'training_outcomes':value(results,'training_followup')['outcomes'],
                'limitation':'训练重点为待启用的稳定性练习草稿；后续圈比较仅记录观测变化，不证明驾驶动作因果或训练效果。'}
    steps=(('index_official_laps',index),('compare_recent_laps',compare),('analyze_segments',segments),('persist_session_facts',persist),('training_followup',followup),('review_report',report))
    if capture_directory is not None:steps=(('project_capture',project),)+steps
    return store.run(task_id,steps)

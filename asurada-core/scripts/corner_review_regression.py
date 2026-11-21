import json
from pathlib import Path
from tempfile import TemporaryDirectory
from regression_support import emit_result
from asurada.corner_review import review_segments
from asurada.task_runtime import TaskContext
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore
from asurada.training_plans import choose_focus


def rows():
    result=[]
    for lap,factor in [(1,10),(2,11),(3,12)]:
        for distance in range(75,276,25):
            result.append(dict(session_uid='s',session_epoch=0,lap_number=lap,track='Suzuka',weather='Clear',safety_car='NONE',
                source_timestamp_ms=lap*10000+distance,player={'speed_kph':100,'tyre':{'compound':'C3'}},
                raw={'lap_distance_m':distance,'current_lap_time_ms':distance*factor,'last_lap_time_ms':100000 if lap>1 else None}))
    result.append(dict(session_uid='s',session_epoch=0,lap_number=4,track='Suzuka',source_timestamp_ms=50000,raw={'last_lap_time_ms':100000}))
    return result


def analyze(values):
    data='\n'.join(json.dumps(row) for row in values).encode()
    return review_segments(data,completed_laps=[{'session_uid':'s','epoch':0,'lap':lap} for lap in (1,2,3)],context=TaskContext.start('test',1000))


def run():
    values=rows();report=analyze(values)
    apex=next(c for c in report['comparisons'] if c['segment']=='T1 Apex')
    checks={'distance_aligned_time_delta':apex['change_ms']==200 and len(apex['laps'])==3,
            'evidence_has_source_and_lines':all(l['evidence']['source_sha256'] and l['evidence']['last_line']>=l['evidence']['first_line'] for l in apex['laps'])}
    missing=[r for r in values if r.get('raw',{}).get('lap_distance_m')!=200]
    # The remaining 50m gap exceeds 500ms on laps 2/3 and is rejected.
    checks['missing_coverage_not_compared']=not any(c['segment']=='T1 Apex' for c in analyze(missing)['comparisons'])
    rewound=rows();rewound[3]['raw']['current_lap_time_ms']=1
    checks['nonmonotonic_lap_excluded']=all(s['lap']!=1 for s in analyze(rewound)['segments'])
    changed=rows()
    for row in changed:
        if row['lap_number']==3:row['weather']='HeavyRain'
    checks['weather_not_mixed']=all(len(c['laps'])==2 for c in analyze(changed)['comparisons'])
    for index, control in enumerate((None, 'UNKNOWN', True, 99, {}, [], 'FULL', 'VSC', 'FORMATION')):
        unknown=rows()
        for row in unknown:row['safety_car']=control
        rejected=analyze(unknown)
        checks[f'non_green_conditions_rejected_{index}']=(
            not rejected['segments'] and not rejected['comparisons'] and choose_focus(rejected) is None
            and rejected['rejected'].get('uncontrolled_or_unknown_conditions')==3)
    unknown=rows();unknown[0]['safety_car']={}
    partial=analyze(unknown)
    checks['one_unknown_sample_invalidates_whole_lap']=(
        all(s['lap']!=1 for s in partial['segments'])
        and any(s['lap']==2 for s in partial['segments']) and choose_focus(partial) is None)
    finished=rows()[:-1]
    finished.append(dict(session_uid='s',session_epoch=0,lap_number=3,track='Suzuka',
        source_timestamp_ms=50000,weather='Clear',safety_car='NONE',
        player={'speed_kph':100,'tyre':{'compound':'C3'}},
        raw={'result_status':3,'lap_distance_m':0,'current_lap_time_ms':0,'last_lap_time_ms':99000}))
    checks['post_finish_clock_reset_preserves_final_segments']=any(
        s['lap']==3 and s['segment']=='T1 Apex' for s in analyze(finished)['segments'])
    with TemporaryDirectory() as temp:
        root=Path(temp);source=root/'session.jsonl'
        source.write_text('\n'.join(json.dumps(row) for row in values))
        result=run_session_review(WorkflowStore(root/'tasks.db'),task_id='corners-v3',source=source)
        final=result['results'][-1]['result']
        checks['production_workflow_contains_segment_evidence']=result['status']=='completed' and any(c['segment']=='T1 Apex' for c in final['segment_review']['comparisons'])
        checks['no_causal_training_claim']=final['training_recommendation']['version']=='segment-consistency-v1' and '单圈结果不证明训练效果' in final['training_recommendation']['limitation']
        source.write_text('\n'.join(json.dumps(row) for row in finished))
        finished_result=run_session_review(WorkflowStore(root/'tasks.db'),task_id='finished-v4',source=source)
        checks['final_lap_counter_stays_on_completed_lap']={
            lap['lap']:lap['time_ms'] for lap in finished_result['results'][0]['result']
        }=={1:100000,2:100000,3:99000}
        conflicting=rows()
        conflicting[10]['raw']['last_lap_time_ms']=99000
        source.write_text('\n'.join(json.dumps(row) for row in conflicting))
        task_store=WorkflowStore(root/'tasks.db')
        try:
            run_session_review(task_store,task_id='conflict-v4',source=source)
            checks['genuine_lap_time_conflict_rejected']=False
        except ValueError as error:
            checks['genuine_lap_time_conflict_rejected']=str(error)=='conflicting_official_lap_time' and task_store.get('conflict-v4')['status']=='failed'
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

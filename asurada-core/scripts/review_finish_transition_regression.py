import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from asurada.review_capture import project_capture
from asurada.task_runtime import TaskContext
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore
from regression_support import emit_result


def run():
    checks={}
    # Same lap counter and updated last-lap time arrive before result_status=3.
    rows=[dict(session_uid='finish',session_epoch=0,track='Shanghai',lap_number=5,source_timestamp_ms=t,weather='LightCloud',safety_car='NONE',player=SimpleNamespace(speed_kph=100,tyre=SimpleNamespace(compound='Intermediate')),raw=dict(lap_distance_m=10,current_lap_time_ms=clock,last_lap_time_ms=duration,result_status=2,session_time_s=t/1000)) for t,clock,duration in [(1000,10000,111160),(1990,0,110218)]]
    envelopes=[SimpleNamespace(kind='Motion',payload={'body':{},'header':{}},session_uid='finish') for _ in rows]
    envelopes.append(SimpleNamespace(kind='LapData',session_uid='finish',payload={'header':{'session_time_s':2},'body':{'result_status':3,'current_lap_num':5,'last_lap_time_ms':110218,'current_lap_time_ms':30,'lap_distance_m':4}}))
    with TemporaryDirectory() as tmp:
        root=Path(tmp);source=root/'raw.jsonl';source.write_text('fixed input');dest=root/'projection.jsonl'
        packets=[SimpleNamespace(received_at_ms=t) for t in [1000,1990,2000]]
        with patch('asurada.review_capture.CaptureJsonlSource',return_value=packets),patch('asurada.review_capture.F125PacketDecoder') as decoder,patch('asurada.review_capture.CaptureSnapshotAssembler') as assembler,patch('asurada.review_capture.decode_snapshot',side_effect=lambda row:SimpleNamespace(**row)),patch('asurada.review_capture.UnifiedStateStore') as store:
            decoder.return_value.decode_raw.side_effect=envelopes
            assembler.return_value.push.side_effect=[*rows,None]
            store.return_value.update.return_value=True
            report=project_capture(source,dest,context=TaskContext.start('finish',5000))
        projected=[json.loads(line) for line in dest.read_text().splitlines()]
        checks['incomplete_last_frame_keeps_official_finish']=report['counts']['completion_records']==1 and projected[-1]['raw']['result_status']==3 and projected[-1]['raw']['last_lap_time_ms']==110218
        checks['only_proven_transition_excluded']=not projected[0]['raw'].get('review_exclude_reason') and projected[1]['raw'].get('review_exclude_reason')=='official_finish_transition'
        result=run_session_review(WorkflowStore(root/'tasks.db'),task_id='finish-review',source=dest)
        laps=next(x['result'] for x in result['results'] if x['step']=='index_official_laps')
        checks['lap_four_and_five_correctly_bound']={x['lap']:x['time_ms'] for x in laps}=={4:111160,5:110218}
        checks['completion_has_no_fabricated_physics']=projected[-1]['player']=={}
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

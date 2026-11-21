"""Session wire layout and immutable projection-version migration checks.
Offsets follow EA F1 25 v3 specification, Session Packet (753 bytes).
"""
from pathlib import Path
import json,hashlib,struct,tempfile
from regression_support import emit_result
from asurada.pdu_decoder import F125PacketDecoder,PacketDecodeError
from asurada.pdu import RawPacket
from asurada.capture_ingest import CaptureJsonlSource
from asurada.review_capture import project_capture_cached,PROJECTION_VERSION
from asurada.task_runtime import TaskContext
from asurada.session_review_workflow import run_session_review
from asurada.workflow_store import WorkflowStore


def run():
    checks={};decoder=F125PacketDecoder()
    fixture=Path(__file__).resolve().parents[1]/'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    packet=next(p for p in CaptureJsonlSource(fixture) if p.payload[6]==1)
    checks['fixture_is_full_session']=len(packet.payload)==753
    rejected=[]
    for n in range(29,753):
     try:decoder.decode_raw(RawPacket(packet.received_at_ms,packet.payload[:n],'test',1))
     except PacketDecodeError:rejected.append(n)
    checks['every_truncated_body_rejected']=len(rejected)==724
    try:decoder.decode_raw(RawPacket(1,packet.payload+b'\x00','test',1));checks['oversize_rejected']=False
    except PacketDecodeError:checks['oversize_rejected']=True
    wire=bytearray(packet.payload);wire[36]=255;wire[47]=1;struct.pack_into('<fb',wire,48,.125,-1);wire[153]=2;wire[154]=1
    body=decoder.decode_raw(RawPacket(1,bytes(wire),'test',1)).payload['body']
    checks['signed_track_and_zone']=body['track_id']==-1 and body['marshal_zones'][0]['zone_flag']==-1 and body['marshal_zones'][0]['zone_start']==.125
    checks['independent_control_positions']=body['safety_car_status']==2 and body['network_game']==1
    for control in range(4):
        wire[153]=control
        wire[155]=1
        struct.pack_into('<BBBbbbbB',wire,156,10,15,3,21,-1,16,2,75)
        wire[668]=1
        decoded=decoder.decode_raw(RawPacket(1,bytes(wire),'test',1)).payload['body']
        checks[f'control_state_{control}']=decoded['safety_car_status']==control
        checks[f'forecast_and_tail_unshifted_{control}']=(
            decoded['num_weather_forecast_samples']==1
            and decoded['weather_forecast_samples'][0]['rain_percentage']==75
            and decoded['weather_forecast_samples'][0]['track_temperature_change']==-1
            and decoded['forecast_accuracy']==1)
    with tempfile.TemporaryDirectory() as temp:
     p=Path(temp);dest=p/'projection.jsonl';manifest=p/'manifest.json'
     report=project_capture_cached(fixture,dest,manifest,context=TaskContext.start('fresh',5000))
     checks['new_projection_version']=report['version']==PROJECTION_VERSION=='review-projection-v4'
     original=dest.read_bytes();old=dict(report,version='review-projection-v1');manifest.write_text(json.dumps(old))
     before=manifest.read_bytes()
     try:project_capture_cached(fixture,dest,manifest,context=TaskContext.start('old',5000));checks['old_cache_rejected']=False
     except ValueError as e:checks['old_cache_rejected']=str(e)=='capture_projection_version_conflict'
     checks['old_artifacts_preserved']=dest.read_bytes()==original and manifest.read_bytes()==before
     store=WorkflowStore(p/'review.db')
     old_request={'version':'session-review-v6','driver_id':'fixture','memory_path':str(store.path.with_suffix('.memory.sqlite3').resolve()),'training_path':str(store.path.with_suffix('.training.sqlite3').resolve()),'source':str(fixture.resolve()),'sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'steps':['project_capture','index_official_laps','compare_recent_laps','analyze_segments','persist_session_facts','training_followup','review_report'],'capture_directory':str(p.resolve()),'projection_version':'review-projection-v1'}
     store.create('old-task',old_request,timeout_s=30)
     prior=store.get('old-task')
     try:run_session_review(store,task_id='old-task',source=fixture,driver_id='fixture',capture_directory=p);checks['old_task_rejected']=False
     except ValueError:checks['old_task_rejected']=store.get('old-task')==prior
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

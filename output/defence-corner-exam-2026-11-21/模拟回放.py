import json
from tempfile import TemporaryDirectory
from pathlib import Path
from attack_forecast_archive_replay import replay
from score_defence_radio import finish_time
from asurada.track_model import load_track_profile

CLOCK = json.loads((Path(__file__).resolve().parents[1] / 'defence-lead-2026-11-21/播报时长.json').read_text())
def snapshots(start, gap0):
    for i in range(91):
        t=i/10
        gap=gap0-12*t
        braking=max(0,t-5.7)
        speed=50-7*braking
        p=start+50*t-3.5*braking**2
        def car(rear):
            absolute = p - (gap if rear else 0)
            return dict(car_index=8 if rear else 9, name='模拟后车' if rear else '玩家',
                        position=(2+int(gap>0) if rear else 2+int(gap<=0)),
                        lap=5+int(absolute//6174),lap_distance_m=absolute%6174,
                        speed_kph=223.2-25.2*braking if rear else 180.0-25.2*braking, world_position_x=2000+absolute,
                        world_position_y=0.,world_position_z=103 if rear else 100,
                        gap_behind_s=gap/(speed+12) if not rear and gap>0 else None,
                        gap_confidence_behind='high' if not rear and gap>0 else 'none',
                        tyre=dict(compound='M',age_laps=3,wear_pct=15),
                        ers_pct=75,fuel_laps_remaining=12,drs_available=rear,pit_status='NONE')
        player=car(False)
        yield dict(session_uid="corner-exam",track="Jeddah",session_epoch=0,source_timestamp_ms=1700000000000+i*100,
                   player=player,rivals=[car(True)],lap_number=player['lap'],total_laps=15,weather='Clear',safety_car='NONE',
                   raw=dict(session_type='SprintRaceLike(15)',timing_mode='race_like',timing_support_level='official_preferred',session_time_s=t,result_status=2,pit_status_code=0,
                            marshal_zone_flag=1,session_paused=False,current_lap_invalid=False,brake=.4 if braking else 0.0,
                            throttle=0. if braking else .8,steer=0.,world_forward_dir=dict(x=1.,z=0.)))
def run():
    for scenario,start,gap0 in [('straight',5820,75),('turn',90,75),('straight-boundary',5820,76),('turn-boundary',90,76)]:
        dest=Path('/tmp/asurada-corner-exam-'+scenario)
        with TemporaryDirectory() as d:
            (Path(d)/'session_log.jsonl').write_text(''.join(json.dumps(s,ensure_ascii=False)+'\n' for s in snapshots(start,gap0)))
            replay(Path(d),'corner-exam',CLOCK,dest)
        rows=list(map(json.loads,dest.with_suffix('.jsonl').open()))
        jobs=json.loads(dest.with_suffix('.json').read_text())['starts']
        print(scenario, [(rows[j['i']]['t'],j['text'],finish_time(rows,j),j.get('cut')) for j in jobs])
        print('rec first',next(((r['t'],r['defence']['corner']) for r in rows if r['defence'] and r['defence']['recommended']),None))
if __name__=='__main__':run()

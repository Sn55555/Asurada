"""Mic-free controlled race: packet assembly, normal strategy, IPC and measured playback starts."""
import argparse
import hashlib
import json
import struct
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from asurada.config import StrategyThresholds
from asurada.decode import decode_snapshot
from asurada.output import ConsoleVoiceOutput
from asurada.personality_runtime import PersonalityRuntime
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu import PacketEnvelope, RawPacket
from asurada.pdu_decoder import F125PacketDecoder
from asurada.snapshot_contract import snapshot_payload
from asurada.speech_client import SharedSpeechClient
from asurada.speech_service import SpeechService
from asurada.strategy import StrategyEngine
from personality_attack_window_regression import ReplayBackend

SESSION = 81016
TARGET = 16
CASES = dict(follow="following", attempt="attempt_no_pass", pass_target="passed",
             dropped="uncertain", tailgate="uncertain", rival_moves="uncertain", prepared_only="uncertain", brief_overlap="uncertain", pit="uncertain", wrong_event="uncertain",
             stale_event="uncertain", rank_only="uncertain", repassed="uncertain", yellow="uncertain", switch_target="uncertain")


def trajectory(case, t):
    if t <= 2:
        return 36 - 4*t, .3
    if case == "follow":
        return 28, .3
    lead = max(2, 28 - 8*(t-2))
    lateral = min(2.8, .3 + (t-2))
    if case == "prepared_only":
        return max(12, lead), lateral
    if case == "brief_overlap" and 5 <= t <= 6:
        return (3.9 if t == 5.5 else 4.9), lateral
    if case == "tailgate":
        return lead if t < 6 else min(18, 2 + 12*(t-6)), .4
    if t > 6:
        if case in {"pass_target", "pit", "wrong_event", "stale_event", "rank_only", "repassed"}:
            lead = max(-75, 2 - 20*(t-6))
        else:
            lead = min(28, 2 + 15*(t-6))
    if case == "repassed" and t >= 6.5:
        lead = min(18, 1+8*(t-6.5))
    return lead, lateral


def event_packet(frame, at, received, target, passer=0):
    decoder = F125PacketDecoder()
    packet = struct.pack(decoder.HEADER_FORMAT, 2025, 25, 1, 0, 1, 3, SESSION, at, frame, frame, 0, 255)
    packet += b'OVTK' + bytes((passer, target))
    return decoder.decode_raw(RawPacket(received, packet.ljust(decoder.PACKET_SIZES[3], b'\0'), '127.0.0.1', 20777))


def frames(case, personality):
    assembler = CaptureSnapshotAssembler()
    for tick in range(53):
        t = tick/4
        if case == "dropped" and 4.5 <= t < 5.5:
            continue
        at = 100+t
        frame = tick+100
        received = 1800000000000 + tick*250
        h = dict(session_uid=SESSION, frame_identifier=frame, overall_frame_identifier=frame,
                 session_time_s=at, player_car_index=0, received_at_ms=received)
        def feed(kind, body):
            packet = PacketEnvelope(kind, frame, str(SESSION), dict(header=h, body=body))
            snapshot = assembler.push(packet)
            if assembler.accepted_epoch is not None:
                personality.observe_packet(packet, assembler.accepted_epoch, replay=True)
            return snapshot
        lead, side = trajectory(case, t)
        distance = 2010 + 50*t
        ahead = lead < 0
        player_pos = 1 if ahead else 2
        rival_pos = 2 if ahead else 1
        rival_id = 8 if case == "switch_target" and t >= 5 else TARGET
        flag = 3 if case == "yellow" and 5 <= t < 8 else 1
        feed("Session", dict(track_id=29, track_length_m=6174, session_type=10, total_laps=17,
             safety_car_status=0, marshal_zones=[dict(zone_start=0., zone_flag=flag)]))
        reverse = t == 6.5 and case == "repassed"
        if (t == 6.25 and case in {"pass_target", "wrong_event", "repassed"}
                or t == 0 and case == "stale_event" or reverse):
            target = 8 if case == "wrong_event" else TARGET
            packet = event_packet(frame, at, received, 0 if reverse else target, target if reverse else 0)
            assembler.push(packet)
            personality.observe_packet(packet, assembler.accepted_epoch, replay=True)
            # Another event in the same frame must not erase the pass.
            feed("Event", dict(event_code="BUTN", event_detail={}))
        def lap(car, pos, d, gap, pit=0):
            return dict(car_index=car, car_position=pos, current_lap_num=16, lap_distance_m=d,
                        total_distance_m=15*6174+d, delta_to_car_in_front_ms=gap,
                        pit_status=pit, result_status=2, sector=0)
        gap_ms = max(5, round(abs(lead)*20))
        p = lap(0, player_pos, distance, 0 if ahead else gap_ms)
        rival = lap(rival_id, rival_pos, distance+lead, gap_ms if ahead else 0,
                    int(case == "pit" and t >= 6))
        rear = lap(7, 3, distance-140, 2600)
        def motion(car, d, z):
            return dict(car_index=car, world_position=dict(x=d, y=0., z=z),
                        world_forward_dir=dict(x=1., y=0., z=0.))
        # A rival changing line can produce the same relative geometry as a player attack.
        player_z = 80. if case == "rival_moves" else 80.3-side
        player_motion = motion(0, distance, player_z)
        ptelem = dict(car_index=0, throttle=.82, brake=0., steer=-.06 if 2 < t < 4.75 and case not in {"follow","rival_moves","tailgate"} else .02, speed_kph=180,
                      drs=t < 5)
        rival_speed = 180 + (lead-trajectory(case,max(0,t-.25))[0])*14.4
        status = dict(car_index=0, drs_allowed=t < 5, ers_store_energy=3200000, fuel_in_tank=12, fuel_capacity=110,
                      fuel_remaining_laps=8, visual_tyre_compound=17)
        bodies = dict(LapData=dict(p, all_cars=[p,rival,rear]), CarStatus=dict(status,all_cars=[status]),
                      CarTelemetry=dict(ptelem,all_cars=[ptelem,dict(car_index=rival_id,speed_kph=rival_speed)]),
                      Motion=dict(player_motion,all_cars=[player_motion,motion(rival_id,distance+lead,player_z+side)]),
                      CarDamage={}, MotionEx={})
        for kind, body in bodies.items():
            snapshot = feed(kind, body)
        assert snapshot is not None
        yield t, snapshot


def replay(case):
    with TemporaryDirectory(prefix='asurada-attack-', dir='/tmp') as tmp, patch.dict('os.environ', {
        'ASURADA_PERSONALITY_ENABLED':'1', 'ASURADA_PERSONALITY_LLM_MODE':'disabled',
        'ASURADA_ATTACK_MODE_STATE_PATH':tmp+'/mode.json','ASURADA_TRAINING_MEMORY_DB':tmp+'/train.db',
        'ASURADA_RELATIONSHIP_DB':tmp+'/growth.db','ASURADA_PIT_EVIDENCE_DB':tmp+'/pit.db'}):
        backend = ReplayBackend({})
        output = ConsoleVoiceOutput(backend=backend)
        publication = Path(tmp)/'latest_snapshot.json'
        service = SpeechService(Path(tmp)/'speech.sock', output=output, session_source=publication).start()
        client = SharedSpeechClient(service.path)
        engine = StrategyEngine(StrategyThresholds())
        personality = PersonalityRuntime()
        history, trace = [], []
        verdict = None
        opening = None
        decisions_recorded = 0
        prefix = hashlib.sha256()
        try:
            for t, snapshot in frames(case, personality):
                if t <= 2:
                    prefix.update(json.dumps(snapshot, sort_keys=True).encode())
                state = decode_snapshot(snapshot)
                # Fresh replay publication for the same authority checks used by live speech.
                state.source_timestamp_ms = int(time.time()*1000)
                state.raw["source_timestamp_ms"] = state.source_timestamp_ms
                history.append(state)
                decision = engine.evaluate(state, history[-30:])
                state.personality = personality.observe_snapshot(state, decision, replay=True)
                backend.clock = state.raw['session_time_s']
                temporary = publication.with_suffix('.tmp')
                temporary.write_text(json.dumps(snapshot_payload(state, decision)))
                temporary.replace(publication)
                client.emit(decision, state=state, render=False)
                window = decision.debug['attack_opportunity']
                if opening is None and window['phase'] == 'actionable':
                    opening = dict(window_id=window['window_id'], at_s=backend.clock,
                                   target=window["front_car_index"], segment=decision.debug['context']['track_segment'])
                if decision.debug.get('attack_outcome'):
                    decisions_recorded += 1
                if window.get('outcome'):
                    verdict = window['outcome']
                target = next((r for r in state.rivals if r.car_index == TARGET), None)
                trace.append(dict(t=backend.clock, strategy=[m.code for m in decision.messages],
                                  window=window['phase'], player_position=state.player.position,
                                  player_distance=state.player.lap_distance_m, player_z=state.player.world_position_z,
                                  target_position=target.position if target else None,
                                  target_distance=target.lap_distance_m if target else None,
                                  target_z=target.world_position_z if target else None,
                                  target_pit=target.pit_status if target else None,
                                  steer=state.raw['steer'], throttle=state.raw['throttle'], brake=state.raw['brake'],
                                  flag=state.raw['marshal_zone_flag'], overtakes=state.raw['recent_overtakes']))
            backend.clock += 4
            output.tick()
            return dict(expected=CASES[case], opening=opening, prefix=prefix.hexdigest(), result=verdict, decisions_recorded=decisions_recorded,
                        playback=backend.jobs, trace=trace)
        finally:
            service.close()
            personality.close()


def run():
    cases = {name: replay(name) for name in CASES}
    for name, row in cases.items():
        result = row['result']
        assert result and result['verdict'] == row['expected'], (name, result, row['trace'][::5])
        assert row['decisions_recorded'] == 1
        assert row['opening'] == cases['follow']['opening']
        assert row['opening']['target'] == result['target'] == TARGET
        assert row['opening']['window_id'] == result['window_id']
        if name != 'stale_event':
            assert row['prefix'] == cases['follow']['prefix']
        spoken = [job for job in row['playback'] if job['code'] == 'ATTACK_OUTCOME']
        assert len(spoken) <= 1, name
        if name in {'follow','attempt','pass_target','dropped'}:
            assert len(spoken) == 1 and spoken[0]['cancel_s'] is None, (name, row['playback'])
        if name == 'yellow':
            assert not spoken and any(job['code'] == 'LOCAL_YELLOW' for job in row['playback'])
        if name == 'pass_target':
            assert result['overtake_event_s'] == 106.25 and result['positions'] == [1,2]
            assert all(job['code'] not in {'ATTACK_MODE_WITHDRAW','PERSONALITY_OVERTAKE'} for job in row['playback'])
        assert all(job['opportunity']['outcome']['verdict'] == result['verdict'] for job in spoken)
    return cases


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    results = run()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
    for name,row in results.items():
        print(name,row['result']['verdict'],[j['text'] for j in row['playback']])

from regression_support import emit_result
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.packet_epoch import PacketEpoch
from asurada.pdu import PacketEnvelope


def packet(kind, overall, frame, uid='one', body=None):
    return PacketEnvelope(kind,frame,uid,{'header':{'received_at_ms':1000+overall,'overall_frame_identifier':overall,'frame_identifier':frame},'body':body or {}})


def run():
    checks = {}
    epoch = PacketEpoch()
    epoch.observe({'overall_frame_identifier':100,'frame_identifier':100})
    checks['ordinary_reordering_not_rewind'] = epoch.observe({'overall_frame_identifier':99,'frame_identifier':99}) == (True,False) and epoch.epoch==0
    checks['forward_overall_backwards_frame_is_rewind'] = epoch.observe({'overall_frame_identifier':101,'frame_identifier':50}) == (True,True) and epoch.epoch==1
    checks['pre_rewind_packet_rejected'] = epoch.observe({'overall_frame_identifier':100,'frame_identifier':100}) == (False,False)
    checks['same_new_frame_other_packet_kept'] = epoch.observe({'overall_frame_identifier':101,'frame_identifier':50}) == (True,False)
    a = CaptureSnapshotAssembler()
    session = {'track_id':0,'track_length_m':5000,'session_type':10,'total_laps':20}
    a.push(packet('Session',100,100,body=session))
    a.push(packet('Event',100,100,body={'event_code':'TEST'}))
    a.session_start_fuel_by_uid['one']=20
    a.push(packet('Motion',101,50))
    checks['rewind_clears_session_event_and_fuel'] = not a.latest_session_by_uid and not a.latest_event_by_uid and not a.session_start_fuel_by_uid
    checks['rewind_removes_old_partial_frames'] = set(a.frames)=={('one',50)}
    late = packet('Event',100,100,body={'event_code':'OLD'})
    late.payload['header']['received_at_ms']=1102
    a.push(late)
    checks['late_pre_rewind_cannot_restore_cache'] = not a.latest_event_by_uid and a.epoch_rejections==1
    a.push(packet('Session',103,51,body=session))
    checks['new_epoch_session_recovers'] = a.packet_epochs['one'].epoch==1 and 'one' in a.latest_session_by_uid
    for index in range(6):
        a.push(packet('Session',200+index,60,uid=str(index),body=session))
    checks['session_cache_count_bounded'] = len(a.packet_epochs)==4 and len(a.latest_session_by_uid)==4 and all(key[0] != 'one' for key in a.frames)
    from phase1_all_track_udp_replay_regression import load_real_udp_frame, COMPACT_FIXTURE
    from asurada.pdu_decoder import F125PacketDecoder
    from asurada.decode import decode_snapshot
    from asurada.state import UnifiedStateStore
    source_session, source_frames = load_real_udp_frame(COMPACT_FIXTURE)
    decoder, assembler, store = F125PacketDecoder(), CaptureSnapshotAssembler(), UnifiedStateStore()
    snapshots = []
    for overall, frame in ((100,100),(101,50)):
        for raw in [source_session, *source_frames.values()]:
            envelope = decoder.decode_raw(raw)
            envelope.payload['header'].update(overall_frame_identifier=overall, frame_identifier=frame, received_at_ms=overall*100)
            result = assembler.push(envelope)
            if result is not None:
                snapshots.append(result)
                store.update(decode_snapshot(result))
    checks['normalized_snapshot_carries_new_epoch'] = [s['session_epoch'] for s in snapshots] == [0,1]
    checks['downstream_epoch_not_incremented_twice'] = store.latest.session_epoch == 1 and len(store.recent(10)) == 1
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

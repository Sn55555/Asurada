from dataclasses import replace
from asurada.frame_counter import newer, older
from asurada.packet_epoch import PacketEpoch
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.state import UnifiedStateStore
from asurada.pdu_decoder import F125PacketDecoder
from asurada.decode import decode_snapshot
from phase1_all_track_udp_replay_regression import load_real_udp_frame, COMPACT_FIXTURE
from packet_epoch_regression import packet
from regression_support import emit_result


def run():
    checks = {'wrap_is_forward': newer(1, 0xfffffffe) and not older(1, 0xfffffffe),
              'late_pre_wrap_is_old': older(0xffffffff, 1),
              'half_range_is_not_forward': not newer(0x80000000, 0)}
    epoch = PacketEpoch()
    epoch.observe({'overall_frame_identifier': 0xfffffffe, 'frame_identifier': 0xfffffffe})
    checks['packet_wrap_not_rewind'] = epoch.observe({'overall_frame_identifier': 1, 'frame_identifier': 1}) == (True, False) and epoch.epoch == 0
    epoch.observe({'overall_frame_identifier': 2, 'frame_identifier': 0})
    checks['actual_rewind_after_wrap'] = epoch.epoch == 1
    checks['floor_rejects_pre_wrap_packet'] = epoch.observe({'overall_frame_identifier': 0xffffffff, 'frame_identifier': 0xffffffff}) == (False, False)
    assembly = CaptureSnapshotAssembler()
    assembly.push(packet('Motion',0xfffffff0,0xfffffff0))
    p = packet('Motion',1,1);p.payload['header']['received_at_ms']=0x100000002+1000
    assembly.push(p)
    checks['old_partial_frame_pruned_across_wrap'] = ('one',0xfffffff0) not in assembly.frames
    source_session, source_frames = load_real_udp_frame(COMPACT_FIXTURE)
    decoder, assembly, store = F125PacketDecoder(), CaptureSnapshotAssembler(), UnifiedStateStore()
    snapshots = []
    for index, counter in enumerate((0xfffffffe, 0xffffffff, 0, 1)):
        for raw in [source_session, *source_frames.values()]:
            envelope = decoder.decode_raw(raw)
            envelope.payload['header'].update(overall_frame_identifier=counter, frame_identifier=counter, received_at_ms=100000+index*100)
            result = assembly.push(envelope)
            if result is not None:
                snapshots.append(result);store.update(decode_snapshot(result))
    checks['actual_packet_projection_keeps_epoch'] = len(snapshots)==4 and all(s['session_epoch']==0 for s in snapshots)
    checks['state_history_continues_across_wrap'] = len(store.history())==4 and store.latest.raw['overall_frame_identifier']==1
    late=replace(store.latest, raw={**store.latest.raw,'overall_frame_identifier':0xffffffff,'frame_identifier':0xffffffff})
    checks['state_rejects_late_pre_wrap_snapshot'] = not store.update(late) and len(store.history())==4
    return {'passed':all(checks.values()),'checks':checks,'scope':'recorded packet fixture with boundary counter injection; not a live game'}


if __name__=='__main__':emit_result(run())

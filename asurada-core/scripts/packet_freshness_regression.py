from regression_support import emit_result
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu import PacketEnvelope


def envelope(kind, time, body=None, uid='one'):
    return PacketEnvelope(kind, 1, uid, {'header': {'received_at_ms':time,'frame_identifier':1},'body':body or {}})


def run():
    a = CaptureSnapshotAssembler()
    session = {'track_id':0,'track_length_m':5000,'session_type':10,'total_laps':20}
    # Use a known-valid session definition according to the production validator.
    assert a._is_session_valid(session)
    a.push(envelope('Session', 1000, session))
    a.push(envelope('Event', 1100, {'event_code':'TEST'}))
    a.push(envelope('Motion', 2000))
    checks = {'current_cache_kept': 'one' in a.latest_session_by_uid and 'one' in a.latest_event_by_uid,
              'age_reported':a.cache_quality_by_uid['one']['Session']['age_ms']==1000}
    a.push(envelope('Motion', 3200))
    checks['expired_event_removed'] = 'one' not in a.latest_event_by_uid
    a.push(envelope('Motion', 6100))
    checks['expired_session_blocks_assembly'] = 'one' not in a.latest_session_by_uid and a.cache_quality_by_uid['one']['Session']['quality']=='unavailable'
    a.push(envelope('Session', 6200, session))
    checks['fresh_session_recovers'] = 'one' in a.latest_session_by_uid
    a.push(envelope('Session', 2000, dict(session, track_id=1)))
    checks['older_packet_cannot_replace_new_cache'] = a.latest_session_by_uid['one']['track_id']==0
    a.push(envelope('Motion', 7000, uid='two'))
    checks['scope_isolated'] = a.cache_quality_by_uid['two']['Session']['quality']=='unavailable' and 'one' in a.latest_session_by_uid
    a.push(envelope('Motion', float('nan')))
    checks['invalid_clock_rejected'] = a.cache_freshness.rejected==2
    return {'passed':all(checks.values()), 'checks':checks}


if __name__=='__main__':emit_result(run())

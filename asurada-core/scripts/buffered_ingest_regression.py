from threading import Event
import time
from regression_support import emit_result
from observation_lane_regression import eventually
from asurada.buffered_ingest import BufferedPacketSource
from asurada.pdu import RawPacket


def packet(i):
    return RawPacket(i, bytes([i]), 'test', 1)


def run():
    checks = {}
    release, consumed = Event(), Event()
    def input_packets():
        yield packet(0)
        release.wait(2)
        for i in range(1, 21):
            yield packet(i)
        consumed.set()
    source = BufferedPacketSource(input_packets(), capacity=3)
    iterator = iter(source)
    first = next(iterator)
    release.set()
    checks['receiver_continues_while_consumer_paused'] = consumed.wait(1)
    health = source.snapshot()
    checks['bounded_queue_reports_loss'] = health['queued'] == 3 and health['dropped_oldest'] == 17
    rest = list(iterator)
    checks['overload_preserves_latest_order'] = [p.received_at_ms for p in rest] == [18, 19, 20]
    checks['receive_metadata_preserved'] = first.ingress_queue_ms >= 0 and first.received_monotonic_ns is not None and rest[-1].ingress_health['dropped_oldest'] == 17
    checks['producer_closed'] = source.close()

    def broken():
        yield packet(0)
        raise OSError('receiver failed')
    source = BufferedPacketSource(broken())
    try:
        list(source)
        checks['producer_error_propagated'] = False
    except OSError as exc:
        checks['producer_error_propagated'] = str(exc) == 'receiver failed' and source.close()

    class Stoppable:
        def __init__(self):
            self.stop = Event()
        def __iter__(self):
            yield packet(0)
            self.stop.wait(2)
        def close(self):
            self.stop.set()
    source = BufferedPacketSource(Stoppable())
    iterator = iter(source)
    next(iterator)
    checks['close_stops_blocked_receiver'] = source.close()
    iterator.close()
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

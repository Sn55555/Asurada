from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import json
import time
from regression_support import emit_result
from asurada.async_capture import AsyncPacketRecorder
from asurada.udp_capture import RawPacketCaptureRecorder
from asurada.capture_ingest import CaptureJsonlSource
from asurada.pdu import RawPacket


def run():
    checks = {}
    with TemporaryDirectory() as temp:
        path = Path(temp)/'capture.jsonl'
        recorder = RawPacketCaptureRecorder(path)
        recorder.reset()
        entered, release = Event(), Event()
        original = recorder.append
        def slow(packet):
            entered.set(); release.wait(2); original(packet)
        recorder.append = slow
        async_recorder = AsyncPacketRecorder(recorder, capacity=1)
        checks['unfinished_manifest_persisted'] = not json.loads(async_recorder.manifest_path.read_text())['finalized']
        packet = RawPacket(1000,b'abc','test',1)
        started = time.monotonic()
        async_recorder.append(packet)
        checks['slow_disk_does_not_block_submit'] = time.monotonic()-started < .1 and entered.wait(1)
        async_recorder.append(packet)
        checks['overload_recorded'] = not async_recorder.append(packet) and async_recorder.snapshot()['dropped'] == 1
        checks['unfinished_close_not_claimed_complete'] = not async_recorder.close(timeout_s=.01)
        release.set()
        checks['drain_finishes'] = async_recorder.close()
        health = json.loads(async_recorder.manifest_path.read_text())
        checks['loss_persisted_after_drain'] = health['finalized'] and not health['local_capture_complete'] and health['sink']['dropped'] == 1
        rows = list(CaptureJsonlSource(path))
        checks['capture_readable_with_submission_ids'] = len(rows)==2 and [p.capture_submission_id for p in rows]==[1,2]
        recorder.reset()
        recorder.append = original
        clean = AsyncPacketRecorder(recorder)
        clean.append(packet); clean.close(ingress_health={'queued':0,'dropped_oldest':0})
        checks['clean_capture_marked_locally_complete'] = json.loads(clean.manifest_path.read_text())['local_capture_complete']
        clean.close(ingress_health={'queued':0,'dropped_oldest':2})
        checks['ingress_loss_invalidates_completeness'] = not json.loads(clean.manifest_path.read_text())['local_capture_complete']
        broken = AsyncPacketRecorder(recorder)
        def fail(packet):raise OSError('disk full')
        recorder.append = fail
        broken.append(packet); broken.close()
        health = json.loads(broken.manifest_path.read_text())
        checks['disk_failure_persisted'] = not health['local_capture_complete'] and health['sink']['failures']==1
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

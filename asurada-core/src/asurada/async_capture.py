"""Raw capture sink with durable completeness metadata outside the hot path."""
from dataclasses import replace
import json
from pathlib import Path

from .async_sink import AsyncRuntimeSink


class _PacketWriter:
    def __init__(self, recorder):
        self.recorder = recorder

    def append(self, packet, unused):
        self.recorder.append(packet)


class AsyncPacketRecorder:
    def __init__(self, recorder, *, capacity=1024):
        self.recorder = recorder
        self.manifest_path = Path(str(recorder.path) + '.health.json')
        self.submitted = 0
        self._last_ingress = {}
        self._write_manifest({'contract_version': 'capture-health-v1', 'finalized': False,
                              'local_capture_complete': False, 'reason': 'recording_in_progress'})
        self.sink = AsyncRuntimeSink(_PacketWriter(recorder), capacity=capacity)

    def append(self, packet):
        self.submitted += 1
        self._last_ingress = dict(packet.ingress_health or {})
        return self.sink.append(replace(packet, capture_submission_id=self.submitted), None)

    def snapshot(self):
        return dict(self.sink.snapshot(), submitted=self.submitted)

    def close(self, *, timeout_s=5., ingress_health=None):
        drained = self.sink.close(timeout_s)
        health = self.snapshot()
        ingress = self._last_ingress if ingress_health is None else ingress_health
        complete = (drained and health['failures'] == 0 and health['dropped'] == 0
                    and health['written'] == self.submitted
                    and not ingress.get('dropped_oldest', 0)
                    and not ingress.get('queued', 0) and not ingress.get('error'))
        self._write_manifest(dict(contract_version='capture-health-v1', finalized=drained,
                                  local_capture_complete=complete, sink=health, ingress=ingress,
                                  scope='application_received_packets_only_not_network_loss'))
        return drained

    def _write_manifest(self, payload):
        temporary = self.manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.manifest_path)

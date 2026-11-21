"""A rejected datagram must not reach assembly or stop later valid telemetry."""
from contextlib import redirect_stdout
from io import StringIO
import base64
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from regression_support import emit_result
from asurada.capture_ingest import CaptureJsonlSource
from asurada.capture_runtime import CaptureReplayRuntime
from asurada.config import StrategyThresholds
from asurada.live_runtime import LiveRuntime
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.pdu import RawPacket
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError
from asurada.review_capture import project_capture
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.task_runtime import TaskContext
from export_phase2_training_data import export_dataset


def wire_packet(packet_id, size=None):
    decoder = F125PacketDecoder
    header = struct.pack(decoder.HEADER_FORMAT, 2025, 25, 1, 0, 1, packet_id, 100, 1., 1, 1, 0, 255)
    return RawPacket(1000, header + bytes((size or decoder.PACKET_SIZES[packet_id]) - len(header)), 'test', 1)


def runtime_dependencies(directory):
    return dict(state_store=UnifiedStateStore(), strategy=StrategyEngine(
        StrategyThresholds(), model_policy=ModelAdmissionPolicy(modes={name: 'disabled' for name in MODEL_NAMES})),
        voice_output=SimpleNamespace(emit=lambda *a, **k: {}),
        logger=SimpleNamespace(directory=directory, append=lambda *a, **k: None))


def run():
    checks = {}
    decoder = F125PacketDecoder()
    truncated = []
    for packet_id, size in decoder.PACKET_SIZES.items():
        packet = wire_packet(packet_id)
        checks[f'valid_family_{packet_id}'] = decoder.decode_raw(packet).kind == decoder.PACKET_ID_NAMES[packet_id]
        rejected = 0
        for length in range(size):
            bad = RawPacket(1000, packet.payload[:length], 'test', 1)
            try:
                decoder.decode_raw(bad)
            except PacketDecodeError:
                rejected += 1
        checks[f'every_truncation_rejected_{packet_id}'] = rejected == size
        truncated += [RawPacket(1000, packet.payload[:n], 'test', 1) for n in (29, size // 2, size - 1)]
    for error in (struct.error('short read'), IndexError('wire index'), UnicodeDecodeError('ascii', b'\xff', 0, 1, 'invalid')):
        with patch.object(decoder, '_decode_body', side_effect=error):
            try:
                decoder.decode_raw(wire_packet(0))
                checks[type(error).__name__] = False
            except PacketDecodeError as exc:
                checks[type(error).__name__] = exc.__cause__ is error and 'packet_id=0' in str(exc)
    for error in (KeyError('bug'), ValueError('bug'), TypeError('bug'), RuntimeError('bug')):
        with patch.object(decoder, '_decode_body', side_effect=error):
            try:
                decoder.decode_raw(wire_packet(0))
                checks['programming_' + type(error).__name__] = False
            except type(error) as exc:
                checks['programming_' + type(error).__name__] = exc is error
    invalid_index = bytearray(wire_packet(0).payload)
    invalid_index[27] = 255
    try:
        decoder.decode_raw(RawPacket(1, bytes(invalid_index), 'test', 1))
        checks['invalid_array_index_rejected'] = False
    except PacketDecodeError as exc:
        checks['invalid_array_index_rejected'] = exc.reason == 'invalid_car_index'

    fixture = Path(__file__).resolve().parents[1] / 'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    valid = list(CaptureJsonlSource(fixture))
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        live = LiveRuntime(truncated + valid, **runtime_dependencies(directory))
        accepted = []
        push = live.pipeline.assembler.push
        with patch.object(live.pipeline.assembler, 'push', side_effect=lambda p: (accepted.append(p), push(p))[1]), redirect_stdout(StringIO()):
            live.run()
        checks['live_counts_all_rejections'] = live.decode_diagnostics.count == len(truncated)
        checks['live_only_valid_packets_reach_assembly'] = len(accepted) == len(valid)
        checks['live_recovers_with_real_complete_frame'] = live.state_store.latest is not None
        with patch.object(live.pipeline, 'ingest_packet', side_effect=RuntimeError('pipeline bug')), redirect_stdout(StringIO()):
            try:
                live.run()
                checks['live_programming_error_propagates'] = False
            except RuntimeError:
                checks['live_programming_error_propagates'] = True
        capture = directory / 'capture.jsonl'
        capture.write_text(''.join(json.dumps(dict(received_at_ms=p.received_at_ms, source_host=p.source_host,
            source_port=p.source_port, payload_base64=base64.b64encode(p.payload).decode())) + '\n' for p in truncated + valid))
        replay = CaptureReplayRuntime(capture, **runtime_dependencies(directory))
        with redirect_stdout(StringIO()):
            replay.run()
        report = json.loads((directory / 'capture_summary.json').read_text())
        checks['capture_counts_and_recovers'] = report['decode_errors'] == len(truncated) and report['normalized_snapshots'] > 0
        projection = project_capture(capture, directory / 'review.jsonl', context=TaskContext.start('decode-resilience', 10000))
        checks['review_counts_and_recovers'] = projection['decode_diagnostics']['count'] == len(truncated) and projection['counts']['snapshots'] > 0
        metadata = directory / 'metadata.json'
        metadata.write_text(json.dumps({'samples': [dict(sample_name='fixture', session_label='Fixture', session_type_code=15,
            session_uid=decoder.decode_raw(valid[0]).session_uid, file_path=str(capture))]}))
        export = export_dataset(sample_metadata_path=metadata, output_dir=directory / 'export', sample_splits={'fixture': 'test'},
            next_segment_offsets=[], max_history_frames=12, sample_limit=None)
        checks['export_counts_and_recovers'] = export['samples'][0]['decode_errors'] == len(truncated) and export['record_count'] > 0
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

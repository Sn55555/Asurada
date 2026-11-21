from types import SimpleNamespace
from unittest.mock import patch
from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.runtime_pipeline import StrategyRuntimePipeline
from asurada.models import StrategyDecision
from asurada.pdu import RawPacket
from asurada.state import UnifiedStateStore


def run():
    state = make_state()
    decision = StrategyDecision(messages=[], debug={})
    captured = []
    pipeline = StrategyRuntimePipeline.__new__(StrategyRuntimePipeline)
    pipeline.personality = None
    pipeline.decoder = SimpleNamespace(decode_raw=lambda p: 'envelope')
    pipeline.assembler = SimpleNamespace(push=lambda e: {})
    pipeline.state_store = UnifiedStateStore()
    pipeline.strategy = SimpleNamespace(evaluate=lambda s,h: decision)
    pipeline.voice_output = SimpleNamespace(emit=lambda *a, **k: {})
    pipeline.logger = SimpleNamespace(append=lambda s,d: captured.append(d.debug['runtime_timing'].copy()))
    packet = RawPacket(100, b'', 'test', 1, received_monotonic_ns=990_000_000,
                       ingress_queue_ms=8., ingress_health={'dropped_oldest': 4})
    with patch('asurada.runtime_pipeline.decode_snapshot', return_value=state), \
         patch('asurada.runtime_pipeline.time.time_ns', return_value=10_000_000_000), \
         patch('asurada.runtime_pipeline.time.monotonic_ns', side_effect=[1_000_000_000,1_001_000_000,1_002_000_000,1_003_000_000,1_008_000_000,1_010_000_000]):
        pipeline.ingest_packet(packet)
    timing = captured[0]
    checks = {'monotonic_strategy_duration': timing['strategy_latency_ms'] == 5.,
              'receive_to_output_includes_queue': timing['receive_to_output_submission_ms'] == 20.,
              'pipeline_excludes_queue': timing['pipeline_latency_ms'] == 10.,
              'wall_timestamp_projection': timing['output_finished_at_ms'] == 10010,
              'ingress_loss_in_log': timing['ingress_health']['dropped_oldest'] == 4,
              'duration_clock_explicit': timing['duration_clock'] == 'monotonic'}
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

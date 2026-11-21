"""Quantify snapshot loss caused specifically by cache TTL on a complete capture."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from asurada.capture_ingest import CaptureJsonlSource
from asurada.packet_snapshot import CaptureSnapshotAssembler
from asurada.pdu_decoder import F125PacketDecoder, PacketDecodeError


def audit(source):
    decoder = F125PacketDecoder()
    current, shadow = CaptureSnapshotAssembler(), CaptureSnapshotAssembler()
    # Counterfactual keeps epoch and packet ordering rules; only TTL eviction
    # is disabled. It is diagnostic and never used for strategy execution.
    shadow.cache_freshness.expire = lambda *args: {}
    totals = Counter()
    sessions = {}
    examples = []
    for packet in CaptureJsonlSource(source):
        totals['packets'] += 1
        try:
            envelope = decoder.decode_raw(packet)
        except PacketDecodeError:
            totals['decode_errors'] += 1
            continue
        actual, comparison = current.push(envelope), shadow.push(envelope)
        if actual is not None or comparison is not None:
            uid = str(envelope.session_uid)
            counts = sessions.setdefault(uid, dict(current=0, without_cache_expiry=0, ttl_suppressed=0))
            if actual is not None:
                totals['current_snapshots'] += 1
                counts['current'] += 1
            if comparison is not None:
                totals['without_cache_expiry_snapshots'] += 1
                counts['without_cache_expiry'] += 1
            if comparison is not None and actual is None:
                totals['ttl_suppressed'] += 1
                counts['ttl_suppressed'] += 1
                if len(examples)<12:
                    examples.append(dict(uid=uid, timestamp=packet.received_at_ms,
                                         cache_quality=current.cache_quality_by_uid.get(uid)))
    return dict(source=str(source), totals=dict(totals), sessions=sessions, examples=examples,
                invalid_or_old_receive_times=current.cache_freshness.rejected,
                pre_rewind_packets_rejected=current.epoch_rejections,
                scope='complete_capture_cache_expiry_counterfactual_not_strategy_or_live_acceptance')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.source)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['totals']))

"""Compact raw subpacket blocks before snapshot identity is established.

Raw UDP capture is the full-fidelity source. These repeated subpacket blocks
aren't read by strategy, training features or review consumers. Keep the
specific history/set/position fields those consumers do read. Diagnostic
exports can explicitly request full blocks with ASURADA_RAW_FULL_BLOCKS=1.
"""
from __future__ import annotations

import os
from typing import Any

UNUSED_FULL_BLOCKS = frozenset({'participants', 'lobby_info', 'car_setup',
                              'final_classification', 'auxiliary_packet_15'})


def project_raw(raw: dict[str, Any], *, full_blocks: bool | None = None) -> dict[str, Any]:
    if full_blocks is None:
        full_blocks = os.getenv('ASURADA_RAW_FULL_BLOCKS', '0') == '1'
    if full_blocks:
        return dict(raw)
    result = {key: value for key, value in raw.items() if key not in UNUSED_FULL_BLOCKS}
    if isinstance(raw.get('session_packet'), dict):
        # Legacy dashboard reader. New readers use snapshot.total_laps.
        result['session_packet'] = {key: raw['session_packet'][key]
                                   for key in ('total_laps',) if key in raw['session_packet']}
    if isinstance(raw.get('session_history'), dict):
        history = raw['session_history']
        result['session_history'] = {key: history[key] for key in
            ('car_index', 'num_laps', 'num_tyre_stints', 'tyre_stints_history_data') if key in history}
    result['raw_projection'] = 'compact-v1'
    return result

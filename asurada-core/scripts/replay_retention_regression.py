import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from asurada.replay import ReplayLogger
from regression_support import emit_result


def run():
    checks = {}
    with TemporaryDirectory() as temp:
        root = Path(temp)
        unrelated = root / 'session_log.review.jsonl'
        unrelated.write_text('keep')
        logger = ReplayLogger(root, max_bytes=1, max_archives=2)
        logger.reset()
        with patch('asurada.replay.snapshot_payload', side_effect=lambda state, decision: {'frame': state}):
            class Decision:
                debug = {}
            for frame in range(30):
                logger.append(frame, Decision())
        rows = [json.loads(p.read_text())['frame'] for p in root.glob('session_log*.jsonl') if p != unrelated]
        checks['retains_latest_two_archives_and_current'] = sorted(rows) == [27, 28, 29]
        checks['unrelated_file_preserved'] = unrelated.read_text() == 'keep'
        logger = ReplayLogger(root / 'zero', max_bytes=1, max_archives=0)
        with patch('asurada.replay.snapshot_payload', return_value={'frame': 1}):
            for _ in range(3):
                logger.append(None, Decision())
        checks['zero_keeps_current_only'] = len(list(logger.directory.iterdir())) == 1
        logger = ReplayLogger(root / 'default', max_bytes=1)
        with patch('asurada.replay.snapshot_payload', return_value={'frame': 1}):
            for _ in range(4):
                logger.append(None, Decision())
        checks['default_preserves_all_archives'] = len(list(logger.directory.iterdir())) == 4
        checks['invalid_retention_rejected'] = True
        for value in (-1, True, 1.5, '2'):
            try:
                ReplayLogger(root / 'invalid', max_archives=value)
            except ValueError:
                continue
            checks['invalid_retention_rejected'] = False
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'real temporary filesystem rotation; production retention remains opt-in'}


if __name__ == '__main__':
    emit_result(run())

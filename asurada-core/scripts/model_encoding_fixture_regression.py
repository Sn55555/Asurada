"""Clean-checkout model parity uses explicit fixture evidence, not local paths."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import model_encoding_regression as encoding
from regression_support import emit_result


def run():
    core = Path(__file__).resolve().parents[1]
    fixture = core / 'data/capture_samples/f1_25_udp_frame_fixture.jsonl'
    missing = [{'sample_name': 'external', 'file_path': '/missing-asurada-test-capture.jsonl'}]
    selected = encoding.select_replay_samples(missing, core)
    checks = {
        'missing_external_uses_checked_in_fixture': selected[0][0]['file_path'] == str(fixture),
        'fixture_uses_every_frame': selected[1] == 1,
        'fixture_scope_is_explicit': selected[2] == 'checked_in_frame_fixture',
    }
    present = [{'sample_name': 'recorded', 'file_path': str(fixture)}]
    checks['available_external_replay_kept'] = encoding.select_replay_samples(present, core) == (present, 128, 'external_recorded_capture_samples')
    with TemporaryDirectory() as directory:
        try:
            encoding.select_replay_samples(missing, Path(directory))
            checks['missing_both_sources_rejected'] = False
        except FileNotFoundError:
            checks['missing_both_sources_rejected'] = True
    with patch.object(encoding, 'select_replay_samples', return_value=selected):
        model = encoding.run_regression()
    checks['encoding_report_valid'] = model.get('passed') is True
    if model.get('checks', {}).get('skipped') is True:
        checks['skipped'] = True
        return {'passed': all(checks.values()), 'checks': checks, 'model_evidence': 'unavailable: lightgbm not installed'}
    checks['all_model_checks_pass'] = all(model['checks'].values())
    checks['real_fixture_frames_evaluated'] = model['sampled_frames'] > 0
    checks['report_identifies_fixture_evidence'] = model['replay_evidence'] == 'checked_in_frame_fixture'
    return {'passed': all(checks.values()), 'checks': checks, 'model_report': model}


if __name__ == '__main__':
    emit_result(run())

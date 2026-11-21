from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
from types import SimpleNamespace
from retrain_current_models import run, expected_reports
from asurada.model_admission import MODEL_NAMES
from regression_support import emit_result


def check():
    checks = {}
    with TemporaryDirectory() as directory:
        root = Path(directory); dataset = root/'data'; dataset.mkdir()
        with patch('retrain_current_models.subprocess.run') as launch:
            try: run(dataset, root/'missing'); checks['incomplete_data_rejected'] = False
            except FileNotFoundError: checks['incomplete_data_rejected'] = not launch.called
        occupied = root/'occupied'; occupied.mkdir(); (occupied/'existing').write_text('preserve')
        try: run(dataset, occupied); checks['prior_results_preserved'] = False
        except ValueError: checks['prior_results_preserved'] = (occupied/'existing').read_text() == 'preserve'
        # Isolate orchestration after validation; data validator has separate real-export tests.
        with patch('retrain_current_models.validate_export', return_value={'passed': True}), patch('retrain_current_models.subprocess.run', return_value=SimpleNamespace(returncode=7)) as launch:
            result = run(dataset, root/'failed')
        saved = json.loads((root/'failed/retraining-report.json').read_text())
        checks['failed_stage_stops_later_training'] = not result['passed'] and launch.call_count == 1 and saved['stages'][0]['exit_code'] == 7
        checks['expected_assets_match_runtime_registry'] = set(expected_reports(root).values()) == MODEL_NAMES
        wrong = root/'wrong-assets'
        def fake_training(*args, **kwargs):
            for index in range(14):
                (wrong/f'wrong_{index}_report.json').write_text(json.dumps({'model_path':'not-a-model'}))
            return SimpleNamespace(returncode=0)
        with patch('retrain_current_models.validate_export', return_value={'passed': True}), patch('retrain_current_models.subprocess.run', side_effect=fake_training):
            result=run(dataset,wrong)
        checks['fourteen_wrong_reports_not_success'] = not result['passed'] and result['error'].startswith('ValueError: runtime_asset_reports_mismatch:')
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__': emit_result(check())

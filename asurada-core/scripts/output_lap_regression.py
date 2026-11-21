"""Public lap rendering remains callable after speech components are separated."""
from contextlib import redirect_stdout
from io import StringIO

from asurada.analysis import LapAnalysisSummary
from asurada.output import ConsoleLapSummaryOutput
from regression_support import emit_result


def run():
    renderer = ConsoleLapSummaryOutput()
    empty = StringIO()
    with redirect_stdout(empty):
        renderer.emit(LapAnalysisSummary(0., 0., 0, 0, 0, 0))
    populated = StringIO()
    with redirect_stdout(populated):
        renderer.emit(LapAnalysisSummary(300., 60., 3, 2, 1, 4, driver_style_summary=['stable']))
    text = populated.getvalue()
    checks = {
        'empty_lap_render_callable': '[ASURADA][LAP]' in empty.getvalue(),
        'highest_speed': '最高车速: 300 km/h' in text,
        'lowest_speed': '最低车速: 60 km/h' in text,
        'braking_count': '重刹事件: 3' in text,
        'risk_count': '姿态不稳事件: 2' in text,
        'driver_style': 'stable' in text,
        'lock_released_after_render': renderer._output_lock.acquire(blocking=False),
    }
    if checks['lock_released_after_render']:
        renderer._output_lock.release()
    return dict(passed=all(checks.values()), checks=checks)


if __name__ == '__main__':
    emit_result(run())

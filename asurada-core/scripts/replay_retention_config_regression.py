import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from regression_support import emit_result
from asurada.config import AppConfig
from asurada.app import AsuradaApp
from asurada import __main__ as cli


def run():
    seen = []
    class FakeApp:
        def __init__(self, config, **kwargs): seen.append(config.replay_log_max_archives)
        def run_replay(self, *args, **kwargs): pass
        def run_live_udp(self, *args, **kwargs): pass
    class FakeSpeech:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    with patch.object(cli, 'AsuradaApp', FakeApp), patch('asurada.live_speech.LiveSpeechService', FakeSpeech):
        for args in (['--demo'], ['--demo', '--replay-log-max-archives', '0'], ['--live-udp', '--replay-log-max-archives', '3']):
            with patch('sys.argv', ['asurada'] + args): cli.main()
        with patch('sys.argv', ['asurada', '--replay-log-max-archives', '-1']), contextlib.redirect_stderr(io.StringIO()):
            try: cli.main()
            except SystemExit as exc: negative_rejected = exc.code == 2
            else: negative_rejected = False
    checks = {'cli_default_preserves_archives': seen[0] is None,
              'cli_zero_forwarded': seen[1] == 0,
              'live_cli_forwarded': seen[2] == 3,
              'invalid_cli_before_app_creation': negative_rejected and len(seen) == 3}
    with TemporaryDirectory() as temp, patch('asurada.app.StrategyEngine'):
        app = AsuradaApp(AppConfig(replay_log_dir=Path(temp), replay_log_max_archives=2), voice_output=object())
        checks['app_constructs_real_logger_with_retention'] = app.logger.max_archives == 2
    for value in (-1, True, '2'):
        try: AppConfig(replay_log_max_archives=value)
        except ValueError: checks['invalid_config_' + repr(value)] = True
        else: checks['invalid_config_' + repr(value)] = False
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'CLI dispatch uses fake live service; App constructs real logger in temporary directory; no UDP listener or user log deletion'}


if __name__ == '__main__': emit_result(run())

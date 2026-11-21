import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch
from regression_support import emit_result
from asurada.live_speech import LiveSpeechService, live_speech_client
from asurada.speech_client import SharedSpeechClient
from asurada.speech_client import make_voice_output
from asurada.output import ConsoleVoiceOutput
from asurada.tts_backends import NullSpeechBackend
from asurada import __main__ as cli
import phase3_macos_voice_loop as voice


def run():
    checks = {}
    env = dict(os.environ, ASURADA_TTS_BACKEND='null')
    env.pop('ASURADA_SPEECH_SOCKET', None)
    with TemporaryDirectory(dir='/tmp', prefix='asurada-live-owner-') as directory, patch.dict(os.environ, env, clear=True):
        path = Path(directory)/'speech.sock'
        owner = LiveSpeechService(path=path)
        with owner as client:
            pid = client.health()['pid']
            checks['default_manager_spawns_real_null_service'] = pid==owner.process.pid and client.health()['backend']=='NullSpeechBackend'
            with LiveSpeechService(path=path) as attached:
                checks['second_launcher_reuses_owner'] = attached.health()['pid']==pid
            checks['attached_exit_keeps_service_alive'] = owner.process.poll() is None and client.health()['pid']==pid
            try:
                with LiveSpeechService(path=path, session_source=Path(directory)/'latest_snapshot.json'): pass
                checks['reuse_rejects_wrong_authority'] = False
            except ValueError as exc:
                checks['reuse_rejects_wrong_authority'] = 'session_source_mismatch' in str(exc)
            with patch('asurada.live_speech.default_speech_socket', lambda:path):
                checks['voice_default_uses_same_owner'] = live_speech_client().health()['pid']==pid
            with patch.dict(os.environ, ASURADA_SPEECH_SOCKET=str(path)):
                with LiveSpeechService() as external:
                    checks['explicit_external_owner_attached'] = external.health()['pid']==pid
        checks['owned_shutdown_confirmed'] = owner.shutdown_confirmed and owner.process.poll()==0 and not path.exists()
        with patch.dict(os.environ, ASURADA_SPEECH_SOCKET=str(path)), patch('asurada.live_speech.subprocess.Popen') as spawn:
            try:
                with LiveSpeechService(): pass
                checks['missing_external_never_spawns_fallback'] = False
            except FileNotFoundError:
                checks['missing_external_never_spawns_fallback'] = not spawn.called
        # Exercise real CLI selection, manager and IPC; replace only the game loop.
        seen = []
        class App:
            def __init__(self, config, *, voice_output=None): self.speech=voice_output
            def run_live_udp(self, config, **kwargs):
                health = self.speech.health()
                seen.append((isinstance(self.speech, SharedSpeechClient), health['pid'], config.port, health['session_source']))
        with patch('asurada.live_speech.default_speech_socket', lambda:path), patch.object(cli, 'AsuradaApp', App), patch('sys.argv', ['asurada','--live-udp','--udp-port','21999']):
            cli.main()
        checks['live_cli_defaults_to_managed_shared_service'] = len(seen)==1 and seen[0][0] and seen[0][2]==21999 and not path.exists()
        checks['live_cli_pins_core_publication'] = seen[0][3] == str((cli.AppConfig().replay_log_dir/'latest_snapshot.json').resolve())
        with patch.dict(os.environ, ASURADA_SPEECH_SOCKET=str(path)), patch('sys.argv', ['voice']), patch.object(voice, 'wait_for_state_and_message') as load:
            checks['voice_missing_service_fails_before_capture'] = voice.main()==2 and not load.called
        # Offline demo does not acquire the live service or contact its socket.
        class Offline:
            def __init__(self, config, **kwargs): seen.append(kwargs)
            def run_replay(self, path): seen.append('replay')
        with patch.object(cli, 'AsuradaApp', Offline), patch('asurada.live_speech.LiveSpeechService') as manager, patch('sys.argv', ['asurada','--demo']):
            cli.main()
            checks['offline_entry_does_not_start_live_owner'] = not manager.called and seen[-1]=='replay' and seen[-2]=={'shared_speech':False}
        with patch.dict(os.environ, ASURADA_SPEECH_SOCKET=str(path)):
            offline = make_voice_output(shared=False, backend_factory=NullSpeechBackend)
            checks['offline_factory_ignores_live_socket'] = isinstance(offline, ConsoleVoiceOutput)
            offline.shutdown()
        class Unconfirmed:
            pid = -1
            terminated = False
            def poll(self): return None
            def terminate(self): self.terminated=True
            def wait(self, timeout): raise subprocess.TimeoutExpired('speech',timeout)
        pending = LiveSpeechService(path=path, shutdown_timeout_s=.01)
        pending.process = Unconfirmed()
        checks['unconfirmed_owner_not_force_killed'] = pending.close() is False and pending.process.terminated and pending.shutdown_confirmed is False
    return dict(passed=all(checks.values()), checks=checks)


if __name__=='__main__': emit_result(run())

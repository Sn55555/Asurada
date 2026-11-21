"""Lifecycle of the speech service used by the live CLI.

An explicit socket attaches to an external service. Without one, the live CLI
starts the per-user service, or attaches to its existing owner. Only a child we
started is asked to exit; unconfirmed playback shutdown is never force-killed.
"""
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from .speech_client import SharedSpeechClient


def default_speech_socket():
    return Path('/tmp') / f'asurada-speech-{os.getuid()}' / 'voice.sock'


def live_speech_client():
    return SharedSpeechClient(os.getenv('ASURADA_SPEECH_SOCKET') or default_speech_socket())


class LiveSpeechService:
    def __init__(self, *, path=None, startup_timeout_s=3., shutdown_timeout_s=3., session_source=None):
        configured = os.getenv('ASURADA_SPEECH_SOCKET')
        self.path = Path(path or configured or default_speech_socket())
        self.external = path is None and bool(configured)
        self.startup_timeout_s = startup_timeout_s
        self.shutdown_timeout_s = shutdown_timeout_s
        self.process = None
        self.client = None
        self.shutdown_confirmed = None
        self.session_source = Path(session_source).resolve() if session_source is not None else None

    def _connect(self, timeout_s=1.):
        client = SharedSpeechClient(self.path, timeout_s=timeout_s)
        health = client.health()
        if self.session_source is not None and health.get('session_source') != str(self.session_source):
            raise ValueError('speech_service_session_source_mismatch')
        if 'ASURADA_PERSONALITY_ENABLED' in os.environ:
            enabled = os.getenv('ASURADA_PERSONALITY_ENABLED') == '1'
            humor = enabled and os.getenv('ASURADA_HUMOR_ENABLED', '1') != '0'
            if (health.get('personality_enabled'), health.get('humor_enabled')) != (enabled, humor):
                raise ValueError('speech_service_personality_configuration_mismatch')
        return client

    def __enter__(self):
        if self.external:
            self.client = self._connect()
            return self.client
        directory = self.path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('speech_directory_must_be_private_and_owned')
        try:
            self.client = self._connect()
            return self.client
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        env = dict(os.environ)
        if not env.get('ASURADA_TTS_BACKEND') and env.get('ASURADA_DISABLE_LOCAL_VOICE_OUTPUT', '').lower() in {'1','true','yes','on'}:
            env['ASURADA_TTS_BACKEND'] = 'null'
        command = [sys.executable, '-m', 'asurada.speech_service', '--socket', str(self.path)]
        if self.session_source is not None:
            command += ['--session-source', str(self.session_source)]
        self.process = subprocess.Popen(
            command,
            env=env, stdout=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + self.startup_timeout_s
        try:
            while time.monotonic() < deadline:
                try:
                    self.client = self._connect(timeout_s=min(.1, max(.001, deadline-time.monotonic())))
                    self.client.timeout_s = 1.
                    return self.client
                except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
                    if self.process.poll() is not None:
                        # A competing launcher may have won the service lock.
                        self.client = self._connect()
                        return self.client
                    time.sleep(.02)
            raise TimeoutError('speech_service_startup_timeout')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is None or self.process.poll() is not None:
            self.shutdown_confirmed = True
            return True
        self.process.terminate()
        try:
            self.process.wait(timeout=self.shutdown_timeout_s)
        except subprocess.TimeoutExpired:
            self.shutdown_confirmed = False
            return False
        self.shutdown_confirmed = self.process.returncode == 0
        return self.shutdown_confirmed

    def __exit__(self, *args):
        if not self.close():
            print(f'[ASURADA][SPEECH] shutdown_unconfirmed pid={self.process.pid} socket={self.path}', file=sys.stderr)

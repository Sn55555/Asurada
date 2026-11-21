"""Per-playback cancellation for owned player processes and HTTP response streams."""
from __future__ import annotations
import subprocess
import threading
from typing import Any


class PlaybackCancelled(Exception):
    pass


class PlaybackControl:
    def __init__(self) -> None:
        self.event=threading.Event()
        self._lock=threading.Lock()
        self._players: list[Any]=[]
        self._response: Any=None

    def check(self) -> None:
        if self.event.is_set():raise PlaybackCancelled('playback_cancelled')

    def attach_player(self, player: Any) -> None:
        with self._lock:
            self._players.append(player)
            cancelled=self.event.is_set()
        if cancelled:
            self._stop_player(player)
            self.check()

    def attach_response(self, response: Any) -> None:
        with self._lock:
            self._response=response
            cancelled=self.event.is_set()
        if cancelled:
            response.close()
            self.check()

    @staticmethod
    def _stop_player(player: Any) -> None:
        if player.poll() is not None:return
        try:player.terminate()
        except ProcessLookupError:return
        try:player.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            player.kill()
            player.wait(timeout=.2)

    def cancel(self) -> None:
        with self._lock:
            if self.event.is_set():return
            self.event.set()
            players=list(self._players);response=self._response
        # Closing a buffered HTTP reader can wait on a read lock: never block
        # the scheduler's cancellation request while performing resource cleanup.
        def close():
            for player in players:self._stop_player(player)
            if response is not None:
                try:response.close()
                except OSError:pass
        threading.Thread(target=close,name='playback-cancel',daemon=True).start()

    def cleanup_players(self) -> None:
        with self._lock:players=list(self._players)
        for player in players:self._stop_player(player)

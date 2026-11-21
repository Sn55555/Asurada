"""Independent queue progress for periods without telemetry or user turns."""
from __future__ import annotations
from collections import deque
import threading
from typing import Any


class SpeechOutputDriver:
    def __init__(self, output: Any, *, interval_s: float = .02) -> None:
        self.output=output
        self.interval=max(.005,interval_s)
        self._stop=threading.Event()
        self.events=deque(maxlen=128)
        self.last_error: str | None=None
        self._thread=threading.Thread(target=self._run,name='speech-scheduler-clock',daemon=True)

    def __enter__(self):
        if not getattr(self.output,"externally_driven",False):self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                event=self.output.tick()
                if event['event']['event_type']!='idle':self.events.append(event)
            except Exception as exc:
                self.last_error=f'{type(exc).__name__}: {exc}'
                self._stop.set()

    def close(self) -> bool:
        if getattr(self.output,"externally_driven",False):return self.output.shutdown()
        self._stop.set()
        self._thread.join(timeout=1)
        return self.output.shutdown() and not self._thread.is_alive()

    def __exit__(self,*args):
        if not self.close():
            self.last_error=self.last_error or 'speech_shutdown_unconfirmed'

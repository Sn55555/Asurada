"""Exact wake-qualified stop commands for the concurrent recognition path."""
import re
from .capability_definitions import CAPABILITIES


def _normalize(text):
    return re.sub(r'[\s，。！？、,.!?：:]+', '', str(text or '').lower())


class SpokenStopRouter:
    def __init__(self, *, wake_phrases, on_stop):
        self.wake_phrases = tuple(_normalize(value) for value in wake_phrases if _normalize(value))
        if not self.wake_phrases:
            raise ValueError('spoken_stop_requires_wake_phrase')
        self.on_stop = on_stop

    def accept(self, result):
        # Partial recognition can change meaning as more audio arrives.
        if result.status != 'recognized':
            return False
        text = _normalize(result.transcript_text)
        aliases = {_normalize(alias) for name in ('stop', 'cancel')
                   for alias in CAPABILITIES[name].fast_aliases}
        if not any(text == wake + alias for wake in self.wake_phrases for alias in aliases):
            return False
        self.on_stop()
        return True

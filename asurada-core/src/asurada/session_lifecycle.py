"""Snapshot lifecycle using the non-rewinding overall frame counter when present."""
from __future__ import annotations

from .retired_identities import RetiredIdentities
from dataclasses import dataclass
import math
from .models import SessionState
from .frame_counter import newer, older


@dataclass(frozen=True)
class SessionTransition:
    accepted: bool
    changed: bool
    reason: str
    session_uid: str
    epoch: int


class SessionLifecycle:
    def __init__(self) -> None:
        self.scope: tuple[str, int] | None = None
        self._overall: int | None = None
        self._frame: int | None = None
        # Preserve every retired UID; spill to disk after the memory bound.
        self._retired = RetiredIdentities()

    def observe(self, state: SessionState) -> SessionTransition:
        overall = state.raw.get('overall_frame_identifier')
        frame = state.raw.get('frame_identifier')
        def counter(value):
            return int(value) if not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and float(value).is_integer() and 0<=value<=0xffffffff else None
        overall,frame=counter(overall),counter(frame)
        incoming = (state.session_uid, state.session_epoch)
        if isinstance(incoming[1],bool) or not isinstance(incoming[1],int) or incoming[1]<0:
            return SessionTransition(False,False,'invalid_epoch',state.session_uid,self.scope[1] if self.scope else 0)
        if self.scope is not None and incoming[0]!=self.scope[0] and incoming[0] in self._retired:
            return SessionTransition(False,False,'retired_session',state.session_uid,self.scope[1])
        changed = self.scope is None or incoming[0] != self.scope[0]
        reason = 'session_started' if changed else 'snapshot'
        epoch = incoming[1] if changed else self.scope[1]
        if not changed:
            if incoming[1]<epoch and state.session_epoch_explicit:
                return SessionTransition(False,False,'stale_epoch',state.session_uid,epoch)
            if incoming[1] > epoch:
                changed, reason, epoch = True, 'epoch_changed', incoming[1]
            elif overall is not None and self._overall is not None:
                if older(overall, self._overall):
                    return SessionTransition(False, False, 'out_of_order', state.session_uid, epoch)
                if newer(overall, self._overall) and frame is not None and self._frame is not None and older(frame, self._frame):
                    changed, reason, epoch = True, 'rewind', epoch + 1
        if self.scope is not None and self.scope[0]!=state.session_uid:
            self._retired.add(self.scope[0])
        self.scope = (state.session_uid, epoch)
        self._overall = overall if changed or overall is not None else self._overall
        self._frame = frame if changed or frame is not None else self._frame
        state.session_epoch = epoch
        state.session_epoch_explicit = True
        return SessionTransition(True, changed, reason, state.session_uid, epoch)

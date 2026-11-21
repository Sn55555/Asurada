"""Event-triggered bounded planner; only current, unexpired results are usable."""
from concurrent.futures import Future
from copy import deepcopy
import hashlib
import json
import time

from .task_runtime import BoundedTaskExecutor, TaskContext, TaskCancelled


def planning_event_key(state, route, policy):
    payload = {
        'scope': [state.session_uid, state.session_epoch, state.track],
        'lap': [state.lap_number, state.total_laps],
        'weather': state.weather, 'safety_car': state.safety_car,
        'tyres': [state.player.tyre.compound, state.player.tyre.age_laps],
        'position': state.player.position,
        'rivals': sorted((r.car_index, r.position, r.pit_status, r.tyre.compound) for r in state.rivals),
        'route': [route.session_mode, route.allow_race_resource_actions],
        'policy': policy.snapshot(),
        'assessment': vars(state.assessment.labels) if state.assessment else None,
        'events': {key: state.raw.get(key) for key in (
            'pit_status', 'pit_lane_timer_active', 'num_pit_stops',
            'weather_forecast_samples', 'session_history_summary', 'session_history', 'tyre_rule_settings', 'tyre_sets')},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class PlanningLane:
    def __init__(self, *, refresh_s=1., ttl_s=2., clock=time.monotonic):
        if refresh_s <= 0 or ttl_s < refresh_s:
            raise ValueError('planner_ttl_must_cover_refresh')
        self.refresh_s, self.ttl_s, self.clock = refresh_s, ttl_s, clock
        self._executor = BoundedTaskExecutor(1)
        self._future: Future | None = None
        self._context = None
        self._key = None
        self._latest = None
        self._submitted = float('-inf')
        self._closed = False
        self._counts = dict(submitted=0, failed=0, cancelled=0, busy_skipped=0)
        self._error = None

    def reopen(self):
        self._closed = False
        self._key = self._latest = None
        self._submitted = float('-inf')

    def _collect(self):
        if self._future is not None and self._future.done():
            try:
                self._latest = self._future.result()
            except TaskCancelled:
                self._counts['cancelled'] += 1
            except Exception as exc:
                self._error = f'{type(exc).__name__}: {exc}'
                self._counts['failed'] += 1
            self._future = self._context = None

    def offer(self, *, key, binding, build_work):
        now = self.clock()
        if key != self._key:
            if self._context is not None:
                self._context.cancel()
            self._key, self._latest = key, None
            self._submitted = float('-inf')
        self._collect()
        if not self._closed and now - self._submitted >= self.refresh_s:
            if self._future is not None:
                self._counts['busy_skipped'] += 1
            else:
                self._submitted = now
                context = TaskContext.start(f'planner:{key}', self.ttl_s * 1000)
                try:
                    owned_binding = deepcopy(binding)
                    work = build_work(context)
                    def run():
                        return dict(key=key, binding=owned_binding, submitted=now, results=work())
                    self._future = self._executor.submit(context, run)
                    self._context = context
                    self._counts['submitted'] += 1
                except Exception as exc:
                    self._error = f'{type(exc).__name__}: {exc}'
                    self._counts['failed'] += 1
        latest = self._latest
        valid = latest is not None and latest['key'] == key and 0 <= now-latest['submitted'] <= self.ttl_s
        return dict(latest=deepcopy(latest) if valid and not self._closed else None,
                    counts=dict(self._counts), inflight=self._future is not None,
                    last_error=self._error, ttl_s=self.ttl_s)

    def close(self):
        self._closed = True
        self._latest = None
        if self._context is not None:
            self._context.cancel()
        self._collect()
        return self._future is None

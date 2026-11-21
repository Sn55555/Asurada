from threading import Event
from unittest.mock import patch
from dataclasses import asdict
import time

from regression_support import emit_result
from observation_lane_regression import eventually
from phase1_rival_pit_window_support_regression import _build_state
from asurada.planning_lane import PlanningLane, planning_event_key
from asurada.config import StrategyThresholds
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from asurada.strategy import StrategyEngine


def run():
    checks = {}
    now = [0.]
    lane = PlanningLane(clock=lambda: now[0])
    binding = dict(session_uid='a', epoch=0, snapshot_id='s')
    calls = []
    def fast(context):
        calls.append(1)
        return lambda: {'score': 42}
    def offer(key='one', build=fast):
        return lane.offer(key=key, binding=binding, build_work=build)
    offer()
    checks['first_result_available'] = eventually(lambda: offer()['latest'] is not None)
    for _ in range(20):
        offer()
    checks['same_event_reuses_result'] = len(calls) == 1
    now[0] = 1.1
    offer()
    checks['periodic_refresh'] = len(calls) == 2
    eventually(lambda: lane._future.done())
    offer()
    entered, release = Event(), Event()
    def blocked(context):
        def work():
            entered.set()
            release.wait(2)
            return {'score': 99}
        return work
    started = time.monotonic()
    health = offer('two', blocked)
    checks['changed_event_invalidates_immediately'] = health['latest'] is None
    checks['slow_plan_nonblocking'] = time.monotonic()-started < .1 and entered.wait(1)
    now[0] = 10
    checks['inflight_does_not_queue_more_plans'] = offer('two', blocked)['counts']['submitted'] == 3
    checks['changed_scope_hides_old_result'] = offer('three')['latest'] is None
    checks['close_reports_pending'] = not lane.close()
    lane.reopen()
    checks['restart_does_not_duplicate_worker'] = offer('three')['counts']['submitted'] == 3
    release.set()
    checks['restart_eventually_recovers'] = eventually(lambda: offer('three')['latest'] is not None)
    # Block refresh of the same event; cached data expires while replacement runs.
    now[0] = 11.1
    release.clear(); entered.clear()
    offer('three', blocked)
    entered.wait(1)
    now[0] = 13
    checks['same_event_cached_result_expires'] = offer('three', blocked)['latest'] is None
    lane.close(); release.set()
    eventually(lane.close)

    with patch.object(ResourceRiskModelRuntime, '_load'), patch.object(StrategyActionModelRuntime, '_load'):
        engine = StrategyEngine(StrategyThresholds())
    state = _build_state()
    state.raw.update(timing_mode='race_like', timing_support_level='official_preferred', fuel_in_tank=20, fuel_capacity=50)
    baseline = engine.evaluate(state, [state])
    engine.enable_background_planning()
    entered, release = Event(), Event()
    original = engine.pit_window_support.evaluate
    def slow_support(**kwargs):
        entered.set()
        release.wait(2)
        return original(**kwargs)
    engine.pit_window_support.evaluate = slow_support
    started = time.monotonic()
    result = engine.evaluate(state, [state])
    checks['production_strategy_does_not_wait_for_plan'] = time.monotonic()-started < .15 and entered.wait(1)
    checks['pending_observe_plan_preserves_actions'] = [asdict(m) for m in baseline.messages] == [asdict(m) for m in result.messages]
    route = engine.session_mode_router.resolve(state)
    key = planning_event_key(state, route, engine.contributor_policy)
    state.lap_number += 1
    checks['new_lap_triggers_event'] = key != planning_event_key(state, route, engine.contributor_policy)
    state.lap_number -= 1
    state.session_epoch += 1
    checks['rewind_triggers_event'] = key != planning_event_key(state, route, engine.contributor_policy)
    engine.planning_lane.close(); release.set()
    checks['production_worker_exits'] = eventually(engine.planning_lane.close)
    from asurada.contributor_admission import ContributorPolicy, NAMES
    policy = ContributorPolicy(modes={name: 'active' for name in NAMES},
                               evidence={name: 'regression' for name in NAMES})
    with patch.object(ResourceRiskModelRuntime, '_load'), patch.object(StrategyActionModelRuntime, '_load'):
        active = StrategyEngine(StrategyThresholds(), contributor_policy=policy)
    active.enable_background_planning()
    first = active.evaluate(state, [state])
    checks['active_pending_is_not_admitted'] = not first.debug['arbiter_v2']['input']['sidecar_scores']['pit_window_support']
    eventually(lambda: active.planning_lane._future.done())
    ready = active.evaluate(state, [state])
    contribution = ready.debug['arbiter_v2']['input']['sidecar_scores']['pit_window_support']
    checks['active_ready_has_bound_contribution'] = bool(contribution) and contribution['contribution_binding']['epoch'] == state.session_epoch
    from asurada.snapshot_contract import snapshot_payload, restore_decision
    import json
    restored_payload = json.loads(json.dumps(snapshot_payload(state, ready), allow_nan=False))
    restore_decision(state, restored_payload)
    persisted = state.decision_record.arbitration['planner_inputs']['contributions']['pit_window_support']
    checks['background_provenance_survives_snapshot'] = (
        persisted['binding'] == contribution['contribution_binding']
        and persisted['validity'] == contribution['validity'])
    state.weather = 'HeavyRain'
    changed = active.evaluate(state, [state])
    checks['event_change_removes_active_contribution'] = not changed.debug['arbiter_v2']['input']['sidecar_scores']['pit_window_support']
    active.planning_lane.close()
    eventually(active.planning_lane.close)
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

from dataclasses import asdict
from threading import Event
import time
from unittest.mock import patch

from regression_support import emit_result
from phase1_rival_pit_window_support_regression import _build_state
from asurada.config import StrategyThresholds
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from asurada.observation_lane import ObservationLane
from asurada.strategy import StrategyEngine


def eventually(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.002)
    return False


def run():
    checks = {}
    binding = dict(session_uid='a', epoch=0, snapshot_id='s', source_timestamp_ms=1)
    entered, release = Event(), Event()
    lane = ObservationLane(interval_s=0)
    def blocked(context):
        def work():
            entered.set()
            release.wait(2)
            return {'value': 1}
        return work
    started = time.monotonic()
    lane.offer(binding=binding, build_work=blocked)
    checks['submission_does_not_wait_for_model'] = time.monotonic()-started < .1 and entered.wait(1)
    calls = []
    def fast(context):
        calls.append(1)
        return lambda: {'value': 2}
    for _ in range(10):
        health = lane.offer(binding=binding, build_work=fast)
    checks['busy_has_no_queue_or_snapshot_copy'] = not calls and health['counts']['busy_skipped'] == 10
    checks['close_reports_unfinished_worker'] = not lane.close()
    lane.reopen()
    lane.offer(binding=binding, build_work=fast)
    checks['restart_retains_old_worker_ownership'] = not calls
    release.set()
    checks['restart_recovers_after_old_worker_finishes'] = eventually(
        lambda: lane.offer(binding=binding, build_work=fast)['counts']['submitted'] > 1)
    lane.close()

    lane = ObservationLane(interval_s=100, result_ttl_s=1)
    lane.offer(binding=binding, build_work=fast)
    checks['completed_result_available'] = eventually(
        lambda: lane.offer(binding=binding, build_work=fast)['latest'] is not None)
    result = lane.offer(binding=binding, build_work=fast)
    result['latest']['results']['value'] = 99
    checks['diagnostic_result_has_separate_ownership'] = lane.offer(binding=binding, build_work=fast)['latest']['results']['value'] == 2
    other = dict(binding, epoch=1)
    checks['old_epoch_result_hidden'] = lane.offer(binding=other, build_work=fast)['latest'] is None
    lane.close()

    lane = ObservationLane(interval_s=100, result_ttl_s=0)
    lane.offer(binding=binding, build_work=fast)
    eventually(lambda: lane._future.done())
    checks['expired_diagnostic_hidden'] = lane.offer(binding=binding, build_work=fast)['latest'] is None
    lane.close()

    lane = ObservationLane()
    def broken(context):
        raise ValueError('bad snapshot')
    health = lane.offer(binding=binding, build_work=broken)
    checks['preparation_failure_isolated'] = health['counts']['failed'] == 1 and 'bad snapshot' in health['last_error']
    lane.close()

    # Drive the actual strategy entry, not only the helper lane. A blocked
    # observed inference must not affect actions or prevent a second frame.
    with patch.object(ResourceRiskModelRuntime, '_load'), patch.object(StrategyActionModelRuntime, '_load'):
        engine = StrategyEngine(StrategyThresholds())
        baseline_engine = StrategyEngine(StrategyThresholds())
    engine.enable_background_observations()
    model = engine.resource_risk_runtime._runtimes["ers_risk"]
    entered, release = Event(), Event()
    def slow(**kwargs):
        entered.set()
        release.wait(2)
        return {'enabled': True, 'score': 100}
    model.predict_score = slow
    state = _build_state()
    state.raw.update(timing_mode='race_like', timing_support_level='official_preferred', fuel_in_tank=20, fuel_capacity=50)
    baseline = baseline_engine.evaluate(state, [state])
    started = time.monotonic()
    decision = engine.evaluate(state, [state])
    checks['live_strategy_returns_while_observed_model_blocked'] = time.monotonic()-started < .15 and entered.wait(1)
    checks['live_observe_matches_offline_actions'] = [asdict(m) for m in decision.messages] == [asdict(m) for m in baseline.messages]
    engine.evaluate(state, [state])
    checks['repeated_live_frame_keeps_one_observer'] = engine.observation_lane._counts['submitted'] == 1
    engine.observation_lane.close()
    release.set()
    checks['strategy_observer_exits'] = eventually(engine.observation_lane.close)
    from asurada.model_admission import ModelAdmissionPolicy
    from threading import get_ident
    # This fixture isolates worker routing, not real active model admission.
    policy = ModelAdmissionPolicy(modes={'ers_risk': 'active'}, evidence={'ers_risk': 'regression'},
                                  context_window_version='source-time-weighted-v1')
    with patch.object(ResourceRiskModelRuntime, '_load'), patch.object(StrategyActionModelRuntime, '_load'), patch.object(ModelAdmissionPolicy, 'validate_assets', return_value={}):
        active_engine = StrategyEngine(StrategyThresholds(), model_policy=policy)
    active_engine.enable_background_observations()
    thread_ids = []
    def active_predict(**kwargs):
        thread_ids.append(get_ident())
        return {'enabled': True, 'score': 1}
    active_engine.resource_risk_runtime._runtimes['ers_risk'].predict_score = active_predict
    scores = active_engine._predict_group(active_engine.resource_risk_runtime, state=state, context={})
    checks['active_prediction_remains_synchronous'] = thread_ids == [get_ident()] and scores['ers_risk']['score'] == 1
    active_engine.observation_lane.close()
    return {'passed': all(checks.values()), 'checks': checks}


if __name__ == '__main__':
    emit_result(run())

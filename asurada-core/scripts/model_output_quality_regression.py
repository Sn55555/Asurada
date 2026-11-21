from unittest.mock import patch
from asurada.config import StrategyThresholds
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
from asurada.model_runtime import StrategyActionModelRuntime
from asurada.strategy import StrategyEngine
from model_encoding_regression import runtimes
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    engine = StrategyEngine(StrategyThresholds(), model_policy=ModelAdmissionPolicy(modes={n: 'observe' for n in MODEL_NAMES}))
    models = runtimes(engine)
    checks = {'all_assets_loaded': len(models) == 14 and all(m.enabled for m in models)}
    if not checks['all_assets_loaded']: return {'passed': False, 'checks': checks}
    state = make_state(); state.raw.update(throttle=0., brake=0., steer=0.)
    context = engine._build_context(state, [state])
    for index, model in enumerate(models):
        action = isinstance(model, StrategyActionModelRuntime)
        call = model.predict_top_k if action else model.predict_score
        invalid = [[], [float('nan')], [float('inf')], [True], ['4'], [[1]], [1, 2]]
        if action:
            n = len(model._target_actions)
            invalid = [[], [[0.] * n], [[float('nan')] * n], [[float('inf')] * n],
                [[True] * n], [[-1.] * n], [[1.1] * n], [[1. / n] * (n + 1)], [[1. / n] * n] * 2]
        for mode in ('observe', 'active'):
            model.mode = mode
            for case, value in enumerate(invalid):
                with patch.object(model._booster, 'predict', return_value=value):
                    result = call(state=state, context=context)
                checks[f'{index}_{mode}_{case}'] = (result == [] and not model.last_output_quality['valid']) if action else (not result['enabled'] and 'score' not in result)
            with patch.object(model._booster, 'predict', side_effect=RuntimeError('fixture prediction failed')):
                result = call(state=state, context=context)
            checks[f'{index}_{mode}_exception'] = result == [] if action else not result['enabled']
            result = call(state=state, context=context)
            checks[f'{index}_{mode}_recovers'] = bool(result) if action else result['enabled']
        model.mode = 'observe'
    model = engine.strategy_action_runtime
    with patch.object(model._booster, 'predict', return_value=[]):
        decision = engine.evaluate(state)
        quality = decision.debug['arbiter_v2']['input']['strategy_action_quality']
        checks['rejection_in_decision_trace'] = quality['output']['reason'] == 'invalid_model_output'
    engine.evaluate(state)
    checks['prior_trace_not_mutated_by_recovery'] = quality['output']['valid'] is False and model.last_output_quality['valid'] is True
    engine.enable_background_observations()
    with patch.object(model._booster, 'predict', return_value=[]):
        engine.evaluate(state)
        future = engine.observation_lane._future
        observed = future.result(timeout=3)
        checks['background_result_has_bound_quality'] = (observed['results']['strategy_action_quality']['output']['reason'] == 'invalid_model_output'
            and observed['binding']['session_uid'] == state.session_uid)
    engine.observation_lane.close()
    return {'passed': all(checks.values()), 'checks': checks,
        'scope': 'real assets with injected raw outputs; active runtime gating only, not asset admission'}


if __name__ == '__main__': emit_result(run())

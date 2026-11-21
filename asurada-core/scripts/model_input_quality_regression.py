from copy import deepcopy
from unittest.mock import patch
import numpy as np
from asurada.config import StrategyThresholds
from asurada.model_admission import ModelAdmissionPolicy, MODEL_NAMES
from asurada.model_runtime import StrategyActionModelRuntime, build_runtime_feature_row
from asurada.model_input_quality import prepare_model_inputs
from asurada.strategy import StrategyEngine
from model_encoding_regression import runtimes
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    engine = StrategyEngine(StrategyThresholds(), model_policy=ModelAdmissionPolicy(
        modes={name: 'observe' for name in MODEL_NAMES}))
    models = runtimes(engine)
    checks = {'all_real_assets_loaded': len(models) == 14 and all(m.enabled for m in models)}
    if not checks['all_real_assets_loaded']:
        return {'passed': False, 'checks': checks}
    state = make_state()
    state.raw.update(throttle=0., brake=0., steer=0.)
    count = 0
    for index, model in enumerate(models):
        action = isinstance(model, StrategyActionModelRuntime)
        watched = [name for name in ('throttle', 'brake', 'steer', 'ers_pct', 'tyre_wear_pct') if name in model._feature_columns]
        for feature in watched:
            for label, invalid in [('missing', None), ('bool', True), ('range', 150)]:
                sample = deepcopy(state)
                if feature == 'ers_pct': sample.player.ers_pct = invalid
                elif feature == 'tyre_wear_pct': sample.player.tyre.wear_pct = invalid
                else: sample.raw[feature] = invalid
                context = engine._build_context(sample, [sample])
                row = model._build_feature_row(state=sample, context=context) if action else build_runtime_feature_row(state=sample, context=context)
                row, quality = prepare_model_inputs(row, model._feature_columns)
                column = model._feature_columns.index(feature)
                checks[f'{index}_{feature}_{label}_nan'] = np.isnan(model._encoder.encode(row)[0, column]) and feature in quality['unavailable_features']
                # Observe mode retains a real inference for analysis only.
                call = model.predict_top_k if action else model.predict_score
                model.mode = 'observe'
                result = call(state=sample, context=context)
                checks[f'{index}_{feature}_{label}_observed'] = bool(result) and (action or feature in result['input_quality']['unavailable_features'])
                # Isolate runtime input gating, not asset admission, by switching
                # the already-loaded instance. An active call must not infer.
                model.mode = 'active'
                with patch.object(model._booster, 'predict', side_effect=AssertionError('invalid active inference')):
                    result = call(state=sample, context=context)
                checks[f'{index}_{feature}_{label}_active_rejected'] = result == [] if action else result['enabled'] is False
                model.mode = 'observe'
                count += 1
        context = engine._build_context(state, [state])
        model.mode = 'active'
        call = model.predict_top_k if action else model.predict_score
        result = call(state=state, context=context)
        checks[f'{index}_valid_zero_accepted'] = bool(result) if action else result['enabled'] is True
        model.mode = 'observe'
    return {'passed': all(checks.values()), 'checks': checks, 'invalid_cases': count,
            'scope': '14 real model assets; runtime input gating, not active admission or live acceptance'}


if __name__ == '__main__': emit_result(run())

"""Generated-column completeness is distinct from a present unknown value."""
from unittest.mock import patch
from asurada.config import StrategyThresholds
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.model_input_quality import prepare_model_inputs
from asurada.model_runtime import StrategyActionModelRuntime,build_runtime_feature_row
from asurada.strategy import StrategyEngine
from asurada.wheel_telemetry import WHEEL_ORDER_VERSION
from model_encoding_regression import runtimes
from phase3_voice_regression import make_state
from regression_support import emit_result


def run():
    engine=StrategyEngine(StrategyThresholds(),model_policy=ModelAdmissionPolicy(modes={name:'observe' for name in MODEL_NAMES}))
    state=make_state();context=engine._build_context(state,[state]);models=runtimes(engine)
    checks={'fourteen_loaded':len(models)==14 and all(m.enabled for m in models)}
    for index,model in enumerate(models):
        action=isinstance(model,StrategyActionModelRuntime)
        row=model._build_feature_row(state=state,context=context) if action else build_runtime_feature_row(state=state,context=context)
        checks[str(index)+'_coverage']=not(set(model._feature_columns)-set(row))
        name=model._feature_columns[0];del row[name]
        for mode in ('active','observe'):
            model.mode=mode
            builder=patch.object(model,'_build_feature_row',return_value=row) if action else patch('asurada.model_runtime.build_runtime_feature_row',return_value=row)
            with builder,patch.object(model._booster,'predict') as predict:
                result=model.predict_top_k(state=state,context=context) if action else model.predict_score(state=state,context=context)
            quality=model.last_input_quality if action else result['input_quality']
            checks[f'{index}_{mode}_no_silent_nan']=not predict.called and name in quality['absent_columns'] and (result==[] if action else result['disabled_reason']=='feature_columns_not_generated')
    state.raw["wheel_slip_ratio"] = [.11, .12, .21, .22]
    columns = [f"wheel_slip_ratio_{wheel}" for wheel in ("rl", "rr", "fl", "fr")]
    row = build_runtime_feature_row(state=state, context=context)
    checks["runtime_wheel_columns_match_wire_order"] = [row[column] for column in columns] == [.11, .12, .21, .22]
    resource = next(model for model in models if not isinstance(model, StrategyActionModelRuntime))
    resource.mode = "observe"
    for version, expected in ((None, [.21, .22, .11, .12]), (WHEEL_ORDER_VERSION, [.11, .12, .21, .22])):
        report = {**resource._report, "training_provenance": {"wheel_order_version": version}}
        with patch.object(resource, "_report", report), patch.object(resource._encoder, "encode") as encode, \
                patch.object(resource._booster, "predict", return_value=[42.0]):
            resource.predict_score(state=state, context=context)
        encoded_row = encode.call_args.args[0]
        checks[f"wheel_columns_for_{version or 'legacy_model'}"] = [encoded_row[column] for column in columns] == expected
    _,quality=prepare_model_inputs({'speed_kph':None},['speed_kph'])
    checks['present_unknown_not_schema_error']=quality['absent_columns']==[]
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

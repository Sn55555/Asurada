from copy import deepcopy
from regression_support import emit_result
from phase3_voice_regression import make_state
from asurada.state import UnifiedStateStore
from asurada.strategy import StrategyEngine
from asurada.context_window import context_samples


def run():
    checks = {}
    engine = object.__new__(StrategyEngine)
    outputs = []
    for hz in (10,20,60):
        store=UnifiedStateStore()
        for index in range(hz+1):
            state=make_state()
            elapsed=index*1000/hz
            state.source_timestamp_ms=100000+elapsed
            state.raw.update(overall_frame_identifier=index,frame_identifier=index,
                throttle=1.0 if elapsed<500 else 0.0,brake=0.,steer=0.)
            state.player.status_tags=['unstable'] if elapsed<500 else []
            assert store.update(state)
        context=engine._build_context(state,store.recent_seconds(1.0))
        outputs.append(context)
        checks[f'{hz}hz_one_second_covered']=abs(context.history_coverage_ms-1000)<1e-8
        checks[f'{hz}hz_half_time_unstable']=abs(context.recent_unstable_ratio-.5)<1e-8
    checks['frequency_independent_driving_context']=len({(x.driving_mode,x.throttle_phase_factor,x.brake_phase_factor) for x in outputs})==1
    early=make_state();early.source_timestamp_ms=100000
    late=deepcopy(early);late.source_timestamp_ms=101000
    _,coverage=context_samples(late,[early,late])
    checks['gap_not_counted_as_full_coverage']=coverage==250
    _,coverage=context_samples(late,[late])
    checks['first_frame_has_no_historical_coverage']=coverage==0
    foreign=deepcopy(early);foreign.session_uid='other'
    future=deepcopy(late);future.source_timestamp_ms+=1
    _,coverage=context_samples(late,[foreign,future,late])
    checks['foreign_and_future_excluded']=coverage==0
    duplicate=deepcopy(early)
    _,coverage=context_samples(late,[early,duplicate,late])
    checks['duplicate_time_does_not_add_weight']=coverage==250
    for value in (None, float('nan'), float('inf'), True, 2.0):
        missing=make_state()
        missing.raw.update(throttle=value,brake=0.,steer=0.)
        context=engine._build_context(missing,[missing])
        checks[f'invalid_{value}_not_zero']=context.driving_mode=='unknown' and context.input_quality['throttle']['quality']=='unavailable'
    zero=make_state();zero.raw.update(throttle=0.,brake=0.,steer=0.)
    context=engine._build_context(zero,[zero])
    checks['actual_zero_remains_observed']=context.driving_mode=='straightline' and context.input_quality['throttle']['quality']=='instantaneous'
    rows=[]
    for index in range(11):
        row=make_state();row.source_timestamp_ms=100000+index*100
        row.raw.update(throttle=1. if index<2 else None,brake=0.,steer=0.)
        rows.append(row)
    context=engine._build_context(rows[-1],rows)
    checks['sparse_throttle_not_promoted_to_window']=context.driving_mode=='unknown' and context.throttle_phase_factor==0 and context.input_quality['throttle']=={'coverage_ms':200.,'quality':'unavailable'}
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

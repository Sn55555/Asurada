"""Source-time weighted short context; gaps are not filled as observations."""
import math
from .input_quality import valid_input

CONTEXT_WINDOW_SECONDS = 1.0
MAX_OBSERVATION_HOLD_MS = 250.0


def input_means(weighted, coverage_ms):
    means, quality = {}, {}
    for name in ('throttle','brake','steer'):
        total = weight_sum = 0.0
        for state, weight in weighted:
            value = valid_input(name, state.raw.get(name))
            if value is None:
                continue
            total += (abs(value) if name=='steer' else value)*weight
            weight_sum += weight
        sufficient = weight_sum>0 and (coverage_ms==0 or weight_sum>=coverage_ms*.5)
        means[name] = total/weight_sum if sufficient else None
        quality[name] = {'coverage_ms':min(weight_sum,coverage_ms),
            'quality':('instantaneous' if coverage_ms==0 else 'observed' if weight_sum==coverage_ms else 'partial') if sufficient else 'unavailable'}
    return means, quality


def context_samples(state, history):
    end = state.source_timestamp_ms
    cutoff = end-CONTEXT_WINDOW_SECONDS*1000
    rows = []
    for item in history:
        timestamp = item.source_timestamp_ms
        if (item.session_uid, item.session_epoch) != (state.session_uid, state.session_epoch):
            continue
        if not isinstance(timestamp,(int,float)) or isinstance(timestamp,bool) or not math.isfinite(timestamp):
            continue
        if cutoff <= timestamp <= end and (not rows or timestamp > rows[-1].source_timestamp_ms):
            rows.append(item)
    if not rows or rows[-1].source_timestamp_ms < end:
        rows.append(state)
    weighted = [(left, min(right.source_timestamp_ms-left.source_timestamp_ms, MAX_OBSERVATION_HOLD_MS))
                for left,right in zip(rows,rows[1:])]
    coverage = sum(weight for _,weight in weighted)
    # An instantaneous first frame remains usable, explicitly without history.
    return (weighted if coverage else [(state,1.0)]), coverage

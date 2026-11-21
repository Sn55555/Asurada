"""Validate raw model results before ranking or score clipping."""
import math
from numbers import Real


def finite_number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def probability_row(prediction, classes):
    if len(prediction) != 1 or len(prediction[0]) != classes:
        raise ValueError('invalid_probability_shape')
    values = list(prediction[0])
    if not all(finite_number(v) and 0 <= v <= 1 for v in values):
        raise ValueError('invalid_probability_values')
    if not math.isclose(sum(values), 1., rel_tol=1e-5, abs_tol=1e-5):
        raise ValueError('invalid_probability_total')
    return values


def regression_score(prediction):
    if len(prediction) != 1 or not finite_number(prediction[0]):
        raise ValueError('invalid_regression_output')
    return float(prediction[0])

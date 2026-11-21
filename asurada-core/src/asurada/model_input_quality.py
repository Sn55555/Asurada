"""Physical input validation before either model encoder path."""
from .input_quality import valid_input
from .assessment import valid_percentage

VERSION = 'physical-inputs-v1'
CONTROLS = ('throttle', 'brake', 'steer')
PERCENTAGES = ('ers_pct', 'tyre_wear_pct')


def prepare_model_inputs(row, columns):
    row = dict(row)
    absent = sorted(set(columns)-set(row))
    missing = []
    for name in (*CONTROLS, *PERCENTAGES):
        if name not in columns:
            continue
        value = (valid_input(name, row.get(name)) if name in CONTROLS
                 else valid_percentage(row.get(name)))
        row[name] = value
        if value is None:
            missing.append(name)
    return row, {'version': VERSION, 'unavailable_features': missing, 'absent_columns': absent}

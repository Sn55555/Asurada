"""Canonical safety-car status; unavailable is distinct from no intervention."""
SAFETY_CAR_NAMES = {0: 'NONE', 1: 'FULL', 2: 'VSC', 3: 'FORMATION'}


def normalize_race_control(value):
    return value if isinstance(value, str) and value in SAFETY_CAR_NAMES.values() else None


def decode_race_control(value):
    return SAFETY_CAR_NAMES.get(value) if type(value) is int else None


def race_control_active(value):
    return normalize_race_control(value) in ('FULL', 'VSC', 'FORMATION')


def describe_race_control(value):
    value = normalize_race_control(value)
    if value is None:
        return '赛道管制数据不可用'
    return '无赛道管制' if value == 'NONE' else f'{value} 阶段'

"""F1 25 wire-order wheel values and the tyre damage advisory threshold."""
from __future__ import annotations

import math

WHEEL_INDEX = {"rl": 0, "rr": 1, "fl": 2, "fr": 3}
WHEEL_ORDER_VERSION = "f1-wire-rl-rr-fl-fr-v1"
WHEEL_NAMES = {"rl": "左后轮", "rr": "右后轮", "fl": "左前轮", "fr": "右前轮"}
TYRE_DAMAGE_WARNING_PCT = 35
TYRE_WEAR_ALERT = "TYRE_WEAR_ALERT"
TYRE_DAMAGE = "TYRE_DAMAGE"
_WHEEL_POSITIONS = {"rl": "左后", "rr": "右后", "fl": "左前", "fr": "右前"}
_DIGITS = "零一二三四五六七八九"


def wheel_value(values, wheel: str) -> float | None:
    index = WHEEL_INDEX[wheel]
    if not isinstance(values, (list, tuple)) or len(values) <= index:
        return None
    value = values[index]
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    return None


def tyre_damage_values(values) -> dict[str, float]:
    result = {}
    for wheel in WHEEL_INDEX:
        value = wheel_value(values, wheel)
        if value is not None and 0 <= value <= 100:
            result[wheel] = value
    return result


def spoken_percent(value):
    number = round(value)
    if number == 100:
        return "百分之一百"
    tens, ones = divmod(number, 10)
    if tens == 0:
        return f"百分之{_DIGITS[ones]}"
    return "百分之" + ("" if tens == 1 else _DIGITS[tens]) + "十" + (_DIGITS[ones] if ones else "")


def tyre_alert(damage_values, wear_values) -> tuple[str, str] | None:
    damage = tyre_damage_values(damage_values)
    wear = tyre_damage_values(wear_values)
    # The game reports damage as an integer and wear as a float. A difference
    # within one point can come from quantization, and missing wear is unknown.
    damaged = {wheel: value for wheel, value in damage.items()
               if wheel in wear and value - wear[wheel] > 1 and value >= TYRE_DAMAGE_WARNING_PCT}
    if damaged:
        wheel = max(damaged, key=damaged.get)
        return TYRE_DAMAGE, f"轮胎受损。{WHEEL_NAMES[wheel]}，{spoken_percent(damaged[wheel])}。"
    if wear and max(wear.values()) >= TYRE_DAMAGE_WARNING_PCT:
        wheel = max(wear, key=wear.get)
        return TYRE_WEAR_ALERT, f"{_WHEEL_POSITIONS[wheel]}这条胎，磨损{spoken_percent(wear[wheel])}。"
    return None

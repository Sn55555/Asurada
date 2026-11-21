"""Normalized driver controls: unknown inputs must not become observed zero."""
import math


def valid_input(name, value):
    lower = -1 if name == 'steer' else 0
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or not lower <= value <= 1):
        return None
    return float(value)


def packet_inputs(telemetry, observed_at_ms):
    values, quality = {}, {}
    for name in ('throttle', 'brake', 'steer'):
        values[name] = valid_input(name, telemetry.get(name))
        quality[name] = dict(source='CarTelemetry', observed_at_ms=observed_at_ms,
            unit='normalized', quality='observed' if values[name] is not None else
            'missing' if telemetry.get(name) is None else 'invalid')
    return values, quality


def marshal_zone_flag(zones, lap_distance_m, track_length_m, *, session_age_ms=0):
    """Match the active official marshal zone, wrapping before the first zone."""
    if (track_length_m <= 0 or lap_distance_m < 0
            or session_age_ms is None or not 0 <= session_age_ms <= 1000):
        return None
    observed = sorted((zone["zone_start"], zone["zone_flag"]) for zone in zones
                      if 0 <= zone.get("zone_start", -1) <= 1 and type(zone.get("zone_flag")) is int)
    if not observed:
        return None
    fraction = (lap_distance_m % track_length_m) / track_length_m
    flag = next((flag for start, flag in reversed(observed) if start <= fraction), observed[-1][1])
    return flag if flag in (0, 1, 2, 3) else None

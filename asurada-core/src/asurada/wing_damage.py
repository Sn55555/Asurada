"""Evidence for a side-specific front-wing warning."""
from math import isfinite

from .assessment import valid_percentage
from .input_quality import valid_input
from .track_model import load_track_profile
from .wheel_telemetry import spoken_percent


FRONT_WING_DAMAGE = "FRONT_WING_DAMAGE"
FRONT_WING_ENTRY_COMPENSATION = "FRONT_WING_ENTRY_COMPENSATION"
FRONT_WING_WARNING_PCT = 30
SIDES = {"front_left": "左前翼", "front_right": "右前翼"}
_STRAIGHTS = {"straight", "deployment_straight", "drs_straight"}
# Reserve time for the whole radio line and a margin before the braking zone.
_CORNER_RADIO_WINDOW_S = (8, 15)
_COMPENSATION_WINDOW_S = (5, 9)
_COMBINED_COMPENSATION_MIN_S = 8
COMPENSATION_TEXT = "入弯前收油，方向慢一点打。"
# Miami's generated profile numbers are sequential feature IDs, not FIA turn numbers.
# Its first and second long straights terminate at T11 and T17 respectively.
_MIAMI_TURNS = {"Main Straight": "一号弯", "Straight 03": "十一号弯", "Straight 04": "十七号弯"}
_MIAMI_LEFT_TURNS = {"Straight 03", "Straight 04"}


def approaching_wing_corner(state, *, playing=False, combined=False):
    """Name a braking point only on its immediately preceding straight."""
    if (state is None or not wing_values(state) or state.safety_car != "NONE"
            or state.raw.get("marshal_zone_flag") not in (None, 0, 1, 2)
            or state.raw.get("pit_status_code", 0) != 0):
        return None
    brake = valid_input("brake", state.raw.get("brake"))
    if brake is None or brake > .1:
        return None
    profile = load_track_profile(state.track)
    distance, speed = state.player.lap_distance_m, state.player.speed_kph
    if (profile is None or type(distance) not in (int, float) or not isfinite(distance)
            or not 0 <= distance < profile.lap_length_m
            or type(speed) not in (int, float) or not isfinite(speed) or speed < 60):
        return None
    segment = next((part for part in profile.semantic_segments if part.start_m <= distance < part.end_m), None)
    if segment is None or segment.zone_type not in _STRAIGHTS:
        return None
    end, wrap = segment.end_m, 0
    first = profile.semantic_segments[0]
    if end == profile.lap_length_m and first.start_m == 0 and first.name == segment.name:
        end, wrap = first.end_m, profile.lap_length_m
    # A fast corner needs both a mapped high-load section and a high-gear apex.
    following = next((part for part in profile.semantic_segments if part.start_m == end), None)
    high_speed = following is not None and following.zone_type == "high_load_management" and any(
        following.start_m <= apex.distance_m < following.end_m
        and apex.recommended_gear is not None and apex.recommended_gear >= 5
        for apex in profile.corner_apexes
    )
    zone = next((item for item in profile.braking_zones if abs(item.start_m - end) <= 15), None)
    if zone is None and not high_speed:
        return None
    entry = min(zone.start_m, end) if zone is not None else end
    seconds = (entry + wrap - distance) / (speed / 3.6)
    first_s, last_s = _COMPENSATION_WINDOW_S if high_speed else _CORNER_RADIO_WINDOW_S
    if high_speed:
        if combined:
            first_s = _COMBINED_COMPENSATION_MIN_S
        if playing:
            first_s = 0
    if not first_s <= seconds <= last_s:
        return None
    label = _MIAMI_TURNS.get(segment.name) if profile.track == "Miami" else None
    damage = state.raw.get("wing_damage_pct", {})
    # This range comes from the dry C4 T11 replay and one matching damage sample.
    entry_reference = (
        label == "十一号弯" and state.weather in {"Clear", "LightCloud", "Overcast"}
        and state.player.tyre.compound == "C4" and damage.get("front_right") == 31
        and damage.get("front_left") == 0 and damage.get("rear") == 0
    )
    return {"track": state.track, "lap": state.lap_number + bool(wrap),
            "braking_zone": zone.name if zone is not None else following.name,
            "label": label or "这条直道末端的弯",
            "direction": "左" if profile.track == "Miami" and segment.name in _MIAMI_LEFT_TURNS else None,
            "entry_reference": entry_reference, "high_speed": high_speed}


def has_wing_compensation(job):
    return job.action_code == FRONT_WING_ENTRY_COMPENSATION or job.metadata.get("wing_compensation") == "combined"


def wing_advice_current(state, job, *, playing=False):
    values = wing_values(state)
    sides = job.metadata.get("wing_sides", ())
    reported = job.metadata.get("wing_levels", {})
    corner = job.metadata.get("wing_corner")
    return (bool(sides) and all(values.get(side) is not None and values[side] >= FRONT_WING_WARNING_PCT
                                and values[side] == reported.get(side, values[side])
                                for side in sides)
            and (not has_wing_compensation(job) or compensation_allowed(state, corner))
            and (corner is None or approaching_wing_corner(
                state, playing=playing, combined=job.metadata.get("wing_compensation") == "combined"
            ) == corner))


def compensation_allowed(state, corner):
    assessment = state.assessment
    if not corner or not corner["high_speed"] or assessment is None:
        return False
    labels = assessment.labels
    return (labels.race_state == "green" and labels.dynamics_state == "stable"
            and labels.attack_state == "closed" and labels.defend_state == "clear")


def wing_radio_text(sides, corner=None, *, levels, corner_only=False):
    reports = [f"{SIDES[side]}受损，损伤程度{spoken_percent(levels[side])}。" for side in sides]
    prefix = "" if corner_only else "".join(reports)
    severe = max(levels[side] for side in sides) >= 40
    if corner is not None:
        if corner.get("entry_reference") and levels == {"front_right": 31}:
            return (f"{prefix}{corner['label']}，早点刹。"
                    "转入弯时，参考时速九十到九十五，前轮左转五到九度。")
        if corner.get("high_speed"):
            return f"{prefix}{COMPENSATION_TEXT}"
        direction = corner.get("direction")
        turn = f"向{direction}打方向" if direction else "打方向"
        action = "再慢一点入弯" if severe else "早点刹车"
        return f"{prefix}{corner['label']}，{action}。减速再{turn}。"
    return f"{prefix}前轮抓地可能下降。"


def wing_values(state):
    if state.raw.get("session_paused") or state.raw.get("result_status", 2) != 2:
        return {}
    raw = state.raw.get("wing_damage_pct")
    return {side: valid_percentage(raw.get(side)) for side in SIDES} if isinstance(raw, dict) else {}


def confirmed_wing_damage(state, history):
    current = wing_values(state)
    earlier = next((item for item in reversed(history)
                    if item.source_timestamp_ms < state.source_timestamp_ms), None)
    if not current or earlier is None or state.source_timestamp_ms - earlier.source_timestamp_ms > 1000:
        return ()
    previous = wing_values(earlier)
    return tuple(side for side, value in current.items() if value is not None
                 and value >= FRONT_WING_WARNING_PCT and previous.get(side) is not None
                 and previous[side] >= FRONT_WING_WARNING_PCT)


def covered_wing_damage(state, completed):
    """True only when both sides are known and all current warnings were heard at this severity."""
    values = wing_values(state)
    if not all(values.get(side) is not None for side in SIDES):
        return False
    warned = {side: value for side, value in values.items() if value >= FRONT_WING_WARNING_PCT}
    return bool(warned) and all(value <= completed.get(side, -1) for side, value in warned.items())

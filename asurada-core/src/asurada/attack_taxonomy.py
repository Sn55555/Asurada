from __future__ import annotations


def infer_corner_overtake_class(
    *,
    track_zone: str,
    track_segment: str,
    track_usage: str,
) -> str:
    segment = (track_segment or "").lower()
    usage = track_usage or ""
    if usage in {"maximum_brake_pressure", "late_brake_control", "brake_marker_commit"}:
        return "heavy_braking_hairpin_or_chicane"
    if any(token in segment for token in ("t1/t2", "t7-t10", "t11-t13", "chicane", "s bend", "s-bend")):
        return "sequence_or_s_bend"
    if track_zone == "exit_traction" and usage in {
        "overtake_setup",
        "straight_launch_prep",
        "traction_release",
        "throttle_commit",
        "traction_rebuild",
    }:
        return "long_exit_to_straight"
    if track_zone == "high_load_management":
        return "high_speed_sweeper"
    if track_zone == "apex_rotation":
        return "medium_speed_single_apex"
    return "general"


def infer_attack_setup_method(
    *,
    track_zone: str,
    track_usage: str,
    corner_overtake_class: str,
) -> str:
    usage = track_usage or ""
    if track_zone == "deployment_straight" and usage in {
        "primary_overtake_deploy",
        "primary_ers_deploy",
        "overtake_setup",
    }:
        return "drs_tow"
    if track_zone == "high_load_management" and corner_overtake_class in {
        "sequence_or_s_bend",
        "high_speed_sweeper",
    }:
        return "pressure_build"
    if track_zone == "exit_traction" and usage in {"overtake_setup", "straight_launch_prep"}:
        return "traction_pass"
    return "none"


def infer_attack_commit_method(
    *,
    track_zone: str,
    track_usage: str,
    corner_overtake_class: str,
) -> str:
    usage = track_usage or ""
    if track_zone == "braking_entry":
        if usage == "late_brake_control":
            return "late_braking_lunge"
        if usage in {"maximum_brake_pressure", "brake_marker_commit", "defensive_braking", "front_end_commit"}:
            return "inside_outbrake"
    if track_zone == "apex_rotation" and corner_overtake_class in {
        "medium_speed_single_apex",
        "high_speed_sweeper",
    }:
        return "outside_carry"
    if track_zone == "exit_traction":
        if usage == "overtake_setup":
            return "switchback"
        if usage in {"straight_launch_prep", "traction_release", "throttle_commit", "traction_rebuild"}:
            return "traction_pass"
    return "none"


def attack_method_label(method: str) -> str:
    return {
        "drs_tow": "DRS/尾流铺垫",
        "pressure_build": "持续压迫铺垫",
        "inside_outbrake": "内线抢刹",
        "late_braking_lunge": "晚刹突袭",
        "outside_carry": "外线绕超",
        "switchback": "交叉线反切",
        "traction_pass": "出口牵引兑现",
        "none": "未形成明确方式",
    }.get(method or "none", method or "未形成明确方式")

"""Reconstruct player-relative timing and check whether an intervening car blocks a run."""
from dataclasses import replace

from .attack_forecast import number
from .attack_outcome import relative_position


def rear_gap_view(state, target):
    """Adjacent timing links are to the preceding car, never directly to the player."""
    rear = next((c for c in state.rivals if c.car_index == target), None)
    if not rear or rear.position <= state.player.position or rear.pit_status != "NONE" or "not_racing" in rear.status_tags:
        return None, None
    previous = state.player.position
    ranks = sorted((c for c in state.rivals if previous < c.position <= rear.position),
                   key=lambda c: c.position)
    gap = 0.
    for car in ranks:
        if car.position != previous + 1:
            return None, None
        previous = car.position
        if car.position == state.player.position + 1:
            part = state.player.gap_behind_s
            confidence = state.player.gap_confidence_behind
        else:
            part = car.gap_ahead_s
            confidence = car.gap_confidence_ahead
        if number(part) is None or part <= 0 or confidence != "high":
            gap = None
        elif gap is not None:
            gap += part
    if rear.position == state.player.position + 1:
        return state, rear
    if gap is None:
        return None, None
    heading = state.raw.get("world_forward_dir") or {}
    geo = relative_position(state.player, rear, heading)
    if rear.lap != state.player.lap or not geo or geo[0] >= -4:
        return None, None
    for car in ranks[:-1]:
        other = relative_position(state.player, car, heading)
        if not other or other[0] >= 0 or other[0] <= geo[0] or abs(other[1]-geo[1]) < 2.5:
            return None, None
    return replace(state, player=replace(state.player, gap_behind_s=gap, gap_confidence_behind="high")), rear

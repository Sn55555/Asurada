"""Serial ordering for uint32 counters, with a half-range ambiguity boundary.

Assumes compared packets are less than 2**31 frames apart. An exact half-range
advance is conservatively classified as old rather than inventing a new epoch.
"""


def distance(new, old):
    return (new - old) & 0xffffffff


def newer(new, old):
    return 0 < distance(new, old) < 0x80000000


def older(new, old):
    return distance(new, old) >= 0x80000000

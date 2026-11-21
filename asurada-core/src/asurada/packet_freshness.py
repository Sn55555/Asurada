"""Cache freshness uses packet receive time, never replay execution wall time."""
import math

CACHE_POLICIES = {
    'Session': ('latest_session_by_uid', 5000),
    'Participants': ('latest_participants_by_uid', 30000),
    'Event': ('latest_event_by_uid', 2000),
    'LobbyInfo': ('latest_lobby_info_by_uid', 30000),
    'CarSetups': ('latest_car_setups_by_uid', 30000),
    'TyreSets': ('latest_tyre_sets_by_uid', 5000),
    'SessionHistory': ('latest_session_history_by_uid', 10000),
    'FinalClassification': ('latest_final_classification_by_uid', 30000),
    'LapPositions': ('latest_lap_positions_by_uid', 5000),
}


class PacketFreshness:
    def __init__(self):
        self.observed = {}
        self.rejected = 0

    @staticmethod
    def timestamp(header):
        value = header.get('received_at_ms')
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None

    def accept(self, uid, kind, header):
        now = self.timestamp(header)
        previous = self.observed.get((uid, kind))
        if now is None or (previous is not None and now < previous):
            self.rejected += 1
            return False
        self.observed[(uid, kind)] = now
        return True

    def expire(self, assembler, uid, header):
        now = self.timestamp(header)
        quality = {}
        for kind, (attribute, ttl) in CACHE_POLICIES.items():
            observed = self.observed.get((uid, kind))
            age = now-observed if now is not None and observed is not None else None
            valid = age is not None and 0 <= age <= ttl
            cache = getattr(assembler, attribute)
            if not valid:
                cache.pop(uid, None)
                if kind == 'Session':
                    assembler.latest_session_header_by_uid.pop(uid, None)
            quality[kind] = dict(source=kind, observed_at_ms=observed, age_ms=age,
                                 ttl_ms=ttl, quality='current' if valid and uid in cache else 'unavailable')
        return quality

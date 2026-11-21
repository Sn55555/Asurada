from __future__ import annotations

from .race_control import normalize_race_control

from dataclasses import asdict, dataclass
from typing import Any
import math
import time
from .runtime_context import RuntimeContextDetector

from .models import SessionState, StrategyDecision, StrategyMessage


STRATEGY_ENGLISH_COPY: dict[str, tuple[str, str]] = {
    "NONE": ("Standby", "No active advisory"),
    "DEFEND_WINDOW": ("Defend", "Rear pressure high"),
    "ATTACK_WINDOW": ("Attack", "Attack window open"),
    "LOW_FUEL": ("Fuel Save", "Fuel margin low"),
    "DYNAMICS_UNSTABLE": ("Stabilize", "Car balance unstable"),
    "FRONT_LOAD": ("Front Load", "Historical load observation"),
    "TYRE_DAMAGE": ("Tyre Damage", "Tyre damage detected"),
    "TYRE_WEAR_ALERT": ("Tyre Wear", "Elevated tyre wear"),
    "FRONT_WING_DAMAGE": ("Front Wing Damage", "Steering may be affected"),
    "SAFETY_CAR": ("Safety Car", "Pace controlled"),
    "VIRTUAL_SAFETY_CAR": ("VSC", "Pace controlled"),
    "PIT_WINDOW": ("Pit Window", "Pit timing open"),
    "OVERTAKE": ("Overtake", "Passing opportunity"),
}


@dataclass
class GapPayload:
    ahead_s: float | None
    behind_s: float | None
    ahead_source: str
    behind_source: str
    front_rival_name: str | None
    rear_rival_name: str | None
    front_rival_position: int | None
    rear_rival_position: int | None


@dataclass
class VoicePayload:
    state: str
    active: bool
    pending: bool
    action_code: str | None
    source_kind: str | None
    persona_id: str | None
    voice_profile_id: str | None
    llm_sidecar_used: bool
    llm_sidecar_status: str | None
    amplitude_level: float
    amplitude_peak: float
    amplitude_rms: int | None
    amplitude_updated_at_ms: int
    amplitude_source: str | None
    beat_pulse: float
    beat_updated_at_ms: int


@dataclass
class DashboardPayload:
    payload_version: str
    timestamp_ms: int
    source_timestamp_ms: int
    session: dict[str, Any]
    car: dict[str, Any]
    tyres: dict[str, Any]
    damage: dict[str, Any]
    gaps: GapPayload
    voice: VoicePayload
    strategy: dict[str, Any]
    timing: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gaps"] = asdict(self.gaps)
        payload["voice"] = asdict(self.voice)
        return payload


def build_dashboard_payload(state: SessionState, decision: StrategyDecision) -> dict[str, Any]:
    raw = state.raw
    primary_message = decision.messages[0] if decision.messages else None
    strategy_code = primary_message.code if primary_message else "NONE"
    strategy_title, strategy_detail = _english_strategy_copy(primary_message)
    payload = DashboardPayload(
        payload_version="v1",
        timestamp_ms=int(raw.get("runtime_timing", {}).get("output_finished_at_ms") or state.source_timestamp_ms),
        source_timestamp_ms=int(state.source_timestamp_ms),
        session={
            "track": state.track,
            "lap_number": state.lap_number,
            "total_laps": state.total_laps,
            "position": state.player.position,
            "weather": state.weather,
            "safety_car": normalize_race_control(state.safety_car),
        },
        car={
            "speed_kph": _float_or_none(state.player.speed_kph, 1),
            "gear": _int_or_none(raw.get("gear")),
            "rpm": _int_or_none(raw.get("rpm")),
            "drs_open": bool(state.player.drs_available),
            "ers_pct": _percentage(state.player.ers_pct),
            "fuel_in_tank": _float_or_none(raw.get("fuel_in_tank")),
            "fuel_laps_remaining": _float_or_none(state.player.fuel_laps_remaining, 2),
        },
        tyres={
            "compound": state.player.tyre.compound,
            "age_laps": state.player.tyre.age_laps,
            "wear_pct_avg": _percentage(state.player.tyre.wear_pct),
            "wear_pct_corners": [_percentage(item) for item in (raw.get("tyres_wear_pct") or [None]*4)],
            "surface_temperature_c": [_int_or_none(item) for item in (state.player.tyre.surface_temperature_c or [None]*4)],
            "inner_temperature_c": [_int_or_none(item) for item in (state.player.tyre.inner_temperature_c or [None]*4)],
            "surface_temperature_avg_c": _float_or_none(raw.get("tyres_surface_temperature_avg_c")),
            "inner_temperature_avg_c": _float_or_none(raw.get("tyres_inner_temperature_avg_c")),
        },
        damage={
            "wing_damage_pct": {k: _percentage(v) for k, v in (raw.get("wing_damage_pct") or {}).items()},
            "floor_damage_pct": _int_or_none(raw.get("floor_damage_pct")),
            "diffuser_damage_pct": _int_or_none(raw.get("diffuser_damage_pct")),
            "sidepod_damage_pct": _int_or_none(raw.get("sidepod_damage_pct")),
            "gearbox_damage_pct": _int_or_none(raw.get("gearbox_damage_pct")),
            "engine_damage_pct": _int_or_none(raw.get("engine_damage_pct")),
            "engine_components_damage_pct": {k: _percentage(v) for k, v in (raw.get("engine_components_damage_pct") or {}).items()},
            "engine_blown": bool(raw.get("engine_blown", False)),
            "engine_seized": bool(raw.get("engine_seized", False)),
            "body_damage_pct": _aggregate_body_damage(raw),
            "powertrain_damage_pct": _aggregate_powertrain_damage(raw),
        },
        gaps=GapPayload(
            ahead_s=_gap_value(raw.get("official_gap_ahead_s"), raw.get("estimated_gap_ahead_s")),
            behind_s=_gap_value(raw.get("official_gap_behind_s"), raw.get("estimated_gap_behind_s")),
            ahead_source=_gap_source(raw.get("official_gap_ahead_s"), raw.get("estimated_gap_ahead_s")),
            behind_source=_gap_source(raw.get("official_gap_behind_s"), raw.get("estimated_gap_behind_s")),
            front_rival_name=raw.get("front_rival_name"),
            rear_rival_name=raw.get("rear_rival_name"),
            front_rival_position=_int_or_none(raw.get("front_rival_position")),
            rear_rival_position=_int_or_none(raw.get("rear_rival_position")),
        ),
        voice=_build_voice_payload(decision),
        strategy={
            **({"starting_grid": decision.debug["starting_grid_routes"]} if "starting_grid_routes" in decision.debug else {}),
            "primary_action": strategy_code,
            "title": strategy_title,
            "detail": strategy_detail,
            "priority": primary_message.priority if primary_message else 0,
            "ordered_actions": _ordered_action_codes(decision.messages),
        },
        timing=dict(raw.get("runtime_timing", {})),
    )
    result = payload.to_dict()
    from .assessment import snapshot_id
    binding = snapshot_id(state)
    record = decision.record
    if record is not None and record.snapshot_id != binding:
        raise ValueError('dashboard_decision_snapshot_mismatch')
    result['binding'] = {
        'contract_version': 'dashboard-binding-v1',
        'telemetry_contract_version': 'telemetry-v1',
        'session_uid': str(state.session_uid),
        'session_epoch': state.session_epoch,
        'snapshot_id': binding,
        'decision_id': record.decision_id if record else None,
        'decision_contract_version': record.contract_version if record else None,
    }
    result['session_event'] = state.session_event
    return result


def dashboard_source_status(payload: dict[str, Any], *, now_ms: int | None = None) -> dict[str, Any]:
    """Transport heartbeats never refresh telemetry age. Match core freshness."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    stamp = payload.get('source_timestamp_ms')
    valid = (not isinstance(stamp, bool) and isinstance(stamp, (int, float))
             and math.isfinite(stamp) and stamp > 0 and stamp == int(stamp))
    age = now - int(stamp) if valid else None
    limit = RuntimeContextDetector().stale_after_ms
    status = ('unavailable' if age is None else 'future' if age < 0
              else 'stale' if age > limit else 'live')
    return dict(contract_version='dashboard-source-v1', status=status,
                age_ms=age, stale_after_ms=limit, checked_at_ms=now)


def placeholder_dashboard_payload() -> dict[str, Any]:
    payload = {
        "payload_version": "v1",
        "timestamp_ms": 0,
        "source_timestamp_ms": 0,
        "session": {"track": "Standby", "lap_number": 0, "total_laps": 0, "position": 0, "weather": "N/A", "safety_car": None},
        "car": {"speed_kph": 0, "gear": 0, "rpm": 0, "drs_open": False, "ers_pct": 0, "fuel_in_tank": None, "fuel_laps_remaining": 0},
        "tyres": {
            "compound": "N/A",
            "age_laps": 0,
            "wear_pct_avg": 0,
            "wear_pct_corners": [0, 0, 0, 0],
            "surface_temperature_c": [0, 0, 0, 0],
            "inner_temperature_c": [0, 0, 0, 0],
            "surface_temperature_avg_c": 0,
            "inner_temperature_avg_c": 0,
        },
        "damage": {
            "wing_damage_pct": {"front_left": 0, "front_right": 0, "rear": 0},
            "floor_damage_pct": 0,
            "diffuser_damage_pct": 0,
            "sidepod_damage_pct": 0,
            "gearbox_damage_pct": 0,
            "engine_damage_pct": 0,
            "engine_components_damage_pct": {},
            "engine_blown": False,
            "engine_seized": False,
            "body_damage_pct": 0,
            "powertrain_damage_pct": 0,
        },
        "gaps": {
            "ahead_s": None,
            "behind_s": None,
            "ahead_source": "missing",
            "behind_source": "missing",
            "front_rival_name": None,
            "rear_rival_name": None,
            "front_rival_position": None,
            "rear_rival_position": None,
        },
        "voice": {
            "state": "idle",
            "active": False,
            "pending": False,
            "action_code": None,
            "source_kind": None,
            "persona_id": None,
            "voice_profile_id": None,
            "llm_sidecar_used": False,
            "llm_sidecar_status": None,
            "amplitude_level": 0.0,
            "amplitude_peak": 0.0,
            "amplitude_rms": None,
            "amplitude_updated_at_ms": 0,
            "amplitude_source": None,
            "beat_pulse": 0.0,
            "beat_updated_at_ms": 0,
        },
        "strategy": {"primary_action": "NONE", "title": "Standby", "detail": "", "priority": 0, "ordered_actions": []},
        "timing": {},
    }


    for key in ('speed_kph', 'gear', 'rpm', 'ers_pct', 'fuel_laps_remaining'):
        payload['car'][key] = None
    for key in ('wear_pct_corners', 'surface_temperature_c', 'inner_temperature_c'):
        payload['tyres'][key] = [None] * 4
    for key in ('wear_pct_avg', 'surface_temperature_avg_c', 'inner_temperature_avg_c'):
        payload['tyres'][key] = None
    for key in ('body_damage_pct', 'powertrain_damage_pct', 'floor_damage_pct', 'engine_damage_pct'):
        payload['damage'][key] = None
    return payload


def _ordered_action_codes(messages: list[StrategyMessage]) -> list[str]:
    return [message.code for message in messages]


def _build_voice_payload(decision: StrategyDecision) -> VoicePayload:
    output_lifecycle = dict(decision.debug.get("output_lifecycle", {}) or {})
    active_output = dict(output_lifecycle.get("active_output") or {})
    pending_output = dict(output_lifecycle.get("pending_output") or {})
    llm_sidecar = dict((decision.debug.get("voice_pipeline_log", {}) or {}).get("llm_sidecar") or {})

    if active_output:
        current = active_output
        state = "active"
    elif pending_output:
        current = pending_output
        state = "pending"
    else:
        current = {}
        state = "idle"

    return VoicePayload(
        state=state,
        active=bool(active_output),
        pending=bool(pending_output),
        action_code=current.get("action_code"),
        source_kind=current.get("source_kind"),
        persona_id=current.get("persona_id"),
        voice_profile_id=current.get("voice_profile_id"),
        llm_sidecar_used=bool(llm_sidecar.get("used", False)),
        llm_sidecar_status=_str_or_none(llm_sidecar.get("status")),
        amplitude_level=0.0,
        amplitude_peak=0.0,
        amplitude_rms=None,
        amplitude_updated_at_ms=0,
        amplitude_source=None,
        beat_pulse=0.0,
        beat_updated_at_ms=0,
    )


def _english_strategy_copy(message: StrategyMessage | None) -> tuple[str, str]:
    if message is None:
        return STRATEGY_ENGLISH_COPY["NONE"]
    mapped = STRATEGY_ENGLISH_COPY.get(message.code)
    if mapped is not None:
        return mapped
    title = message.code.replace("_", " ").title()
    detail = title
    return title, detail


def _gap_value(official_value: Any, estimated_value: Any) -> float | None:
    for value in (official_value, estimated_value):
        result = _float_or_none(value)
        if result is not None and result >= 0:
            return result
    return None


def _gap_source(official_value: Any, estimated_value: Any) -> str:
    for name, value in (('official', official_value), ('estimated', estimated_value)):
        result = _float_or_none(value)
        if result is not None and result >= 0:
            return name
    return 'missing'


def _complete_damage(values) -> int | None:
    values = [_percentage(value) for value in values]
    return None if not values or any(value is None for value in values) else round(max(values))


def _aggregate_body_damage(raw: dict[str, Any]) -> int | None:
    wing = raw.get('wing_damage_pct') or {}
    return _complete_damage([wing.get(key) for key in ('front_left', 'front_right', 'rear')]
        + [raw.get(key) for key in ('floor_damage_pct', 'diffuser_damage_pct', 'sidepod_damage_pct')])


def _aggregate_powertrain_damage(raw: dict[str, Any]) -> int | None:
    return _complete_damage([raw.get('gearbox_damage_pct'), raw.get('engine_damage_pct')]
        + list((raw.get('engine_components_damage_pct') or {}).values()))


def _float_or_none(value: Any, digits: int = 3) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return round(float(value), digits) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _percentage(value: Any) -> float | None:
    value = _float_or_none(value, 2)
    return value if value is not None and 0 <= value <= 100 else None


def _int_or_none(value: Any) -> int | None:
    value = _float_or_none(value)
    return int(value) if value is not None else None


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


MODEL_NAMES = frozenset({
    "strategy_action", "fuel_risk", "ers_risk", "tyre_risk", "dynamics_risk",
    "front_pressure", "rear_pressure", "rival_pressure", "entry_quality",
    "apex_quality", "exit_traction", "future_tyre_wear_delta",
    "future_grip_drop_score", "defence_cost",
})
MODES = frozenset({"disabled", "observe", "active"})


def validate_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"Unknown model admission mode: {mode}")
    return mode


def _default_modes() -> dict[str, str]:
    modes = {name: "observe" for name in MODEL_NAMES}
    modes.update(fuel_risk="disabled", front_pressure="disabled")
    return modes


@dataclass(frozen=True)
class ModelAdmissionPolicy:
    """Explicit model permissions; observing scores never grants decision access."""

    modes: Mapping[str, str] = field(default_factory=_default_modes)
    version: str = "f1-25-review-2026-09-08"
    evidence: Mapping[str, str] = field(default_factory=dict)
    context_window_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "modes", MappingProxyType(dict(self.modes)))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        unknown = set(self.modes) - MODEL_NAMES
        if unknown:
            raise ValueError(f"Unknown models in admission policy: {sorted(unknown)}")
        for name, mode in self.modes.items():
            validate_mode(mode)
            if mode == "active" and not self.evidence.get(name, "").strip():
                raise ValueError(f"Active model requires an admission evidence reference: {name}")

    def mode(self, name: str) -> str:
        return self.modes.get(name, "disabled")

    def validate_assets(self, runtimes) -> dict:
        """Bind active approval records to the assets actually selected for loading."""
        import json
        import hashlib
        from pathlib import Path
        from .model_assets import read_model_asset
        verified = {}
        for name, runtime in runtimes.items():
            if self.mode(name) != 'active':
                continue
            evidence_path = Path(self.evidence[name])
            if not evidence_path.is_absolute():
                evidence_path = runtime.report_path.parent / evidence_path
            evidence_bytes = evidence_path.read_bytes()
            evidence = json.loads(evidence_bytes)
            report, _ = read_model_asset(runtime.report_path, require_manifest=True)
            expected = {'version': 'model-admission-evidence-v1', 'model': name,
                        'context_window_version': self.context_window_version,
                        'model_sha256': report['asset_manifest']['model_sha256'],
                        'feature_schema_sha256': report['asset_manifest']['feature_schema_sha256']}
            if (not isinstance(evidence, dict) or evidence.get('approved') is not True
                    or any(evidence.get(key) != value for key, value in expected.items())
                    or not isinstance(evidence.get('evaluation_summary'), str)
                    or not evidence['evaluation_summary'].strip()):
                raise ValueError('invalid_active_model_evidence:' + name)
            verified[name] = {**expected, 'approved': True,
                              'evidence_sha256': hashlib.sha256(evidence_bytes).hexdigest()}
        return verified

    def active_scores(self, scores: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            name: value for name, value in scores.items()
            if self.mode(name) == "active" and value.get("enabled") is True
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "context_window_version": self.context_window_version,
            "models": {
                name: {"mode": self.mode(name), "evidence": self.evidence.get(name)}
                for name in sorted(MODEL_NAMES)
            },
        }

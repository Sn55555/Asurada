"""Behavior admission for deterministic planners, separate from model admission."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from .model_admission import validate_mode
from .model_output_quality import finite_number

NAMES=frozenset({'pit_window_support','long_horizon_strategy'})

# Only these numeric fields participate in arbitration. Other diagnostic fields
# may legitimately be unavailable and do not grant decision influence.
SCORING_FIELDS = {
    'pit_window_support': ('pit_window_open_prob', 'rejoin_traffic_penalty', 'pit_loss_now_score'),
    'long_horizon_strategy': ('aggression_bias', 'stint_risk_score',
                             'strategy_confidence', 'remaining_required_stops'),
}


def valid_contribution(name, payload):
    fields = SCORING_FIELDS.get(name)
    return (fields is not None and isinstance(payload, dict)
            and payload.get('enabled') is True
            and all(finite_number(payload.get(key)) for key in fields))



@dataclass(frozen=True)
class ContributorPolicy:
    modes: Mapping[str,str]=field(default_factory=lambda:{name:'observe' for name in NAMES})
    evidence: Mapping[str,str]=field(default_factory=dict)
    version: str='planner-admission-v1'

    def __post_init__(self):
        if set(self.modes)-NAMES:raise ValueError('unknown_contributor')
        for name,mode in self.modes.items():
            validate_mode(mode)
            if mode=='active' and not self.evidence.get(name,'').strip():raise ValueError('active_contributor_requires_evidence')
        if self.mode('long_horizon_strategy')=='active' and self.mode('pit_window_support')!='active':
            raise ValueError('active_planner_requires_active_support')
        object.__setattr__(self,'modes',MappingProxyType(dict(self.modes)))
        object.__setattr__(self,'evidence',MappingProxyType(dict(self.evidence)))

    def mode(self,name):return self.modes.get(name,'disabled')

    def admit(self,name,payload):
        return payload if self.mode(name)=='active' and valid_contribution(name, payload) else {}

    def snapshot(self):return {'version':self.version,'modes':dict(self.modes),'evidence':dict(self.evidence)}

"""Planner provenance survives a minimal snapshot and is content-bound."""
from copy import deepcopy
import json
from unittest.mock import patch
from asurada.config import StrategyThresholds
from asurada.strategy import StrategyEngine
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from asurada.contributor_admission import ContributorPolicy, NAMES
from asurada.snapshot_contract import snapshot_payload, restore_decision
from phase1_rival_pit_window_support_regression import _build_state
from regression_support import emit_result


def run():
    checks = {}
    ids = {}
    for mode in ('disabled','observe','active'):
        policy = ContributorPolicy(modes={n:mode for n in NAMES},
                                   evidence={n:'synthetic-record-test' for n in NAMES} if mode=='active' else {})
        with patch.object(ResourceRiskModelRuntime,'_load'), patch.object(StrategyActionModelRuntime,'_load'):
            engine = StrategyEngine(StrategyThresholds(), contributor_policy=policy)
        state = _build_state()
        state.raw.update(timing_mode='race_like', timing_support_level='official_preferred',fuel_in_tank=20,fuel_capacity=50)
        state.raw["tyre_rule_settings"] = dict(session_type=16, session_length=3, formula=0,
                                               game_mode=28, rule_set=1, weekend_structure=[15, 16])
        decision = engine.evaluate(state,[state])
        payload = json.loads(json.dumps(snapshot_payload(state,decision),allow_nan=False))
        restore_decision(state,payload)
        record = state.decision_record
        inputs = record.arbitration['planner_inputs']
        checks[mode+'_policy_roundtrip'] = inputs['policy']==policy.snapshot()
        ids[mode] = record.decision_id
        if mode != 'active':
            checks[mode+'_no_scoring_inputs'] = inputs['contributions']=={}
        else:
            checks['active_both_contributions_recorded'] = set(inputs['contributions'])==NAMES
            checks['active_scope_and_validity'] = all(
                v['binding']['snapshot_id']==record.snapshot_id and v['binding']['epoch']==state.session_epoch
                and v['validity']=={'scope':'snapshot_only'} for v in inputs['contributions'].values())
        tampered = deepcopy(payload)
        tampered['decision_record']['arbitration']['planner_inputs']['policy']['version']='changed'
        try:
            restore_decision(state,tampered)
            checks[mode+'_tamper_rejected']=False
        except ValueError as exc:
            checks[mode+'_tamper_rejected']=str(exc)=='decision_content_mismatch'
    checks['policy_changes_content_identity']=len(set(ids.values()))==3
    return {'passed':all(checks.values()),'checks':checks}


if __name__=='__main__':emit_result(run())

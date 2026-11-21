from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from asurada.arbiter import ModelCandidate
from asurada.config import AppConfig
from asurada.model_admission import MODEL_NAMES, ModelAdmissionPolicy
from asurada.model_runtime import ResourceRiskModelRuntime, StrategyActionModelRuntime
from asurada.strategy import StrategyEngine
from phase1_rival_pit_window_support_regression import _build_state
from regression_support import emit_result


def evaluate(policy, score):
    # Fixed predictions exercise every consumer without depending on model assets.
    with patch.object(ResourceRiskModelRuntime, "_load"), patch.object(StrategyActionModelRuntime, "_load"), patch.object(ModelAdmissionPolicy, 'validate_assets', return_value={}):
        engine = StrategyEngine(AppConfig().thresholds, model_policy=policy)
    state = _build_state()
    state.raw.update(timing_mode="race_like", timing_support_level="official_preferred", fuel_in_tank=1, fuel_capacity=100, fuel_laps_remaining_source="derived_from_sample_consumption")
    prediction = {"enabled": True, "score": score}
    for attribute in ("resource_risk_runtime", "rival_pressure_runtime", "driving_quality_runtime", "tyre_degradation_trend_runtime"):
        runtime = getattr(engine, attribute)
        for model in runtime._runtimes.values():
            model.predict_score = lambda **kwargs: dict(prediction)
    engine.defence_cost_runtime.predict_score = lambda **kwargs: dict(prediction)
    engine.strategy_action_runtime._enabled = policy.mode("strategy_action") != "disabled"
    engine.strategy_action_runtime.predict_top_k = lambda **kwargs: [
        ModelCandidate(code="LOW_FUEL", score=0.99, rank=1, source_model="fixture", title="fuel", detail="fixture")
    ]
    return engine.evaluate(state, [state])


def run_regression():
    default = ModelAdmissionPolicy()
    disabled = ModelAdmissionPolicy(modes={name: "disabled" for name in MODEL_NAMES})
    observe = ModelAdmissionPolicy(modes={name: "observe" for name in MODEL_NAMES})
    active = ModelAdmissionPolicy(
        modes={"fuel_risk": "active", "strategy_action": "active"},
        evidence={"fuel_risk": "synthetic-contract-test", "strategy_action": "synthetic-contract-test"},
        context_window_version='source-time-weighted-v1',
    )
    baseline = evaluate(disabled, 0)
    low = evaluate(observe, 0)
    high = evaluate(observe, 100)
    admitted = evaluate(active, 100)
    old_window_rejected = False
    try:
        evaluate(replace(active, context_window_version=None),100)
    except ValueError as exc:
        old_window_rejected = 'current_context_window_evaluation' in str(exc)
    high_input = high.debug["arbiter_v2"]["input"]
    admitted_input = admitted.debug["arbiter_v2"]["input"]
    denied_without_evidence = False
    try:
        ModelAdmissionPolicy(modes={"fuel_risk": "active"})
    except ValueError:
        denied_without_evidence = True
    invalid_mode_rejected = False
    try:
        ModelAdmissionPolicy(modes={"fuel_risk": "actve"})
    except ValueError:
        invalid_mode_rejected = True
    off = ResourceRiskModelRuntime(name="fuel_risk", report_path=Path("missing.json"), mode="disabled")
    checks = {
        "poor_fuel_model_disabled": default.mode("fuel_risk") == "disabled",
        "poor_front_model_disabled": default.mode("front_pressure") == "disabled",
        "unapproved_models_observe": default.mode("strategy_action") == "observe",
        "disabled_does_not_load_assets": not off.enabled and off.disabled_reason == "admission_disabled" and off._booster is None,
        "observed_candidates_logged": len(high_input["observed_model_candidates"]) == 1,
        "observed_candidates_not_admitted": high_input["model_candidates"] == [],
        "observed_scores_not_admitted": high_input["sidecar_scores"]["resource_models"] == {},
        "observed_scores_still_visible": high_input["resource_models"]["fuel_risk"]["score"] == 100,
        "observed_extremes_preserve_actions": baseline.messages == low.messages == high.messages,
        "observed_extremes_preserve_plan": baseline.debug["long_horizon_strategy"] == low.debug["long_horizon_strategy"] == high.debug["long_horizon_strategy"],
        "active_candidates_admitted": len(admitted_input["model_candidates"]) == 1,
        "only_approved_scores_admitted": set(admitted_input["sidecar_scores"]["resource_models"]) == {"fuel_risk"},
        "active_requires_evidence": denied_without_evidence,
        "active_requires_current_window_evaluation": old_window_rejected,
        "invalid_mode_rejected": invalid_mode_rejected,
        "policy_version_logged": high_input["model_admission"]["version"] == observe.version,
    }
    return {"passed": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    emit_result(run_regression())

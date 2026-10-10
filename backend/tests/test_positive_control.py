import pytest

from evals.statistics import summarize_results
from tools.positive_control import DEGRADED, apply, assess, plan


def test_control_changes_only_instructions_and_preserves_safety():
    control = plan("explicit-model", 1)
    a, b = control["configurations"]
    assert a["model"] == b["model"]
    assert a["reasoning_effort"] == b["reasoning_effort"]
    assert (
        a["sandbox_policy"]
        == b["sandbox_policy"]
        == {"mode": "workspace-write", "network": False}
    )
    assert b["instruction_preamble"] == a["instruction_preamble"] + "\n\n" + DEGRADED


def test_control_apply_is_bounded_and_never_starts_agents():
    calls = []

    def rpc(method, params=None):
        calls.append(method)
        if method == "eval.experiment.list":
            return []
        if method == "eval.suite.list":
            return [
                {"latest_version": {"id": 1, "status": "frozen", "cases": [{}] * 6}}
            ]
        if method == "eval.config.capture":
            return {"snapshot": {"id": len(calls)}}
        if method == "eval.config.diff":
            return {"differences": [{"field": "instructions"}]}
        if method == "eval.experiment.preflight":
            return {
                "network_enabled": False,
                "invalid_case_revision_ids": [],
                "attempt_count": 36,
            }
        if method == "eval.experiment.create":
            return {"id": 1, "status": "ready"}
        raise AssertionError(f"Unexpected RPC {method}")

    control = plan("explicit-model", 1)
    with pytest.raises(ValueError, match="budget"):
        apply(rpc, control, max_attempts=35)
    assert "eval.config.capture" not in calls
    result = apply(rpc, control, max_attempts=36)
    assert result["started"] is False
    assert "eval.experiment.start" not in calls


@pytest.mark.parametrize(
    "cases,detected", [(1, False), (5, False), (6, True), (30, True)]
)
def test_control_assessment_uses_case_level_evidence(cases, detected):
    rows = [
        {
            "case_revision_id": case,
            "sample_index": sample,
            "config_snapshot_id": config,
            "outcome": "pass" if config == 1 else "fail",
        }
        for case in range(cases)
        for sample in range(3)
        for config in (1, 2)
    ]
    results = summarize_results(rows, [1, 2])
    assert (
        assess(results, expected_case_count=cases, expected_samples_per_case=3)[
            "control_difference_detected"
        ]
        is detected
    )
    assert not assess(
        results, expected_case_count=cases + 1, expected_samples_per_case=3
    )["control_difference_detected"]
    assert not assess(results, expected_case_count=cases, expected_samples_per_case=4)[
        "control_difference_detected"
    ]
    assert (
        assess(
            summarize_results(rows, [1, 2], is_final=False),
            expected_case_count=cases,
            expected_samples_per_case=3,
        )["control_difference_detected"]
        is False
    )

import json
from copy import deepcopy

import pytest

from tools.revise_t3_prompts import ROOT, revise_t3_cases


def fixture(*, already_revised=False):
    overlay = json.loads((ROOT / "evals/t3code/prompt-scope-v2.json").read_text())
    cases = [
        {
            "id": i + 1,
            "title": f"T3 Code: {c['id']}",
            "latest_revision": {
                "id": i + 1,
                "status": "published",
                "prompt": c["prompt"] if already_revised else c["original_prompt"],
                "scorer_spec": [{"type": "diff", "allowed": [c["allowed_path"]]}],
            },
        }
        for i, c in enumerate(overlay["cases"])
    ]
    suite = {
        "id": 1,
        "name": "T3 Code realistic regressions",
        "latest_version": {
            "id": 1,
            "status": "frozen",
            "version": 1,
            "cases": [{"revision_id": i + 1} for i in range(5)],
        },
    }
    calls = []

    def rpc(method, params=None):
        calls.append((method, params))
        if method == "eval.case.list":
            return deepcopy(cases)
        if method == "eval.suite.list":
            return [deepcopy(suite)]
        if method.startswith("eval.case."):
            case = cases[params["case_id"] - 1]
            if method == "eval.case.revise":
                case["latest_revision"]["id"] += 5
                case["latest_revision"]["status"] = "draft"
            elif method == "eval.case.update_draft":
                assert set(params) == {"case_id", "revision_id", "prompt"}
                case["latest_revision"]["prompt"] = params["prompt"]
            elif method == "eval.case.validate":
                case["latest_revision"]["validation_status"] = "valid"
            elif method == "eval.case.publish":
                case["latest_revision"]["status"] = "published"
            else:
                raise AssertionError(method)
            return deepcopy(case)
        if method == "eval.suite.update_draft":
            suite["latest_version"] = {
                "id": 2,
                "version": 2,
                "status": "draft",
                "cases": [{"revision_id": i} for i in params["case_revision_ids"]],
            }
            return deepcopy(suite)
        if method == "eval.suite.freeze":
            suite["latest_version"]["status"] = "frozen"
            return deepcopy(suite)
        raise AssertionError(f"Unexpected agent launch or mutation: {method}")

    return overlay, cases, calls, rpc


def test_scope_revision_changes_only_prompts_and_freezes_new_suite():
    overlay, _, calls, rpc = fixture()
    result = revise_t3_cases(rpc, overlay)
    assert result["revision_ids"] == [6, 7, 8, 9, 10]
    assert result["suite"]["latest_version"]["version"] == 2
    assert result["agent_attempts_launched"] == 0
    assert sum(method == "eval.case.validate" for method, _ in calls) == 5


def test_scope_revision_is_idempotent():
    overlay, _, calls, rpc = fixture(already_revised=True)
    result = revise_t3_cases(rpc, overlay)
    assert result["revision_ids"] == [1, 2, 3, 4, 5]
    assert [m for m, _ in calls] == ["eval.case.list", "eval.suite.list"]


@pytest.mark.parametrize("change", ["prompt", "scope", "draft"])
def test_preflight_refuses_independent_changes_before_any_mutation(change):
    overlay, cases, calls, rpc = fixture()
    revision = cases[-1]["latest_revision"]
    if change == "prompt":
        revision["prompt"] = "An independent task"
    elif change == "scope":
        revision["scorer_spec"][0]["allowed"] = ["other.ts"]
    else:
        revision["status"] = "draft"
    with pytest.raises(ValueError):
        revise_t3_cases(rpc, overlay)
    assert [m for m, _ in calls] == ["eval.case.list"]

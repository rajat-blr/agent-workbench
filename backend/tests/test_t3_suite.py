from pathlib import Path

import pytest

from tools import run_t3_suite


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_count", 9),
        ("attempt_count", 11),
        ("case_count", 4),
        ("network_enabled", True),
        ("invalid_case_revision_ids", [1]),
    ],
)
def test_requires_bounded_valid_offline_plan(field, value):
    plan = {
        "attempt_count": 10,
        "case_count": 5,
        "network_enabled": False,
        "invalid_case_revision_ids": [],
    }
    plan[field] = value
    with pytest.raises(RuntimeError, match="ten valid offline"):
        run_t3_suite.validate_plan(plan, [{"field": "reasoning_effort"}])


def test_only_reasoning_effort_may_differ():
    plan = {
        "attempt_count": 10,
        "case_count": 5,
        "network_enabled": False,
        "invalid_case_revision_ids": [],
    }
    run_t3_suite.validate_plan(plan, [{"field": "reasoning_effort"}])
    for differences in (
        [],
        [{"field": "model"}],
        [{"field": "reasoning_effort"}, {"field": "instructions"}],
    ):
        with pytest.raises(RuntimeError, match="only in reasoning"):
            run_t3_suite.validate_plan(plan, differences)


def test_refuses_silent_duplicate(monkeypatch):
    calls = []

    def rpc(method, params=None):
        calls.append(method)
        assert method == "eval.experiment.list"
        return [{"name": run_t3_suite.NAME}]

    monkeypatch.setattr(
        run_t3_suite, "connection_for_process", lambda *_: ("local", "secret")
    )
    monkeypatch.setattr(run_t3_suite, "Rpc", lambda *_: rpc)
    with pytest.raises(RuntimeError, match="already exists"):
        run_t3_suite.run_suite(Path("unused"), 1, "pinned-model")
    assert calls == ["eval.experiment.list"]

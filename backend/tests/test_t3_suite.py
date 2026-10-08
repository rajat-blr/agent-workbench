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


def test_existing_snapshots_are_reused_in_requested_order():
    catalog = [
        {
            "snapshot": {
                "id": i,
                "model": "pinned-model",
                "reasoning_effort": effort,
                "sandbox_policy": {"mode": "workspace-write", "network": False},
            }
        }
        for i, effort in ((2, "medium"), (3, "high"))
    ]
    assert (
        run_t3_suite.select_existing_configs(catalog[::-1], [2, 3], "pinned-model")
        == catalog
    )
    for ids in ([2, 2], [3, 2], [2, 4], [2]):
        with pytest.raises(RuntimeError):
            run_t3_suite.select_existing_configs(catalog, ids, "pinned-model")
    with pytest.raises(RuntimeError):
        run_t3_suite.select_existing_configs(catalog, [2, 3], "another-model")
    catalog[0]["snapshot"]["sandbox_policy"]["network"] = True
    with pytest.raises(RuntimeError):
        run_t3_suite.select_existing_configs(catalog, [2, 3], "pinned-model")


def test_v2_duplicate_is_refused_before_mutation(monkeypatch):
    monkeypatch.setattr(
        run_t3_suite, "connection_for_process", lambda *_: ("local", "secret")
    )
    calls = []

    def rpc(method, params=None):
        calls.append(method)
        return [{"name": "T3 v2 five-case comparison — medium vs high"}]

    monkeypatch.setattr(run_t3_suite, "Rpc", lambda *_: rpc)
    with pytest.raises(RuntimeError, match="already exists"):
        run_t3_suite.run_suite(Path("unused"), 1, "pinned-model", suite_version=2)
    assert calls == ["eval.experiment.list"]

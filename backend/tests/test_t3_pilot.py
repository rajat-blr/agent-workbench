from pathlib import Path

import pytest

from tools import run_t3_pilot


def install_rpc(monkeypatch, *, previous=False, attempts=1, network=False):
    calls = []

    def rpc(method, params=None):
        calls.append(method)
        if method == "eval.case.list":
            return [
                {
                    "id": 3,
                    "title": "T3 Code: cache-pruning",
                    "latest_revision": {
                        "id": 3,
                        "workspace_id": 7,
                        "status": "published",
                    },
                }
            ]
        if method == "eval.experiment.list":
            return [{"name": "T3 cache-pruning pilot"}] if previous else []
        if method == "eval.config.capture":
            return {"id": 1, "snapshot": {"id": 1}}
        if method in {"eval.suite.create", "eval.suite.freeze"}:
            return {"id": 2, "latest_version": {"id": 2}}
        if method == "eval.suite.update_draft":
            assert params["case_revision_ids"] == [3]
            return {}
        if method == "eval.experiment.preflight":
            assert params["samples_per_case"] == params["concurrency"] == 1
            assert params["timeout_seconds"] == 600
            return {
                "attempt_count": attempts,
                "invalid_case_revision_ids": [],
                "network_enabled": network,
            }
        raise AssertionError(f"Unexpected mutation: {method}")

    monkeypatch.setattr(
        run_t3_pilot, "connection_for_process", lambda *_: ("local", "secret")
    )
    monkeypatch.setattr(run_t3_pilot, "Rpc", lambda *_: rpc)
    return calls


def test_pilot_refuses_silent_duplicate_run(monkeypatch):
    calls = install_rpc(monkeypatch, previous=True)
    with pytest.raises(RuntimeError, match="already exists"):
        run_t3_pilot.run_pilot(Path("unused"), 1, "explicit-model")
    assert calls == ["eval.case.list", "eval.experiment.list"]


@pytest.mark.parametrize("attempts,network", [(2, False), (1, True)])
def test_pilot_requires_exactly_one_offline_attempt(monkeypatch, attempts, network):
    calls = install_rpc(monkeypatch, attempts=attempts, network=network)
    with pytest.raises(RuntimeError, match="one valid offline attempt"):
        run_t3_pilot.run_pilot(Path("unused"), 1, "explicit-model")
    assert "eval.experiment.create" not in calls
    assert "eval.experiment.start" not in calls

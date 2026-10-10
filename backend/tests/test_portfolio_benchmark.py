import pytest

from tools.portfolio_benchmark import TASKS, export_recording, portable


def test_portfolio_plan_is_four_cases_balanced_by_repository():
    assert len(TASKS) == 4
    assert sum(title.startswith("Zod") for title, _ in TASKS.values()) == 2
    assert sum(title.startswith("Hono") for title, _ in TASKS.values()) == 2
    assert all(len(commit) == 40 for commit in TASKS)


def test_portable_recording_preserves_numeric_usage_and_redacts_secrets():
    original = {
        "input_tokens": 1234,
        "text": "\x1b[31mBearer abcdefghijklmnopqrstuvwxyz\x1b[0m",
        "rows": [{"content": "api_key=private-value"}],
    }
    result = portable(original)
    assert result["input_tokens"] == 1234
    assert "abcdefghijklmnopqrstuvwxyz" not in result["text"]
    assert "\x1b" not in result["text"]
    assert "private-value" not in result["rows"][0]["content"]
    assert "private-value" in original["rows"][0]["content"]


def test_export_rejects_partial_run_without_reading_or_writing_evidence():
    calls = []

    def rpc(method, params):
        calls.append(method)
        return {"status": "running", "attempts": []}

    with pytest.raises(ValueError, match="all eight"):
        export_recording(rpc, {"experiment_id": 1})
    assert calls == ["eval.experiment.get"]

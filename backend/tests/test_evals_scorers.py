import sys

import pytest

from evals.scorers import (
    CommandScorerSpec,
    DiffConstraintSpec,
    FileAssertionSpec,
    ScoreResult,
    classify_required_scores,
    score_command,
    score_diff_constraints,
    score_file_assertion,
    score_tamper,
)


@pytest.mark.asyncio
async def test_command_scorer_uses_worktree_and_filtered_environment(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("UNRELATED_SECRET", "hidden")
    script = (
        "import os, pathlib, sys; "
        "print(pathlib.Path.cwd().name); "
        "print(os.getenv('CASE_VALUE')); "
        "sys.exit(0 if os.getenv('UNRELATED_SECRET') is None else 9)"
    )
    result = await score_command(
        CommandScorerSpec(
            key="tests",
            argv=(sys.executable, "-c", script),
            environment={"CASE_VALUE": "visible"},
        ),
        tmp_path,
    )

    assert result.status == "pass"
    assert result.passed is True
    assert result.value == {"exit_code": 0}
    assert result.evidence["stdout"].splitlines() == [tmp_path.name, "visible"]


@pytest.mark.asyncio
async def test_command_failure_and_timeout_are_distinct(tmp_path) -> None:
    failed = await score_command(
        CommandScorerSpec(
            key="tests",
            argv=(sys.executable, "-c", "raise SystemExit(3)"),
        ),
        tmp_path,
    )
    timed_out = await score_command(
        CommandScorerSpec(
            key="slow",
            argv=(sys.executable, "-c", "import time; time.sleep(5)"),
            timeout_seconds=0.05,
        ),
        tmp_path,
    )

    assert (failed.status, failed.passed) == ("fail", False)
    assert failed.value == {"exit_code": 3}
    assert (timed_out.status, timed_out.passed) == ("unavailable", None)


def test_file_assertion_scorer_supports_all_mvp_assertions(tmp_path) -> None:
    (tmp_path / "output.txt").write_text("hello evals\n")
    (tmp_path / "result.json").write_text('{"result":{"count":3}}')

    specs = [
        FileAssertionSpec("exists", "output.txt", "exists"),
        FileAssertionSpec("absent", "missing.txt", "absent"),
        FileAssertionSpec("contains", "output.txt", "contains", "evals"),
        FileAssertionSpec("regex", "output.txt", "regex", r"hello\s+evals"),
        FileAssertionSpec(
            "json", "result.json", "json_value", 3, json_path="result.count"
        ),
    ]

    results = [score_file_assertion(spec, tmp_path) for spec in specs]

    assert all(result.status == "pass" for result in results)
    escaped = score_file_assertion(
        FileAssertionSpec("escape", "../secret", "exists"), tmp_path
    )
    assert escaped.status == "unavailable"


def test_diff_and_tamper_scorers_return_concrete_evidence() -> None:
    changed = {"src/app.py", "tests/test_app.py", "verifier/hidden.py"}
    constraints = score_diff_constraints(
        DiffConstraintSpec(
            key="paths",
            allowed=("src/**", "tests/**"),
            forbidden=("verifier/**",),
            required_paths=("src/**", "docs/**"),
        ),
        changed,
    )
    tamper = score_tamper(changed, ("verifier/**",))

    assert constraints.status == "fail"
    assert constraints.evidence == {
        "outside_allowed": ["verifier/hidden.py"],
        "forbidden": ["verifier/hidden.py"],
        "missing_required": ["docs/**"],
    }
    assert tamper.status == "fail"
    assert tamper.evidence["forbidden"] == ["verifier/hidden.py"]


def test_required_score_classification_separates_failures_from_infrastructure() -> None:
    def result(status, required=True):
        return ScoreResult("test", 1, required, status, status == "pass", {}, "", {})

    assert classify_required_scores([result("pass")]) == "pass"
    assert classify_required_scores([result("pass"), result("fail")]) == "fail"
    assert (
        classify_required_scores([result("fail"), result("unavailable")])
        == "infra_error"
    )
    assert classify_required_scores([result("fail", required=False)]) == "infra_error"

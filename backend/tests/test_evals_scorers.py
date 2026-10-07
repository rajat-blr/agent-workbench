import asyncio
import os
import sys

import pytest

from evals.scorers import (
    MAX_COMMAND_OUTPUT_BYTES,
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


@pytest.mark.asyncio
async def test_large_output_preserves_both_streams_and_bounds_excess(tmp_path) -> None:
    result = await score_command(
        CommandScorerSpec(
            "large",
            (
                sys.executable,
                "-c",
                "import sys; print('a'*40000); print('b'*40000, file=sys.stderr)",
            ),
        ),
        tmp_path,
        capture_full_output=True,
    )
    assert result.status == "pass"
    assert result.evidence["stdout_truncated"] and result.evidence["stderr_truncated"]
    assert result.full_output == {
        "stdout": "a" * 40000 + "\n",
        "stderr": "b" * 40000 + "\n",
    }
    exceeded = await score_command(
        CommandScorerSpec(
            "excess",
            (
                sys.executable,
                "-c",
                f"import sys,time; sys.stdout.buffer.write(b'x'*{MAX_COMMAND_OUTPUT_BYTES + 65536}); sys.stdout.flush(); time.sleep(5)",
            ),
        ),
        tmp_path,
        capture_full_output=True,
    )
    assert exceeded.status == "unavailable" and exceeded.passed is None
    assert "output limit" in exceeded.summary
    assert exceeded.full_output is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process group assertion")
async def test_cancelled_scorer_reaps_parent_and_stops_descendant(tmp_path) -> None:
    child = "import pathlib,time; p=pathlib.Path('heartbeat');\nwhile True: p.write_text(str(time.time_ns())); time.sleep(.01)"
    script = f"import os,pathlib,subprocess,sys; pathlib.Path('pid').write_text(str(os.getpid())); child=subprocess.Popen([sys.executable,'-c',{child!r}]); child.wait()"
    task = asyncio.create_task(
        score_command(
            CommandScorerSpec("cancel", (sys.executable, "-c", script)), tmp_path
        )
    )
    try:
        async with asyncio.timeout(3):
            while not (tmp_path / "heartbeat").exists():
                await asyncio.sleep(0.01)
        pid = int((tmp_path / "pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        await asyncio.sleep(0.05)
        heartbeat = (tmp_path / "heartbeat").read_text()
        await asyncio.sleep(0.1)
        assert (tmp_path / "heartbeat").read_text() == heartbeat
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


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

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tools.audit_mined_inventory import inventory
from tools.eval_baselines import git
from tools.mine_eval_cases import (
    Options,
    candidate,
    mine,
)
from tools.mine_eval_cases import (
    test_argv as expand_test_argv,
)


def test_test_paths_expand_as_distinct_arguments():
    assert expand_test_argv(
        ("vitest", "run", "{test_paths}"), ["a.test.ts", "b test.ts"]
    ) == ("vitest", "run", "a.test.ts", "b test.ts")
    assert expand_test_argv(("literal-{test_paths}",), ["a"]) == (
        "literal-{test_paths}",
    )


def commit(repository):
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    return git(repository, "rev-parse", "HEAD").decode().strip()


def fixture(
    tmp_path,
    *,
    test="from calc import add\nassert add(1, 2) == 3\n",
    baseline="def add(a, b): return 0\n",
):
    repository = tmp_path / "source"
    repository.mkdir()
    git(repository, "init", "--quiet")
    (repository / ".gitignore").write_text("__pycache__/\n")
    (repository / "calc.py").write_text(baseline)
    parent = commit(repository)
    (repository / "calc.py").write_text("def add(a, b): return a + b\n")
    (repository / "test_behavior.py").write_text(test)
    fixed = commit(repository)
    return repository, parent, fixed


@pytest.mark.asyncio
async def test_miner_validates_parent_failure_and_reference_success_without_history_leaks(
    tmp_path,
):
    repository, parent, fixed = fixture(tmp_path)
    options = Options(
        test_command=(sys.executable, "{test_paths}"), visibility="private"
    )
    report = await mine(repository, [fixed], tmp_path / "mined", options, execute=True)
    assert report["accepted_count"] == 1
    item = report["cases"][0]
    assert item["parent"] == parent
    assert item["status"] == "validated_draft"
    assert item["provenance"]["contamination_status"] == "not_established"
    baseline = Path(item["baseline"])
    assert not (baseline / "test_behavior.py").exists()
    assert git(baseline, "rev-list", "--count", "--all").strip() == b"1"
    assert git(baseline, "remote").strip() == b""
    scores = json.loads((Path(item["private"]) / "scores.json").read_text())
    assert [score["status"] for score in scores] == ["fail", "fail", "pass", "pass"]
    assert Path(item["import_payload"]).exists()
    payload = json.loads(Path(item["import_payload"]).read_text())
    assert payload["scorer_spec"][0]["argv"] == [sys.executable, "test_behavior.py"]
    assert git(repository, "status", "--porcelain") == b""
    evidence = tmp_path / "mined" / "report.json"
    audited = inventory([("fixture", evidence), ("fixture", evidence)])
    assert audited["case_count"] == 1
    assert audited["model_attempts"] == 0
    assert audited["counts_by_source"] == {"fixture": 1}
    (Path(item["private"]) / "reference.patch").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        inventory([("fixture", evidence)])


@pytest.mark.asyncio
async def test_discovery_never_prepares_or_executes_test_commands(tmp_path):
    repository, _, fixed = fixture(tmp_path)
    report = await mine(
        repository,
        [fixed],
        tmp_path / "discovery",
        Options(test_command=("must-not-run",)),
    )
    assert report["cases"][0]["status"] == "discovered_unvalidated"
    assert not (tmp_path / "discovery" / fixed[:12]).exists()
    with pytest.raises(ValueError, match="Discovery"):
        inventory([("fixture", tmp_path / "discovery" / "report.json")])


@pytest.mark.asyncio
async def test_export_preserves_upstream_tracked_ignored_manifests(tmp_path):
    repository, _, _ = fixture(tmp_path)
    (repository / ".gitignore").write_text("__pycache__/\nmanifest.json\n")
    (repository / "manifest.json").write_text('{"required": true}')
    git(repository, "add", "--force", "manifest.json")
    commit(repository)
    (repository / "calc.py").write_text("def add(a, b): return 0\n")
    commit(repository)
    (repository / "calc.py").write_text("def add(a, b): return a + b\n")
    (repository / "test_behavior.py").write_text(
        "import json\nfrom calc import add\n"
        "assert json.load(open('manifest.json'))['required']\nassert add(1, 2) == 3\n"
    )
    fixed = commit(repository)
    report = await mine(
        repository,
        [fixed],
        tmp_path / "mined",
        Options(test_command=(sys.executable, "{test_paths}")),
        execute=True,
    )
    assert report["accepted_count"] == 1
    baseline = Path(report["cases"][0]["baseline"])
    assert git(baseline, "ls-files", "manifest.json").strip() == b"manifest.json"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test,baseline",
    [
        ("assert True\n", "def add(a, b): return 0\n"),
        ("import missing_dependency\n", "def add(a, b): return 0\n"),
        ("from calc import add\nassert add(1, 2) == 9\n", "def add(a, b): return 0\n"),
        ("from calc import add\nassert add(1, 2) == 3\n", "def add(a, b): return 3\n"),
    ],
)
async def test_miner_rejects_vacuous_infrastructure_reference_failures_and_already_fixed_baselines(
    tmp_path, test, baseline
):
    repository, _, fixed = fixture(tmp_path, test=test, baseline=baseline)
    result = await mine(
        repository,
        [fixed],
        tmp_path / "mined",
        Options(test_command=(sys.executable, "test_behavior.py")),
        execute=True,
    )
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 1
    assert not (tmp_path / "mined" / fixed[:12] / "private" / "import.json").exists()


def test_cutoff_and_private_declarations_are_explicit_not_proof(tmp_path):
    repository, parent, fixed = fixture(tmp_path)
    with pytest.raises(ValueError, match="newer"):
        candidate(repository, fixed, replace(Options(), training_cutoff="9999-01-01"))
    item = candidate(
        repository,
        fixed,
        replace(Options(), visibility="public", training_cutoff="2000-01-01"),
    )
    assert item["provenance"]["post_cutoff_by_git_timestamp"] is True
    assert item["provenance"]["contamination_status"] == "not_established"
    with pytest.raises(ValueError, match="Root"):
        candidate(repository, parent, Options())


@pytest.mark.asyncio
async def test_miner_never_overwrites_existing_output(tmp_path):
    repository, _, fixed = fixture(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep").write_text("user data")
    with pytest.raises(FileExistsError):
        await mine(repository, [fixed], output, Options())
    assert (output / "keep").read_text() == "user data"

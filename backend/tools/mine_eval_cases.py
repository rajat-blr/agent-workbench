"""Mine bounded, history-free draft cases; discovery never executes repository code."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.scorers import CommandScorerSpec, score_command
from evals.verifier_bundles import build_verifier_bundle, materialize_verifier_bundle
from evals.worktrees import WorktreeError, WorktreeService
from tools.eval_baselines import audit_baseline, extract_baseline, git

TEST_GLOBS = (
    "**/test_*.py",
    "test_*.py",
    "**/*.test.*",
    "**/*.spec.*",
    "tests/**",
    "test/**",
)
SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".rb",
}


@dataclass(frozen=True)
class Options:
    test_globs: tuple[str, ...] = TEST_GLOBS
    test_command: tuple[str, ...] = ()
    setup_command: tuple[str, ...] = ()
    failure_pattern: str = "AssertionError"
    timeout: int = 120
    repetitions: int = 2
    visibility: str = "unknown"
    training_cutoff: str | None = None


def test_argv(argv: tuple[str, ...], paths: list[str]) -> tuple[str, ...]:
    """Expand a standalone placeholder without invoking a shell."""
    return tuple(
        path for arg in argv for path in (paths if arg == "{test_paths}" else [arg])
    )


def candidate(repository: Path, commit: str, options: Options) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full commit SHA")
    lineage = (
        git(repository, "rev-list", "--parents", "-n", "1", commit).decode().split()
    )
    if len(lineage) != 2:
        raise ValueError("Root and merge commits are not supported")
    parent = lineage[1]
    fields = (
        git(repository, "diff", "--no-renames", "--name-status", "-z", parent, commit)
        .decode()
        .split("\0")[:-1]
    )
    if len(fields) % 2:
        raise ValueError("Invalid changed-path listing")
    tests, production = [], []
    for status, filename in zip(fields[::2], fields[1::2], strict=True):
        if Path(filename).suffix in {".md", ".rst", ".txt"} or filename.startswith(
            "docs/"
        ):
            continue  # Documentation changes are not part of the production patch.
        if status not in {"A", "M"}:
            raise ValueError(
                "Only additions/modifications are supported; review deletions/renames manually"
            )
        if any(
            fnmatch.fnmatchcase(filename, pattern) for pattern in options.test_globs
        ):
            tests.append(filename)
        elif Path(filename).suffix in SOURCE_SUFFIXES and Path(filename).name not in {
            "AGENTS.md",
            "conftest.py",
        }:
            production.append(filename)
        else:
            raise ValueError(
                "Commit includes non-source/tooling changes; review it manually"
            )
    if not tests or not production:
        raise ValueError("Commit must change both held-out tests and production source")
    modes = git(repository, "ls-tree", commit, "--", *tests).decode().splitlines()
    if len(modes) != len(tests) or any(
        not row.startswith(("100644 blob ", "100755 blob ")) for row in modes
    ):
        raise ValueError("Held-out tests must be regular files")
    timestamp = git(repository, "show", "-s", "--format=%cI", commit).decode().strip()
    post_cutoff = None
    if options.training_cutoff:
        post_cutoff = date.fromisoformat(timestamp[:10]) > date.fromisoformat(
            options.training_cutoff
        )
        if not post_cutoff:
            raise ValueError("Commit timestamp is not newer than the declared cutoff")
    return {
        "commit": commit,
        "parent": parent,
        "test_paths": sorted(tests),
        "production_paths": sorted(production),
        "provenance": {
            "source_visibility": options.visibility,
            "visibility_basis": "operator declaration, not independently verified",
            "commit_timestamp": timestamp,
            "declared_training_cutoff": options.training_cutoff,
            "post_cutoff_by_git_timestamp": post_cutoff,
            "contamination_status": "not_established",
        },
    }


def prepare(repository: Path, item: dict, output: Path) -> dict:
    directory = output / item["commit"][:12]
    directory.mkdir(mode=0o700)
    baseline = directory / "baseline"
    baseline.mkdir()
    private = directory / "private"
    private.mkdir(mode=0o700)
    withheld = set(item["test_paths"])
    extract_baseline(
        git(repository, "archive", "--format=tar", item["parent"]), baseline, withheld
    )
    git(baseline, "init", "--quiet")
    # The archive contains upstream-tracked files, including ignored manifests.
    git(baseline, "add", "--force", ".")
    git(
        baseline,
        "-c",
        "user.name=Eval Miner",
        "-c",
        "user.email=eval-miner@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "History-free evaluation baseline",
    )
    sha = git(baseline, "rev-parse", "HEAD").decode().strip()
    audit = audit_baseline(baseline, withheld, sha)
    bundle = build_verifier_bundle(
        [
            {
                "path": filename,
                "content": git(
                    repository, "show", f"{item['commit']}:{filename}"
                ).decode(),
            }
            for filename in item["test_paths"]
        ]
    )
    (private / "verifier.json").write_bytes(bundle)
    patch = git(
        repository,
        "diff",
        "--binary",
        item["parent"],
        item["commit"],
        "--",
        *item["production_paths"],
    )
    (private / "reference.patch").write_bytes(patch)
    return {
        **item,
        "baseline": str(baseline),
        "base_sha": sha,
        "private": str(private),
        "isolation_audit": audit,
        "verifier_sha256": hashlib.sha256(bundle).hexdigest(),
        "reference_patch_sha256": hashlib.sha256(patch).hexdigest(),
    }


async def validate(item: dict, options: Options, output: Path, index: int) -> dict:
    worktrees = WorktreeService(output / "validation-worktrees")
    provisioned = await worktrees.provision(item["baseline"], item["base_sha"], index)
    private = Path(item["private"])
    scores = []
    try:
        if options.setup_command:
            setup = await score_command(
                CommandScorerSpec(
                    "setup", options.setup_command, timeout_seconds=options.timeout
                ),
                provisioned.path,
                capture_full_output=True,
            )
            scores.append({"stage": "setup", **asdict(setup)})
            if setup.status != "pass":
                raise ValueError("Setup command did not pass")
        if await worktrees.changed_paths(provisioned):
            raise ValueError("Setup changed tracked source files")
        bundle = await asyncio.to_thread((private / "verifier.json").read_bytes)
        await asyncio.to_thread(materialize_verifier_bundle, bundle, provisioned.path)
        command = CommandScorerSpec(
            "held-out-regression",
            test_argv(options.test_command, item["test_paths"]),
            timeout_seconds=options.timeout,
        )
        for stage in ("baseline", "reference"):
            if stage == "reference":
                await asyncio.to_thread(
                    git, provisioned.path, "apply", str(private / "reference.patch")
                )
            for _ in range(options.repetitions):
                score = await score_command(
                    command, provisioned.path, capture_full_output=True
                )
                scores.append({"stage": stage, **asdict(score)})
                text = score.evidence.get("stdout", "") + score.evidence.get(
                    "stderr", ""
                )
                if stage == "baseline":
                    if (
                        score.status != "fail"
                        or score.value.get("exit_code") != 1
                        or not re.search(options.failure_pattern, text)
                    ):
                        raise ValueError(
                            "Baseline lacks a normal assertion failure matching the required pattern"
                        )
                elif score.status != "pass":
                    raise ValueError("Reference patch did not pass held-out tests")
        expected = set(item["production_paths"]) | set(item["test_paths"])
        if await worktrees.changed_paths(provisioned) != expected:
            raise ValueError("Validation changed unexpected files")

        def check_tests():
            from evals.verifier_bundles import parse_verifier_bundle

            return all(
                (provisioned.path / str(relative)).read_bytes() == content
                for relative, content in parse_verifier_bundle(bundle)
            )

        if not await asyncio.to_thread(check_tests):
            raise ValueError("Held-out tests changed during validation")
        await asyncio.to_thread(
            audit_baseline,
            Path(item["baseline"]),
            set(item["test_paths"]),
            item["base_sha"],
        )
        payload = {
            "title": f"Mined regression {item['commit'][:12]}",
            "description": "History-mined draft: human review of prompt, scope and independence required",
            "repository_path": item["baseline"],
            "base_sha": item["base_sha"],
            "prompt": f"Repair the regression in {', '.join(item['production_paths'])}. Preserve public behavior and change only those production files; do not edit tests or tooling.",
            "setup_spec": (
                [
                    {
                        "type": "command",
                        "key": "setup",
                        "argv": list(options.setup_command),
                        "timeout_seconds": options.timeout,
                    }
                ]
                if options.setup_command
                else []
            ),
            "scorer_spec": [
                {
                    "type": "command",
                    "key": "held-out-regression",
                    "argv": list(test_argv(options.test_command, item["test_paths"])),
                    "timeout_seconds": options.timeout,
                    "required": True,
                },
                {
                    "type": "diff",
                    "key": "source-only",
                    "allowed": item["production_paths"],
                    "required": True,
                },
            ],
            "path_policy": {"base_expectation": "required_scorer_fails"},
            "verifier_bundle_path": str(private / "verifier.json"),
            "verifier_bundle_sha256": item["verifier_sha256"],
        }
        await asyncio.to_thread(
            (private / "import.json").write_text, json.dumps(payload, indent=2)
        )
        return {
            **item,
            "status": "validated_draft",
            "validation_repetitions": options.repetitions,
            "import_payload": str(private / "import.json"),
        }
    finally:
        await asyncio.to_thread(
            (private / "scores.json").write_text, json.dumps(scores, indent=2)
        )
        await worktrees.cleanup(provisioned)


async def mine(
    repository: Path,
    commits: list[str],
    output: Path,
    options: Options,
    *,
    execute: bool = False,
) -> dict:
    if not 1 <= len(commits) <= 50 or len(set(commits)) != len(commits):
        raise ValueError("Provide 1–50 distinct candidate commits")
    if execute and (
        not options.test_command
        or not options.failure_pattern
        or not 1 <= options.repetitions <= 5
        or not 1 <= options.timeout <= 3600
    ):
        raise ValueError(
            "Validation needs a test argv, assertion pattern, 1–5 repetitions and bounded timeout"
        )
    re.compile(options.failure_pattern)
    await asyncio.to_thread(output.mkdir, mode=0o700, parents=True, exist_ok=False)
    accepted, rejected = [], []
    for index, commit in enumerate(commits, 1):
        try:
            item = await asyncio.to_thread(candidate, repository, commit, options)
            if execute:
                item = await asyncio.to_thread(prepare, repository, item, output)
                item = await validate(item, options, output, index)
            else:
                item["status"] = "discovered_unvalidated"
            accepted.append(item)
        except (
            ValueError,
            OSError,
            UnicodeError,
            subprocess.CalledProcessError,
            WorktreeError,
        ) as exc:
            rejected.append({"commit": commit, "reason": str(exc)})
    report = {
        "schema_version": 1,
        "mode": "validated_drafts" if execute else "discovery_only",
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "cases": accepted,
        "rejected": rejected,
        "warnings": [
            "No cases are auto-published; human prompt/scope review and application validation remain required.",
            "Sibling verifier/reference files are not protected by an OS isolation boundary.",
            "Commit dates and private-source declarations do not prove absence from model training data.",
        ],
    }
    await asyncio.to_thread(
        (output / "report.json").write_text, json.dumps(report, indent=2)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--commits", nargs="+", help="1–50 full commit SHAs")
    selection.add_argument(
        "--revision-range", help="Local history range, e.g. main~200..main; no fetch"
    )
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--max-scan", type=int, default=500)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory; never overwrites"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Execute explicitly supplied repo setup/test commands",
    )
    parser.add_argument(
        "--test-command",
        type=json.loads,
        default=[],
        help="JSON argv, not a shell string; standalone {test_paths} expands to held-out paths",
    )
    parser.add_argument("--setup-command", type=json.loads, default=[])
    parser.add_argument("--test-glob", action="append")
    parser.add_argument("--failure-pattern", default="AssertionError")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument(
        "--source-visibility",
        choices=("public", "private", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--training-cutoff", help="Operator-declared YYYY-MM-DD; not model-verified"
    )
    args = parser.parse_args()
    for argv in (args.test_command, args.setup_command):
        if not isinstance(argv, list) or any(
            not isinstance(arg, str) or not arg for arg in argv
        ):
            parser.error("Commands must be JSON arrays of non-empty strings")
    options = Options(
        tuple(args.test_glob or TEST_GLOBS),
        tuple(args.test_command),
        tuple(args.setup_command),
        args.failure_pattern,
        args.timeout,
        args.repetitions,
        args.source_visibility,
        args.training_cutoff,
    )
    repository = args.repo.resolve()
    scanned_rejections = []
    commits = args.commits
    if args.revision_range:
        if (
            args.revision_range.startswith("-")
            or not 1 <= args.max_candidates <= 50
            or not 1 <= args.max_scan <= 5000
        ):
            parser.error(
                "History scanning requires a non-option range, 1–50 candidates and 1–5000 scanned commits"
            )
        commits = []
        for commit in (
            git(
                repository,
                "rev-list",
                f"--max-count={args.max_scan}",
                args.revision_range,
                "--",
            )
            .decode()
            .split()
        ):
            try:
                candidate(repository, commit, options)
                commits.append(commit)
            except (ValueError, subprocess.CalledProcessError, UnicodeError) as exc:
                scanned_rejections.append({"commit": commit, "reason": str(exc)})
            if len(commits) >= args.max_candidates:
                break
        if not commits:
            parser.error(
                "No eligible test-and-source commits found in the bounded history range"
            )
    report = asyncio.run(
        mine(
            repository,
            commits,
            args.output.resolve(),
            options,
            execute=args.validate,
        )
    )
    if scanned_rejections:
        report["history_scan_rejections"] = scanned_rejections
        (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "accepted": report["accepted_count"],
                "rejected": report["rejected_count"],
                "report": str(args.output.resolve() / "report.json"),
            }
        )
    )


if __name__ == "__main__":
    main()

"""Prepare isolated T3 benchmark baselines and verify them without running an agent.

Run with the backend virtualenv; generated repositories/evidence stay outside UIagg.
The private directory is excluded from case Git history, not an OS security boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.scorers import (
    CommandScorerSpec,
    DiffConstraintSpec,
    score_command,
    score_diff_constraints,
)
from evals.verifier_bundles import (
    build_verifier_bundle,
    materialize_verifier_bundle,
)
from evals.worktrees import WorktreeService

ROOT = Path(__file__).resolve().parents[2]
FILTERS = (
    "@t3tools/contracts...",
    "@t3tools/shared...",
    "t3...",
    "@t3tools/desktop...",
    "@t3tools/web...",
)
SETUP_ARGV = (
    "env",
    "COREPACK_ENABLE_NETWORK=0",
    "corepack",
    "pnpm",
    "install",
    "--offline",
    "--frozen-lockfile",
    "--ignore-scripts",
    *(argument for name in FILTERS for argument in ("--filter", name)),
)


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def extract_baseline(archive: bytes, destination: Path, withheld: set[str]) -> None:
    """Exclude held-out files before the first commit, including their Git blobs."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        members = []
        for member in source.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise ValueError(f"Unsafe source archive path: {member.name}")
            if member.name not in withheld:
                members.append(member)
        source.extractall(destination, members=members, filter="data")


def audit_baseline(repository: Path, withheld: set[str], expected_sha: str) -> dict:
    if git(repository, "rev-list", "--count", "--all").strip() != b"1":
        raise ValueError("Baseline must contain exactly one commit")
    if git(repository, "remote").strip():
        raise ValueError("Baseline must not have upstream remotes")
    if git(repository, "status", "--porcelain").strip():
        raise ValueError("Baseline is not clean")
    if git(repository, "rev-parse", "HEAD").decode().strip() != expected_sha:
        raise ValueError("Baseline commit does not match")
    tracked = set(git(repository, "ls-files", "-z").decode().split("\0"))
    if tracked & withheld or any(
        (repository / path).exists() or (repository / path).is_symlink()
        for path in withheld
    ):
        raise ValueError("A held-out test leaked into the baseline")
    return {
        "commits": 1,
        "remotes": [],
        "clean": True,
        "held_out_paths_absent": sorted(withheld),
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


async def prepare(source: Path, manifest_path: Path, output: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    reference = manifest["reference_commit"]
    if git(source, "rev-parse", "HEAD").decode().strip() != reference:
        raise ValueError("Source checkout does not match the pinned reference")
    # Export committed files, never local credentials, caches, or installed packages.
    archive = git(source, "archive", "--format=tar", reference)
    withheld = {case["verifier_test_path"] for case in manifest["cases"]}
    repositories = output / "repositories"
    private = output / "private"
    repositories.mkdir()
    private.mkdir(mode=0o700)
    worktrees = WorktreeService(output / "worktrees")
    results = []
    for index, case in enumerate(manifest["cases"], 1):
        slug = case["id"]
        print(f"Preparing {slug}", flush=True)
        repository = repositories / slug
        repository.mkdir()
        extract_baseline(archive, repository, withheld)
        patch = manifest_path.parent / case["validation_patch"]
        if (
            hashlib.sha256(patch.read_bytes()).hexdigest()
            != case["validation_patch_sha256"]
        ):
            raise ValueError(f"Patch checksum mismatch: {slug}")
        git(repository, "init", "--quiet")
        git(repository, "apply", str(patch))
        git(repository, "add", ".")
        git(
            repository,
            "-c",
            "user.name=Eval Baseline",
            "-c",
            "user.email=eval-baseline@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Benchmark baseline",
        )
        base_sha = git(repository, "rev-parse", "HEAD").decode().strip()
        audit = audit_baseline(repository, withheld, base_sha)
        test_path = case["verifier_test_path"]
        test_content = git(source, "show", f"{reference}:{test_path}").decode()
        bundle = build_verifier_bundle([{"path": test_path, "content": test_content}])
        bundle_path = private / f"{slug}.verifier.json"
        bundle_path.write_bytes(bundle)
        setup_spec = {
            "type": "command",
            "key": "locked-offline-dependencies",
            "argv": list(SETUP_ARGV),
            "timeout_seconds": 180,
        }
        test_argv = [
            "node",
            "node_modules/vite-plus/bin/vp",
            "test",
            "run",
            test_path,
            "--config",
            "vite.config.ts",
            "--testTimeout",
            "5000",
        ]
        scorer_spec = [
            {
                "type": "command",
                "key": "held-out-regression",
                "argv": test_argv,
                "timeout_seconds": 60,
                "required": True,
            },
            {
                "type": "diff",
                "key": "production-only",
                "allowed": [case["production_path"]],
                "forbidden": [
                    "**/*.test.*",
                    "**/package.json",
                    "pnpm-lock.yaml",
                    "vite.config.ts",
                    "AGENTS.md",
                ],
                "required": True,
            },
        ]
        payload = {
            "title": f"T3 Code: {slug}",
            "description": "External regression benchmark",
            "repository_path": str(repository),
            "base_sha": base_sha,
            "prompt": case["task_prompt"],
            "setup_spec": [setup_spec],
            "scorer_spec": scorer_spec,
            "path_policy": {"base_expectation": "required_scorer_fails"},
            "verifier_bundle_path": str(bundle_path),
            "verifier_bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        }
        provisioned = await worktrees.provision(repository, base_sha, index)
        try:
            assert not any((provisioned.path / path).exists() for path in withheld)
            setup = await score_command(
                CommandScorerSpec(
                    key=setup_spec["key"], argv=SETUP_ARGV, timeout_seconds=180
                ),
                provisioned.path,
            )
            if setup.status != "pass":
                raise RuntimeError(f"{slug} setup: {setup.summary}: {setup.evidence}")
            # Match scheduler ordering: inspect agent diff before installing held-out files.
            baseline_changes = await worktrees.changed_paths(provisioned)
            assert baseline_changes == set(), baseline_changes
            materialize_verifier_bundle(bundle, provisioned.path)
            command_spec = CommandScorerSpec(
                "held-out-regression", tuple(test_argv), timeout_seconds=60
            )
            buggy = await score_command(
                command_spec, provisioned.path, capture_full_output=True
            )
            if buggy.status != "fail" or buggy.value.get("exit_code") != 1:
                raise RuntimeError(
                    f"{slug} baseline did not fail normally: {buggy.summary}"
                )
            # Do not accept an infrastructure/import failure as a valid regression.
            output_text = buggy.evidence.get("stdout", "") + buggy.evidence.get(
                "stderr", ""
            )
            if "AssertionError" not in output_text or "Tests " not in output_text:
                raise RuntimeError(
                    f"{slug} baseline lacks regression assertion evidence"
                )
            git(provisioned.path, "apply", "-R", str(patch))
            reference_changes = (await worktrees.changed_paths(provisioned)) - {
                test_path
            }
            assert reference_changes == {case["production_path"]}, reference_changes
            diff = score_diff_constraints(
                DiffConstraintSpec(
                    "production-only", allowed=(case["production_path"],)
                ),
                reference_changes,
            )
            fixed = await score_command(
                command_spec, provisioned.path, capture_full_output=True
            )
            if fixed.status != "pass" or diff.status != "pass":
                raise RuntimeError(f"{slug} reference did not pass: {fixed.summary}")
            assert (provisioned.path / test_path).read_text() == test_content
            write_json(
                private / f"{slug}.scores.json",
                {
                    "setup": asdict(setup),
                    "buggy": asdict(buggy),
                    "reference": asdict(fixed),
                    "reference_diff": asdict(diff),
                },
            )
        finally:
            await worktrees.cleanup(provisioned)
        audit_baseline(repository, withheld, base_sha)
        write_json(private / f"{slug}.import.json", payload)
        results.append(
            {
                "id": slug,
                "base_sha": base_sha,
                "repository_path": str(repository),
                "isolation_audit": audit,
                "verifier_bundle_sha256": payload["verifier_bundle_sha256"],
                "baseline_score": buggy.status,
                "reference_score": fixed.status,
                "reference_diff_score": diff.status,
                "import_payload": str(private / f"{slug}.import.json"),
            }
        )
        print(f"Validated {slug}: baseline fail, reference pass, diff pass", flush=True)
    assert not list((output / "worktrees").glob("attempt-*"))
    report = {
        "schema_version": 1,
        "status": "packaged_and_scorer_verified",
        "upstream_reference": reference,
        "output_directory": str(output),
        "agent_runs": 0,
        "case_count": len(results),
        "cases": results,
        "worktree_cleanup_verified": True,
        "boundary": "Held-out files and history are excluded from each case repository; "
        "this is not OS-level protection against reading sibling directories.",
    }
    write_json(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".eval-sources/t3code")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "evals/t3code/cases.json"
    )
    arguments = parser.parse_args()
    output = Path(tempfile.mkdtemp(prefix="uiagg-t3-evals-", dir="/private/tmp"))
    print(f"Output: {output}", flush=True)
    report = asyncio.run(
        prepare(arguments.source.resolve(), arguments.manifest.resolve(), output)
    )
    print(f"Report: {report['output_directory']}/report.json", flush=True)


if __name__ == "__main__":
    main()

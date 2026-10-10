import asyncio
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import main
from artifacts import ArtifactStore
from database import Base, models
from database.schemas import RpcRequest
from evals.service import EvalService, _revision_payload
from evals.worktrees import WorktreeService


class RuntimeStub:
    def __init__(self) -> None:
        self.started: list[tuple] = []

    async def start(self, *args, **kwargs) -> None:
        self.started.append((args, kwargs))

    async def cancel(self, session_id: int) -> bool:
        return False


def initialize_git_fixture(repository) -> str:
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "evals@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Evals Test"],
        check=True,
    )
    (repository / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-q", "-m", "fixture"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def dispatch(dispatcher, db, method, params=None):
    response = await dispatcher.dispatch(
        RpcRequest(id=1, method=method, params=params or {}), db
    )
    assert "error" not in response, response
    return response["result"]


@pytest.mark.asyncio
async def test_sqlite_dispatch_and_durable_events(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(main, "SessionLocal", session_factory)

    runtime = RuntimeStub()
    dispatcher = main.RpcDispatcher(runtime)
    async with session_factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(tmp_path), "name": "Test"},
        )
        session = await dispatch(
            dispatcher,
            db,
            "session.create",
            {"workspace_id": workspace["id"], "provider": "codex"},
        )
        sent = await dispatch(
            dispatcher,
            db,
            "session.send",
            {"session_id": session["id"], "content": "Inspect the project"},
        )
        second_session = await dispatch(
            dispatcher,
            db,
            "session.create",
            {"workspace_id": workspace["id"], "provider": "codex"},
        )
        overlap = await dispatcher.dispatch(
            RpcRequest(
                id=2,
                method="session.send",
                params={"session_id": second_session["id"], "content": "Overlap"},
            ),
            db,
        )
        assert overlap["error"]["code"] == -32010

    run_id = sent["run_id"]
    assert runtime.started[0][0][:2] == (session["id"], run_id)
    assert runtime.started[0][1] == {"mode": "chat"}
    started = await main.persist_event(
        session["id"], run_id, "session.started", {"pid": 123}, None
    )
    assistant = await main.persist_event(
        session["id"],
        run_id,
        "assistant.text",
        {
            "content": "Inspection complete",
            "item": {"type": "agent_message", "metadata": {"tokens": 10}},
        },
        "item-1",
    )
    completed = await main.persist_event(
        session["id"], run_id, "session.completed", {"return_code": 0}, None
    )

    async with session_factory() as db:
        history = await dispatch(
            dispatcher,
            db,
            "session.history",
            {"session_id": session["id"]},
        )
        stored_session = await db.get(models.Session, session["id"])

    assert started.sequence < assistant.sequence < completed.sequence
    assert [message["role"] for message in history["conversation"]] == [
        "user",
        "assistant",
    ]
    assert history["conversation"][1]["content"] == "Inspection complete"
    assert history["conversation"][1]["run_id"] == run_id
    assert history["events"][1]["payload"]["item"]["metadata"] == {"tokens": 10}
    assert history["events"][1]["sequence"] == assistant.sequence
    assert history["has_more"] is False
    assert stored_session and stored_session.status == "completed"

    async with session_factory() as db:
        run_record = await dispatch(
            dispatcher,
            db,
            "run.get",
            {"run_id": run_id},
        )
        run_events = await dispatch(
            dispatcher,
            db,
            "run.events",
            {"run_id": run_id, "limit": 2},
        )

    assert run_record["kind"] == "chat"
    assert run_record["session_id"] == session["id"]
    assert run_record["workspace_path"] == str(tmp_path)
    assert [event["type"] for event in run_events["events"]] == [
        "session.started",
        "assistant.text",
    ]
    assert run_events["has_more"] is True

    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_writer = artifact_store.open_writer(run_id, "raw_jsonl")
    artifact_writer.write(b'{"type":"turn.completed"}\n')
    stored_artifact = artifact_writer.finish()
    await main.persist_artifact(run_id, stored_artifact)
    async with session_factory() as db:
        artifacts = await dispatch(
            dispatcher,
            db,
            "run.artifacts",
            {"run_id": run_id},
        )

    assert len(artifacts) == 1
    assert artifacts[0]["artifact_type"] == "raw_jsonl"
    assert artifacts[0]["sha256"] == stored_artifact.sha256

    async with session_factory() as db:
        eval_run = models.Run(
            kind="eval",
            eval_attempt_id=99,
            workspace_path=str(tmp_path / "disposable-worktree"),
            status="queued",
            prompt="Run the eval",
        )
        db.add(eval_run)
        await db.commit()
        await db.refresh(eval_run)
        eval_run_id = eval_run.id

    await main.persist_event(None, eval_run_id, "session.started", {"pid": 456}, None)
    await main.persist_event(
        None, eval_run_id, "session.completed", {"return_code": 0}, None
    )
    async with session_factory() as db:
        eval_record = await dispatch(
            dispatcher,
            db,
            "run.get",
            {"run_id": eval_run_id},
        )
        eval_events = await dispatch(
            dispatcher,
            db,
            "run.events",
            {"run_id": eval_run_id},
        )

    assert eval_record["kind"] == "eval"
    assert eval_record["session_id"] is None
    assert eval_record["eval_attempt_id"] == 99
    assert [event["type"] for event in eval_events["events"]] == [
        "session.started",
        "session.completed",
    ]

    async with session_factory() as db:
        renamed = await dispatch(
            dispatcher,
            db,
            "workspace.rename",
            {"workspace_id": workspace["id"], "name": "Renamed project"},
        )
        git_status = await dispatch(
            dispatcher,
            db,
            "workspace.git_status",
            {"workspace_id": workspace["id"]},
        )
        deleted_session = await dispatch(
            dispatcher,
            db,
            "session.delete",
            {"session_id": session["id"]},
        )
        deleted_workspace = await dispatch(
            dispatcher,
            db,
            "workspace.delete",
            {"workspace_id": workspace["id"]},
        )

    assert renamed["name"] == "Renamed project"
    assert git_status == {
        "is_repository": False,
        "is_root": False,
        "branch": None,
        "detached": False,
        "files": [],
        "remotes": [],
        "index_token": None,
        "dirty_count": 0,
        "staged_count": 0,
        "unstaged_count": 0,
    }
    assert deleted_session == {"deleted": True, "session_id": session["id"]}
    assert deleted_workspace == {"deleted": True, "workspace_id": workspace["id"]}
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_schema_rejects_invalid_persisted_types(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, path, name) VALUES (1, '/tmp/project', 'Project')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_id, provider, status) "
                "VALUES (1, 1, 'codex', 'idle')"
            )
        )

    for statement in (
        "INSERT INTO sessions (workspace_id, provider, status) VALUES (1, 'fake', 'idle')",
        "INSERT INTO sessions (workspace_id, provider, status) VALUES (1, 'codex', 'unknown')",
        "INSERT INTO runs (session_id, status, prompt) VALUES (1, 'unknown', 'Hi')",
        "INSERT INTO messages (session_id, role, content) VALUES (1, 'system', 'Hi')",
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text(statement))
    await engine.dispose()


@pytest.mark.asyncio
async def test_eval_case_drafts_are_persistent_and_published_revisions_are_immutable(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cases.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    dispatcher = main.RpcDispatcher(RuntimeStub())

    async with session_factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(tmp_path), "name": "Cases"},
        )
        created = await dispatch(
            dispatcher,
            db,
            "eval.case.create",
            {
                "title": "Fix parser regression",
                "description": "A representative bug",
                "workspace_id": workspace["id"],
                "prompt": "Fix the failing parser test",
                "base_sha": "a" * 40,
            },
        )
        updated = await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                "case_id": created["id"],
                "revision_id": created["latest_revision"]["id"],
                "scorer_spec": [{"type": "command", "argv": ["pytest", "-q"]}],
            },
        )
        listed = await dispatch(dispatcher, db, "eval.case.list")

    assert updated["latest_revision"]["status"] == "draft"
    assert updated["latest_revision"]["validation_status"] == "not_validated"
    assert updated["latest_revision"]["scorer_spec"][0]["type"] == "command"
    assert [case["title"] for case in listed] == ["Fix parser regression"]

    async with session_factory() as db:
        revision = await db.get(
            models.EvalCaseRevision, created["latest_revision"]["id"]
        )
        assert revision
        revision.status = "published"
        revision.content_hash = "b" * 64
        revision.validation_status = "valid"
        revision.published_at = main.datetime.now(main.UTC)
        await db.commit()
        response = await dispatcher.dispatch(
            RpcRequest(
                id=2,
                method="eval.case.update_draft",
                params={
                    "case_id": created["id"],
                    "revision_id": revision.id,
                    "prompt": "Mutate published input",
                },
            ),
            db,
        )

    assert response["error"] == {
        "code": -32010,
        "message": "Published case revisions are immutable",
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_eval_case_validation_and_publish_use_disposable_worktree(
    tmp_path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    head = await asyncio.to_thread(initialize_git_fixture, repository)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publish.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    dispatcher = main.RpcDispatcher(RuntimeStub())
    worktree_root = tmp_path / "eval-worktrees"
    dispatcher.eval_service = EvalService(WorktreeService(worktree_root))

    async with session_factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(repository), "name": "Fixture"},
        )
        created = await dispatch(
            dispatcher,
            db,
            "eval.case.create",
            {
                "title": "Repair the fixture",
                "workspace_id": workspace["id"],
                "prompt": "Make the verifier pass",
            },
        )
        revision_id = created["latest_revision"]["id"]
        assert created["latest_revision"]["base_sha"] == head
        await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                "case_id": created["id"],
                "revision_id": revision_id,
                "scorer_spec": [
                    {
                        "type": "command",
                        "key": "verifier",
                        "argv": [sys.executable, "-c", "raise SystemExit(1)"],
                    }
                ],
            },
        )
        validated = await dispatch(
            dispatcher,
            db,
            "eval.case.validate",
            {"case_id": created["id"], "revision_id": revision_id},
        )
        published = await dispatch(
            dispatcher,
            db,
            "eval.case.publish",
            {"case_id": created["id"], "revision_id": revision_id},
        )
        duplicate = await dispatcher.dispatch(
            RpcRequest(
                id=2,
                method="eval.case.publish",
                params={"case_id": created["id"], "revision_id": revision_id},
            ),
            db,
        )

    assert validated["latest_revision"]["validation_status"] == "valid"
    assert validated["latest_revision"]["validation_details"]["base_results"] == [
        {
            "key": "verifier",
            "status": "fail",
            "summary": "Command exited with code 1",
        }
    ]
    assert published["latest_revision"]["status"] == "published"
    assert len(published["latest_revision"]["content_hash"]) == 64
    assert not list(worktree_root.glob("attempt-*"))
    assert duplicate["error"] == {
        "code": -32010,
        "message": "Case revision is already published",
    }
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("held_out", [False, True])
async def test_revise_preserves_published_input_and_copies_owned_verifier(
    tmp_path, held_out
):
    repository = tmp_path / "repository"
    repository.mkdir()
    await asyncio.to_thread(initialize_git_fixture, repository)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'revisions.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = ArtifactStore(tmp_path / "artifacts")
    dispatcher = main.RpcDispatcher(RuntimeStub())
    dispatcher.eval_service = EvalService(
        WorktreeService(tmp_path / "worktrees"), artifact_store=store
    )
    async with factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(repository), "name": "Fixture"},
        )
        case = await dispatch(
            dispatcher,
            db,
            "eval.case.create",
            {
                "title": "Revision fixture",
                "workspace_id": workspace["id"],
                "prompt": "Original task",
            },
        )
        identity = {"case_id": case["id"], "revision_id": case["latest_revision"]["id"]}
        premature = await dispatcher.dispatch(
            RpcRequest(id=2, method="eval.case.revise", params=identity), db
        )
        assert premature["error"]["code"] == -32010
        await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                **identity,
                "setup_spec": [
                    {
                        "type": "command",
                        "argv": [sys.executable, "-c", "print('setup')"],
                    }
                ],
                "scorer_spec": [
                    {
                        "type": "command",
                        "key": "regression",
                        "argv": [sys.executable, "-c", "raise SystemExit(1)"],
                    },
                    {"type": "diff", "key": "scope", "allowed": ["README.md"]},
                ],
                **(
                    {
                        "verifier_files": [
                            {"path": "hidden/check.py", "content": "assert False\n"}
                        ]
                    }
                    if held_out
                    else {}
                ),
            },
        )
        await dispatch(dispatcher, db, "eval.case.validate", identity)
        published = await dispatch(dispatcher, db, "eval.case.publish", identity)
        original = published["latest_revision"]
        suite = await dispatch(
            dispatcher, db, "eval.suite.create", {"name": "Frozen original"}
        )
        suite_identity = {
            "suite_id": suite["id"],
            "version_id": suite["latest_version"]["id"],
        }
        await dispatch(
            dispatcher,
            db,
            "eval.suite.update_draft",
            {**suite_identity, "case_revision_ids": [identity["revision_id"]]},
        )
        frozen = await dispatch(dispatcher, db, "eval.suite.freeze", suite_identity)
        revised = await dispatch(dispatcher, db, "eval.case.revise", identity)
        draft = revised["latest_revision"]
        assert draft["revision"] == 2 and draft["status"] == "draft"
        assert draft["validation_status"] == "not_validated"
        assert draft["content_hash"] is None and draft["published_at"] is None
        for field in (
            "prompt",
            "base_sha",
            "workspace_id",
            "setup_spec",
            "scorer_spec",
            "path_policy",
        ):
            assert draft[field] == original[field]
        repeated = await dispatch(dispatcher, db, "eval.case.revise", identity)
        assert repeated["latest_revision"]["id"] == draft["id"]
        if held_out:
            assert draft["verifier_artifact_id"] != original["verifier_artifact_id"]
            copied = await db.get(models.RunArtifact, draft["verifier_artifact_id"])
            source = await db.get(models.RunArtifact, original["verifier_artifact_id"])
            assert copied.relative_path.startswith(
                f"eval-case-{draft['id']}/verifier_bundle/"
            )
            assert store.read_verified_bytes(
                copied.relative_path, copied.sha256
            ) == store.read_verified_bytes(source.relative_path, source.sha256)
        await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                "case_id": case["id"],
                "revision_id": draft["id"],
                "prompt": "Only change README.md",
            },
        )
        validated = await dispatch(
            dispatcher,
            db,
            "eval.case.validate",
            {"case_id": case["id"], "revision_id": draft["id"]},
        )
        assert validated["latest_revision"]["validation_status"] == "valid"
        source_row = await db.get(models.EvalCaseRevision, original["id"])
        await db.refresh(source_row)
        assert _revision_payload(source_row) == original
        unchanged_suite = await dispatch(
            dispatcher, db, "eval.suite.get", {"suite_id": suite["id"]}
        )
        for field in ("id", "version", "status", "content_hash", "cases"):
            assert (
                unchanged_suite["latest_version"][field]
                == frozen["latest_version"][field]
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_held_out_verifier_is_materialized_for_validation_and_checksum_checked(
    tmp_path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    await asyncio.to_thread(initialize_git_fixture, repository)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'held-out.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    dispatcher = main.RpcDispatcher(RuntimeStub())
    dispatcher.eval_service = EvalService(
        WorktreeService(tmp_path / "worktrees"), artifact_store=artifact_store
    )

    async with session_factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(repository), "name": "Fixture"},
        )
        created = await dispatch(
            dispatcher,
            db,
            "eval.case.create",
            {
                "title": "Held-out verifier",
                "workspace_id": workspace["id"],
                "prompt": "Create done.txt",
            },
        )
        revision_id = created["latest_revision"]["id"]
        updated = await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                "case_id": created["id"],
                "revision_id": revision_id,
                "setup_spec": [
                    {
                        "type": "command",
                        "argv": [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('setup.txt').write_text('ready')",
                        ],
                    }
                ],
                "verifier_files": [
                    {
                        "path": "tests/hidden_verifier.py",
                        "content": "from pathlib import Path\n"
                        "assert Path('setup.txt').read_text() == 'ready'\n"
                        "raise SystemExit(0 if Path('done.txt').exists() else 1)\n",
                    }
                ],
                "scorer_spec": [
                    {
                        "type": "command",
                        "key": "hidden-verifier",
                        "argv": [sys.executable, "tests/hidden_verifier.py"],
                    }
                ],
            },
        )
        validated = await dispatch(
            dispatcher,
            db,
            "eval.case.validate",
            {"case_id": created["id"], "revision_id": revision_id},
        )
        artifact = await db.get(
            models.RunArtifact, updated["latest_revision"]["verifier_artifact_id"]
        )

    assert validated["latest_revision"]["validation_status"] == "valid"
    assert validated["latest_revision"]["validation_details"]["held_out_paths"] == [
        "tests/hidden_verifier.py"
    ]
    assert (
        validated["latest_revision"]["validation_details"]["base_results"][0]["summary"]
        == "Command exited with code 1"
    )
    assert artifact is not None
    assert not (repository / "tests" / "hidden_verifier.py").exists()
    assert not (repository / "setup.txt").exists()

    (artifact_store.root / artifact.relative_path).write_bytes(b"tampered")
    async with session_factory() as db:
        invalid = await dispatch(
            dispatcher,
            db,
            "eval.case.validate",
            {"case_id": created["id"], "revision_id": revision_id},
        )
    assert invalid["latest_revision"]["validation_status"] == "invalid"
    assert "checksum" in invalid["latest_revision"]["validation_details"]["problems"][0]
    await engine.dispose()


@pytest.mark.asyncio
async def test_eval_suites_freeze_and_config_snapshots_are_redacted(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    dispatcher = main.RpcDispatcher(RuntimeStub())

    async with session_factory() as db:
        workspace = models.Workspace(path=str(tmp_path), name="Catalog")
        case = models.EvalCase(title="Published case", description="")
        db.add_all([workspace, case])
        await db.flush()
        revision = models.EvalCaseRevision(
            case_id=case.id,
            revision=1,
            status="published",
            content_hash="c" * 64,
            workspace_id=workspace.id,
            base_sha="a" * 40,
            prompt="Repair it",
            setup_spec_json=[],
            scorer_spec_json=[{"type": "command", "argv": ["true"]}],
            path_policy_json={},
            validation_status="valid",
            validation_details_json={},
            published_at=main.datetime.now(main.UTC),
        )
        db.add(revision)
        await db.commit()
        await db.refresh(revision)

        suite = await dispatch(dispatcher, db, "eval.suite.create", {"name": "Core"})
        suite = await dispatch(
            dispatcher,
            db,
            "eval.suite.update_draft",
            {
                "suite_id": suite["id"],
                "version_id": suite["latest_version"]["id"],
                "case_revision_ids": [revision.id],
            },
        )
        frozen = await dispatch(
            dispatcher,
            db,
            "eval.suite.freeze",
            {
                "suite_id": suite["id"],
                "version_id": suite["latest_version"]["id"],
            },
        )
        config_a = await dispatch(
            dispatcher,
            db,
            "eval.config.capture",
            {
                "name": "Baseline",
                "model": "codex-a",
                "reasoning_effort": "medium",
                "codex_config": {"api_token": "must-not-persist", "feature": True},
                "sandbox_policy": {"mode": "workspace-write", "network": False},
            },
        )
        config_b = await dispatch(
            dispatcher,
            db,
            "eval.config.capture",
            {
                "name": "Candidate",
                "model": "codex-b",
                "reasoning_effort": "high",
                "instruction_preamble": "Keep changes focused.",
            },
        )
        difference = await dispatch(
            dispatcher,
            db,
            "eval.config.diff",
            {
                "left_snapshot_id": config_a["snapshot"]["id"],
                "right_snapshot_id": config_b["snapshot"]["id"],
            },
        )
        plan = {
            "name": "Core comparison",
            "suite_version_id": frozen["latest_version"]["id"],
            "config_snapshot_ids": [
                config_a["snapshot"]["id"],
                config_b["snapshot"]["id"],
            ],
            "samples_per_case": 2,
            "concurrency": 1,
            "timeout_seconds": 600,
        }
        preflight = await dispatch(dispatcher, db, "eval.experiment.preflight", plan)
        experiment = await dispatch(dispatcher, db, "eval.experiment.create", plan)
        listed_experiments = await dispatch(dispatcher, db, "eval.experiment.list")

    assert frozen["latest_version"]["status"] == "frozen"
    assert frozen["latest_version"]["cases"][0]["revision_id"] == revision.id
    assert len(frozen["latest_version"]["content_hash"]) == 64
    assert config_a["snapshot"]["codex_config"]["api_token"] == "[REDACTED]"
    assert config_b["snapshot"]["instructions"] == [
        {"kind": "preamble", "content": "Keep changes focused."}
    ]
    assert {item["field"] for item in difference["differences"]} >= {
        "model",
        "reasoning_effort",
    }
    assert preflight["attempt_count"] == 4
    assert preflight["configuration_differences"] == [
        "model",
        "reasoning_effort",
        "instructions",
        "codex_config",
    ]
    assert config_a["snapshot"]["reproducibility_warnings"]
    assert config_b["snapshot"]["sandbox_policy"] == {
        "mode": "workspace-write",
        "network": False,
    }
    assert experiment["status"] == "ready"
    assert experiment["attempt_status_counts"] == {"queued": 4}
    assert [item["config_snapshot_id"] for item in experiment["attempts"]] == [
        config_a["snapshot"]["id"],
        config_b["snapshot"]["id"],
        config_a["snapshot"]["id"],
        config_b["snapshot"]["id"],
    ]
    assert listed_experiments[0]["id"] == experiment["id"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_config_captures_workspace_instructions_and_verified_cli(
    tmp_path, monkeypatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    await asyncio.to_thread(initialize_git_fixture, repository)
    (repository / "AGENTS.md").write_text("Project guidance\napi_key=never-store-me\n")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "AGENTS.override.md").write_text("Global override")
    monkeypatch.setenv("CODEX_HOME", str(profile))
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "evals.configs.detect_cli_version", AsyncMock(return_value="codex-cli 1.2.3")
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'capture.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    dispatcher = main.RpcDispatcher(
        RuntimeStub(), worktrees=WorktreeService(tmp_path / "worktrees")
    )
    async with session_factory() as db:
        workspace = models.Workspace(path=str(repository), name="Capture")
        db.add(workspace)
        await db.commit()
        values = {
            "name": "Captured",
            "workspace_id": workspace.id,
            "model": "pinned-model",
            "instruction_preamble": "Task preamble",
        }
        captured = await dispatch(dispatcher, db, "eval.config.capture", values)
        repeated = await dispatch(dispatcher, db, "eval.config.capture", values)
        snapshot = await db.get(models.EvalConfigSnapshot, captured["snapshot"]["id"])
        assert "never-store-me" not in str(snapshot.instructions_json)
    result = captured["snapshot"]
    assert result["cli_version"] == "codex-cli 1.2.3"
    assert [item["kind"] for item in result["instructions"]] == [
        "file",
        "file",
        "preamble",
    ]
    assert result["instructions"][0]["path"] == "$CODEX_HOME/AGENTS.override.md"
    assert result["instructions"][1]["redacted"] is True
    assert result["content_hash"] == repeated["snapshot"]["content_hash"]
    assert result["uncontrolled_inputs"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_chat_run_creates_prefilled_eval_case(tmp_path) -> None:
    repository = tmp_path / "source-repository"
    repository.mkdir()
    head = await asyncio.to_thread(initialize_git_fixture, repository)
    (repository / "README.md").write_text("dirty before run\n")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'from-run.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    diff_service = main.RunDiffService(session_factory)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    dispatcher = main.RpcDispatcher(RuntimeStub(), diff_service, artifact_store)
    dispatcher.eval_service.worktrees = WorktreeService(tmp_path / "case-worktrees")

    async with session_factory() as db:
        workspace = models.Workspace(path=str(repository), name="Source")
        session = models.Session(
            workspace=workspace, provider="codex", status="completed"
        )
        run = models.Run(
            kind="chat",
            session=session,
            workspace_path=str(repository),
            status="completed",
            prompt="Fix the parser regression",
        )
        db.add(run)
        await db.commit()
        run_id = run.id
        session_id = session.id
    await diff_service.capture(run_id, str(repository))
    await diff_service.refresh(run_id, final=True)
    async with session_factory() as db:
        db.add(
            models.RunEvent(
                session_id=session_id,
                run_id=run_id,
                source_event_id="verify-1",
                event_type="codex.item.completed",
                payload={
                    "item": {
                        "id": "verify-1",
                        "type": "command_execution",
                        "command": "pytest -q",
                        "exit_code": 0,
                    }
                },
            )
        )
        await db.commit()
        created = await dispatch(
            dispatcher, db, "eval.case.create_from_run", {"run_id": run_id}
        )
        artifact = await db.get(
            models.RunArtifact, created["latest_revision"]["starting_patch_artifact_id"]
        )
        configured = await dispatch(
            dispatcher,
            db,
            "eval.case.update_draft",
            {
                "case_id": created["id"],
                "revision_id": created["latest_revision"]["id"],
                "scorer_spec": [
                    {
                        "type": "file",
                        "key": "starting-state",
                        "path": "README.md",
                        "assertion": "contains",
                        "expected": "dirty before run",
                    }
                ],
                "path_policy": {"base_expectation": "required_scorer_passes"},
            },
        )
        validated = await dispatch(
            dispatcher,
            db,
            "eval.case.validate",
            {
                "case_id": created["id"],
                "revision_id": configured["latest_revision"]["id"],
            },
        )

    assert created["title"] == "Fix the parser regression"
    assert created["latest_revision"]["source_run_id"] == run_id
    assert created["latest_revision"]["base_sha"] == head
    assert created["latest_revision"]["validation_details"][
        "candidate_verifier_commands"
    ] == ["pytest -q"]
    assert artifact and b"dirty before run" in artifact_store.read_bytes(
        artifact.relative_path
    )
    assert validated["latest_revision"]["validation_status"] == "valid"
    assert (
        validated["latest_revision"]["validation_details"]["base_results"][0]["status"]
        == "pass"
    )
    await engine.dispose()

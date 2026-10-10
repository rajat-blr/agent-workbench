"""Registered workspace RPC handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    GitCommitParams,
    GitPushParams,
    GitStageParams,
    WorkspaceCloneGithub,
    WorkspaceCreate,
    WorkspaceIdParams,
    WorkspaceRename,
)
from git_workspace import git_status as _git_status
from git_workspace import staging_paths
from rpc_contract import CatalogListParams
from rpc_handlers.common import (
    RpcMethodError,
    _params,
    _resolve_workspace,
    _run_git_action,
    _workspace_dict,
)
from rpc_registry import rpc
from settings import settings


class WorkspaceHandlers:
    @rpc("workspace.clone_github")
    async def _rpc_workspace_clone_github(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        from github_repositories import clone_github_repository, github_repository

        values = _params(WorkspaceCloneGithub, params)
        canonical = github_repository(values.url)[2]
        async with self._repository_import_locks.setdefault(canonical, asyncio.Lock()):
            path, name = await clone_github_repository(
                values.url, settings.resolved_eval_repository_directory
            )
            workspace = await db.scalar(
                select(models.Workspace).where(models.Workspace.path == str(path))
            )
            if workspace is None:
                workspace = models.Workspace(path=str(path), name=name)
                db.add(workspace)
                await db.commit()
                await db.refresh(workspace)
            return _workspace_dict(workspace)

    @rpc("workspace.create")
    async def _rpc_workspace_create(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(WorkspaceCreate, params)
        if not values.name.strip():
            raise ValueError("Workspace name is required")
        workspace = models.Workspace(
            path=_resolve_workspace(values.path), name=values.name.strip()
        )
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
        return _workspace_dict(workspace)

    @rpc("workspace.list")
    async def _rpc_workspace_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(CatalogListParams, params)
        query = select(models.Workspace).limit(values.limit)
        if values.before_id is not None:
            query = query.order_by(models.Workspace.id.desc())
            if values.before_id:
                query = query.where(models.Workspace.id < values.before_id)
        else:
            query = query.order_by(models.Workspace.name, models.Workspace.id)
        workspaces = (await db.scalars(query)).all()
        return [_workspace_dict(workspace) for workspace in workspaces]

    @rpc("workspace.get")
    async def _rpc_workspace_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(WorkspaceIdParams, params)
        return _workspace_dict(await self._workspace(db, values.workspace_id))

    @rpc("workspace.rename")
    async def _rpc_workspace_rename(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(WorkspaceRename, params)
        if not values.name.strip():
            raise ValueError("Workspace name is required")
        workspace = await self._workspace(db, values.workspace_id)
        workspace.name = values.name.strip()
        await db.commit()
        await db.refresh(workspace)
        return _workspace_dict(workspace)

    @rpc("workspace.git_status")
    async def _rpc_workspace_git_status(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(WorkspaceIdParams, params)
        workspace = await self._workspace(db, values.workspace_id)
        return await _git_status(workspace.path)

    @rpc(
        "workspace.git_stage",
        "workspace.git_commit",
        "workspace.git_push_main",
        "workspace.git_push",
    )
    async def _rpc_workspace_git_stage(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        parameter_type = {
            "workspace.git_stage": GitStageParams,
            "workspace.git_commit": GitCommitParams,
            "workspace.git_push": GitPushParams,
            "workspace.git_push_main": WorkspaceIdParams,
        }[method]
        values = _params(parameter_type, params)
        workspace = await self._workspace(db, values.workspace_id)
        async with self._workspace_locks.setdefault(workspace.id, asyncio.Lock()):
            await db.rollback()
            workspace = await self._workspace(db, values.workspace_id)
            if await self._has_active_run(db, workspace_id=workspace.id):
                raise RpcMethodError(
                    -32010, "Wait for the active run to finish before using Git"
                )
            status = await _git_status(workspace.path)
            if not status["is_repository"]:
                raise RpcMethodError(-32030, "This workspace is not a Git repository")
            if not status["is_root"]:
                raise RpcMethodError(
                    -32030,
                    "Select the repository root as the workspace to use Git actions",
                )
            if not status["branch"]:
                raise RpcMethodError(
                    -32030, "Check out a branch before using Git actions"
                )
            if method == "workspace.git_push_main" and status["branch"] != "main":
                raise RpcMethodError(
                    -32030, "Switch to the main branch before using Git actions"
                )
            if (
                method != "workspace.git_push_main"
                and values.expected_branch != status["branch"]
            ):
                raise RpcMethodError(-32030, "Branch changed; refresh the Git review")
            if method == "workspace.git_stage":
                paths = staging_paths(status, values.paths)
                output = await _run_git_action(
                    workspace.path, "--literal-pathspecs", "add", "--", *paths
                )
                action = "staged"
            elif method == "workspace.git_commit":
                message = values.message.strip()
                if not message:
                    raise ValueError("Commit message is required")
                if not status["staged_count"]:
                    raise RpcMethodError(-32030, "Stage changes before committing")
                if values.index_token != status["index_token"]:
                    raise RpcMethodError(
                        -32030, "Staged contents changed; refresh the commit review"
                    )
                output = await _run_git_action(workspace.path, "commit", "-m", message)
                action = "committed"
            else:
                remote = values.remote if method == "workspace.git_push" else "origin"
                branch = values.branch if method == "workspace.git_push" else "main"
                if remote.startswith("-") or remote not in status["remotes"]:
                    raise ValueError("Select a configured Git remote")
                if branch.startswith("-"):
                    raise ValueError("Invalid destination branch")
                await _run_git_action(
                    workspace.path, "check-ref-format", f"refs/heads/{branch}"
                )
                output = await _run_git_action(
                    workspace.path,
                    "push",
                    "-u",
                    "--",
                    remote,
                    f"HEAD:refs/heads/{branch}",
                )
                action = "pushed"
            return {
                "action": action,
                "output": output,
                "status": await _git_status(workspace.path),
            }

    @rpc("workspace.delete")
    async def _rpc_workspace_delete(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(WorkspaceIdParams, params)
        workspace = await self._workspace(db, values.workspace_id)
        if await self._has_active_run(db, workspace_id=workspace.id):
            raise RpcMethodError(
                -32010, "Stop active sessions before removing this workspace"
            )
        await db.delete(workspace)
        await db.commit()
        return {"deleted": True, "workspace_id": values.workspace_id}

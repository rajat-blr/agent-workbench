"""Registered suites RPC handlers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    EvalSuiteCreate,
    EvalSuiteIdParams,
    EvalSuiteUpdateDraft,
    EvalSuiteVersionParams,
)
from evals.common import EvalServiceError, _params
from rpc_registry import rpc


class SuitesHandlers:
    async def _suite_payload(
        self, db: AsyncSession, suite: models.EvalSuite
    ) -> dict[str, Any]:
        versions = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersion)
                    .where(models.EvalSuiteVersion.suite_id == suite.id)
                    .order_by(models.EvalSuiteVersion.version.desc())
                )
            ).all()
        )
        latest = versions[0]
        members = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersionCase)
                    .where(models.EvalSuiteVersionCase.suite_version_id == latest.id)
                    .order_by(models.EvalSuiteVersionCase.ordinal)
                )
            ).all()
        )
        cases = []
        for member in members:
            revision = await db.get(models.EvalCaseRevision, member.case_revision_id)
            case = await db.get(models.EvalCase, revision.case_id) if revision else None
            if revision and case:
                cases.append(
                    {
                        "case_id": case.id,
                        "title": case.title,
                        "revision_id": revision.id,
                        "revision": revision.revision,
                        "ordinal": member.ordinal,
                    }
                )
        return {
            "id": suite.id,
            "name": suite.name,
            "description": suite.description,
            "created_at": suite.created_at.isoformat(),
            "updated_at": suite.updated_at.isoformat(),
            "latest_version": {
                "id": latest.id,
                "version": latest.version,
                "status": latest.status,
                "content_hash": latest.content_hash,
                "frozen_at": latest.frozen_at.isoformat() if latest.frozen_at else None,
                "cases": cases,
            },
        }

    @rpc("eval.suite.create")
    async def _rpc_eval_suite_create(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalSuiteCreate, params)
        if not values.name.strip():
            raise EvalServiceError(-32602, "Suite name is required")
        suite = models.EvalSuite(
            name=values.name.strip(), description=values.description.strip()
        )
        db.add(suite)
        await db.flush()
        db.add(models.EvalSuiteVersion(suite_id=suite.id, version=1, status="draft"))
        await db.commit()
        await db.refresh(suite)
        return await self._suite_payload(db, suite)

    @rpc("eval.suite.list")
    async def _rpc_eval_suite_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        suites = (
            await db.scalars(
                select(models.EvalSuite).order_by(models.EvalSuite.updated_at.desc())
            )
        ).all()
        return [await self._suite_payload(db, suite) for suite in suites]

    @rpc("eval.suite.get")
    async def _rpc_eval_suite_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalSuiteIdParams, params)
        suite = await db.get(models.EvalSuite, values.suite_id)
        if not suite:
            raise EvalServiceError(-32004, "Eval suite not found")
        return await self._suite_payload(db, suite)

    @rpc("eval.suite.update_draft")
    async def _rpc_eval_suite_update_draft(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalSuiteUpdateDraft, params)
        suite = await db.get(models.EvalSuite, values.suite_id)
        version = await db.get(models.EvalSuiteVersion, values.version_id)
        if not suite or not version or version.suite_id != suite.id:
            raise EvalServiceError(-32004, "Eval suite version not found")
        if version.status == "frozen":
            old_members = list(
                (
                    await db.scalars(
                        select(models.EvalSuiteVersionCase)
                        .where(
                            models.EvalSuiteVersionCase.suite_version_id == version.id
                        )
                        .order_by(models.EvalSuiteVersionCase.ordinal)
                    )
                ).all()
            )
            version = models.EvalSuiteVersion(
                suite_id=suite.id, version=version.version + 1, status="draft"
            )
            db.add(version)
            await db.flush()
            for member in old_members:
                db.add(
                    models.EvalSuiteVersionCase(
                        suite_version_id=version.id,
                        case_revision_id=member.case_revision_id,
                        ordinal=member.ordinal,
                    )
                )
        if values.name is not None:
            suite.name = values.name.strip()
        if values.description is not None:
            suite.description = values.description.strip()
        if values.case_revision_ids is not None:
            if len(values.case_revision_ids) != len(set(values.case_revision_ids)):
                raise EvalServiceError(-32602, "A case revision may appear only once")
            revisions = [
                await db.get(models.EvalCaseRevision, item)
                for item in values.case_revision_ids
            ]
            if any(item is None or item.status != "published" for item in revisions):
                raise EvalServiceError(
                    -32602, "Suites may contain only published case revisions"
                )
            await db.execute(
                delete(models.EvalSuiteVersionCase).where(
                    models.EvalSuiteVersionCase.suite_version_id == version.id
                )
            )
            for ordinal, revision_id in enumerate(values.case_revision_ids):
                db.add(
                    models.EvalSuiteVersionCase(
                        suite_version_id=version.id,
                        case_revision_id=revision_id,
                        ordinal=ordinal,
                    )
                )
        suite.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(suite)
        return await self._suite_payload(db, suite)

    @rpc("eval.suite.freeze")
    async def _rpc_eval_suite_freeze(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalSuiteVersionParams, params)
        suite = await db.get(models.EvalSuite, values.suite_id)
        version = await db.get(models.EvalSuiteVersion, values.version_id)
        if not suite or not version or version.suite_id != suite.id:
            raise EvalServiceError(-32004, "Eval suite version not found")
        if version.status != "draft":
            raise EvalServiceError(-32010, "Suite version is already frozen")
        members = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersionCase)
                    .where(models.EvalSuiteVersionCase.suite_version_id == version.id)
                    .order_by(models.EvalSuiteVersionCase.ordinal)
                )
            ).all()
        )
        if not members:
            raise EvalServiceError(
                -32010, "Add at least one published case before freezing"
            )
        canonical = json.dumps(
            [item.case_revision_id for item in members], separators=(",", ":")
        )
        version.content_hash = hashlib.sha256(canonical.encode()).hexdigest()
        version.status = "frozen"
        version.frozen_at = datetime.now(UTC)
        suite.updated_at = version.frozen_at
        await db.commit()
        await db.refresh(suite)
        return await self._suite_payload(db, suite)

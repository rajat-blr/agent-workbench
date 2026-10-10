"""Registered health RPC handlers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rpc_registry import rpc


class HealthHandlers:
    @rpc("health.check")
    async def _rpc_health_check(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        await db.execute(text("SELECT 1"))
        return {"status": "ok"}

"""Pooled async PostgreSQL access (checklist T041).

`Database.transaction()` is the unit of work: everything a stage writes (action states, audit rows, the jobs it
enqueues) commits or rolls back together (D-003). Rows come back as dicts. JSONB goes in via
`psycopg.types.json.Jsonb` and comes out as Python objects.

Windows note: psycopg's async mode cannot use the default Proactor event loop; use
`asyncio.WindowsSelectorEventLoopPolicy` for local runs (tests do this in conftest). Linux/Docker are unaffected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class Database:
    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._pool = AsyncConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=15)

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        """A pooled connection in autocommit mode (each statement commits on its own)."""
        async with self._pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """A pooled connection inside one transaction: commits on success, rolls back on any exception."""
        async with self._pool.connection() as conn, conn.transaction():
            yield conn

import uuid

import pytest

from contextrail.db import Database


async def test_transaction_commits(migrated_db):
    rid = uuid.uuid4()
    async with Database(migrated_db) as db:
        async with db.transaction() as c:
            await c.execute("insert into runs (id, source, request_text) values (%s, 'slack', 'x')", (rid,))
        async with db.connection() as c:
            row = await (await c.execute("select source from runs where id = %s", (rid,))).fetchone()
    assert row == {"source": "slack"}


async def test_transaction_rolls_back_everything_on_error(migrated_db):
    rid = uuid.uuid4()
    async with Database(migrated_db) as db:
        with pytest.raises(RuntimeError):
            async with db.transaction() as c:
                await c.execute("insert into runs (id, source, request_text) values (%s, 'slack', 'x')", (rid,))
                await c.execute("insert into jobs (kind) values ('rail.run')")
                raise RuntimeError("stage failed")
        async with db.connection() as c:
            runs = await (await c.execute("select count(*) as n from runs")).fetchone()
            jobs = await (await c.execute("select count(*) as n from jobs")).fetchone()
    assert runs["n"] == 0 and jobs["n"] == 0


async def test_pool_serves_concurrent_connections(migrated_db):
    import asyncio

    async with Database(migrated_db, max_size=4) as db:
        async def one(i):
            async with db.connection() as c:
                return (await (await c.execute("select %s::int as i, pg_sleep(0.05)", (i,))).fetchone())["i"]

        assert sorted(await asyncio.gather(*(one(i) for i in range(8)))) == list(range(8))

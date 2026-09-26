import psycopg
import pytest

from contextrail import migrate
from contextrail.migrate import Migration, MigrationDrift, apply_all


def _fake(monkeypatch, migrations):
    monkeypatch.setattr(migrate, "discover", lambda: migrations)


def test_applies_in_order_once(monkeypatch, empty_db):
    # Deliberately unsorted: 0002 depends on 0001, so wrong order fails.
    _fake(monkeypatch, [
        Migration("0002_b", "create table b (id int references a(id));"),
        Migration("0001_a", "create table a (id int primary key);"),
    ])
    assert apply_all(empty_db) == ["0001_a", "0002_b"]
    assert apply_all(empty_db) == []  # idempotent
    with psycopg.connect(empty_db) as c:
        assert [r[0] for r in c.execute("select version from schema_migrations order by version")] == [
            "0001_a", "0002_b"]


def test_failed_migration_rolls_back_and_is_not_recorded(monkeypatch, empty_db):
    _fake(monkeypatch, [Migration("0001_bad", "create table x (id int); select * from nope;")])
    with pytest.raises(psycopg.errors.UndefinedTable):
        apply_all(empty_db)
    with psycopg.connect(empty_db) as c:
        assert c.execute("select count(*) from schema_migrations").fetchone()[0] == 0
        assert c.execute("select to_regclass('x')").fetchone()[0] is None


def test_edited_applied_migration_is_refused(monkeypatch, empty_db):
    _fake(monkeypatch, [Migration("0001_a", "create table a (id int);")])
    apply_all(empty_db)
    _fake(monkeypatch, [Migration("0001_a", "create table a (id bigint);")])
    with pytest.raises(MigrationDrift):
        apply_all(empty_db)


def test_real_migrations_discovered_in_order():
    versions = [m.version for m in migrate.discover()]
    assert versions == sorted(versions)

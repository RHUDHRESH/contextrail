"""Schema-level guarantees. These hold even if Python code has a bug."""

import uuid

import psycopg
import pytest

H = "a" * 64  # a valid-looking sha256 hex


def _run(c, source="slack"):
    rid = uuid.uuid4()
    c.execute("insert into runs (id, source, request_text) values (%s, %s, %s)", (rid, source, "same as Rahul"))
    return rid


def _action(c, rid, aid="A1", verdict="ALLOW", state="planned", approver=None, idem=None):
    c.execute(
        """insert into actions (id, run_id, kind, target, params_hash, verdict, rule_id, clause, approver, state,
                                idempotency_key)
           values (%s, %s, 'grant', '{"system":"github"}', %s, %s, 'POL-X', 'clause text', %s, %s, %s)""",
        (aid, rid, H, verdict, approver, state, idem),
    )


# --- 0001_core ---------------------------------------------------------------------------------------------

def test_refuse_can_never_move_forward(migrated_db):
    with psycopg.connect(migrated_db) as c:
        rid = _run(c)
        _action(c, rid, verdict="REFUSE")
        c.execute("update actions set state = 'refused' where run_id = %s", (rid,))
        for forbidden in ("approved", "executed", "verified", "awaiting"):
            with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
                c.execute("update actions set state = %s, verified_at = now() where run_id = %s", (forbidden, rid))


def test_hold_must_name_an_approver(migrated_db):
    with psycopg.connect(migrated_db) as c:
        rid = _run(c)
        with pytest.raises(psycopg.errors.CheckViolation):
            _action(c, rid, verdict="HOLD", approver=None)


def test_verified_requires_read_back_timestamp(migrated_db):
    with psycopg.connect(migrated_db) as c:
        rid = _run(c)
        _action(c, rid)
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("update actions set state = 'verified' where run_id = %s", (rid,))


def test_idempotency_key_is_unique(migrated_db):
    with psycopg.connect(migrated_db) as c:
        rid = _run(c)
        _action(c, rid, aid="A1", idem="k1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _action(c, rid, aid="A2", idem="k1")


def test_first_decision_wins_across_doors(migrated_db):
    with psycopg.connect(migrated_db) as c:
        rid = _run(c)
        _action(c, rid, verdict="HOLD", approver="security-oncall")
        c.execute("""insert into approvals (run_id, action_id, params_hash, approver, decision, channel)
                     values (%s, 'A1', %s, 'p-anil', 'approved', 'email')""", (rid, H))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute("""insert into approvals (run_id, action_id, params_hash, approver, decision, channel)
                         values (%s, 'A1', %s, 'p-anil', 'refused', 'teams')""", (rid, H))


def test_unknown_source_and_status_rejected(migrated_db):
    with psycopg.connect(migrated_db) as c:
        with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
            _run(c, source="whatsapp")
        rid = _run(c)
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("update runs set status = 'approved' where id = %s", (rid,))

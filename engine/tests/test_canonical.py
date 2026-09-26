import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contextrail.canonical import (
    NotCanonicalizable,
    canonical_json,
    door_send_key,
    idempotency_key,
    params_hash,
    sha256_hex,
)
from contextrail.models import Action, ActionState


def test_key_order_and_whitespace_do_not_matter():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == '{"a":[1,{"c":3,"d":2}],"b":1}'
    assert sha256_hex({"x": 1, "y": 2}) == sha256_hex({"y": 2, "x": 1})


def test_datetimes_normalise_to_utc_z_and_naive_is_refused():
    ist = timezone(timedelta(hours=5, minutes=30))
    a = datetime(2026, 9, 26, 15, 30, tzinfo=ist)
    b = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    assert canonical_json(a) == canonical_json(b) == '"2026-09-26T10:00:00.000000Z"'
    with pytest.raises(NotCanonicalizable):
        canonical_json(datetime(2026, 9, 26))  # noqa: DTZ001 -- naive on purpose


def test_scalars():
    rid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert canonical_json({"id": rid, "d": date(2026, 9, 1), "amt": Decimal("10.500"), "s": {"b", "a"}}) == (
        '{"amt":"10.5","d":"2026-09-01","id":"12345678-1234-5678-1234-567812345678","s":["a","b"]}')
    assert canonical_json("प्रिया") == '"प्रिया"'  # UTF-8, not \u escapes
    for bad in (float("nan"), float("inf"), Decimal("NaN"), {1: "x"}, object()):
        with pytest.raises(NotCanonicalizable):
            canonical_json(bad)


def test_params_hash_changes_with_kind_or_any_target_field():
    base = params_hash("grant", {"system": "github", "repo": "northbeam/perception-sdk", "permission": "read"})
    assert base == params_hash("grant", {"permission": "read", "repo": "northbeam/perception-sdk", "system": "github"})
    assert base != params_hash("grant", {"system": "github", "repo": "northbeam/perception-sdk", "permission": "write"})
    assert base != params_hash("revoke", {"system": "github", "repo": "northbeam/perception-sdk", "permission": "read"})


def test_action_hash_must_match_its_target():
    a = Action.create("A1", "grant", {"system": "github", "permission": "read"})
    assert a.params_hash == params_hash("grant", {"system": "github", "permission": "read"})
    with pytest.raises(ValidationError, match="does not match"):
        Action(id="A1", kind="grant", target={"permission": "write"}, params_hash=a.params_hash)
    with pytest.raises(ValidationError, match="frozen"):
        a.target = {"system": "github", "permission": "admin"}  # silent escalation after hashing is refused
    assert a.target == {"system": "github", "permission": "read"}  # and the object was NOT mutated
    assert a.state is ActionState.PLANNED


# --- idempotency keys (T051) -------------------------------------------------------------------------------

def test_idempotency_key_is_stable_and_bound_to_params():
    rid = uuid.UUID(int=7)
    a = Action.create("A1", "grant", {"system": "github", "perm": "read"})
    k = idempotency_key(rid, a.id, a.params_hash)
    assert k == idempotency_key(uuid.UUID(int=7), "A1", a.params_hash)  # replay -> same key -> one write
    changed = Action.create("A1", "grant", {"system": "github", "perm": "write"})
    assert idempotency_key(rid, "A1", changed.params_hash) != k       # different params -> different action
    assert idempotency_key(uuid.UUID(int=8), "A1", a.params_hash) != k
    assert len(k) == 64


def test_keys_cannot_collide_by_concatenation():
    assert idempotency_key("ab", "c", "h") != idempotency_key("a", "bc", "h")


def test_door_send_key_differs_per_channel():
    rid = uuid.UUID(int=7)
    assert door_send_key(rid, "A1", "email") != door_send_key(rid, "A1", "slack")
    assert door_send_key(rid, "A1", "email") == door_send_key(rid, "A1", "email")

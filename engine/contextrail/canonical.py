"""Canonical JSON and hashing (checklist T048).

Everything that is hashed (capsule digests, params hashes, audit rows, idempotency keys) goes through
`canonical_json`, so the same value always produces the same bytes on every machine, in every door:
sorted keys, no whitespace, UTF-8, timezone-aware datetimes normalised to UTC with microseconds and a `Z`,
UUIDs and Decimals as strings, sets sorted, NaN/Infinity refused.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotCanonicalizable(TypeError):
    pass


def _normalise(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise NotCanonicalizable(f"dict keys must be str, got {type(k).__name__}")
            out[k] = _normalise(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalise(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise NotCanonicalizable("naive datetime; use timezone-aware (UTC) datetimes")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise NotCanonicalizable("non-finite Decimal")
        return format(value.normalize(), "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NotCanonicalizable("NaN/Infinity cannot be hashed canonically")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise NotCanonicalizable(f"cannot canonicalise {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def params_hash(kind: str, target: dict) -> str:
    """What an approval is bound to: the action kind and its exact target. Change either and the hash changes."""
    return sha256_hex({"kind": kind, "target": target})

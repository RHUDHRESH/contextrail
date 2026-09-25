"""Rule selection: which rules concern this subject and this action (checklist T055, T056).

A missing value never matches. A rule about contractors does not apply to a subject whose employment type is
unknown; an unknown subject is a Discover failure (needs_input), not something policy should guess about.
"""

from __future__ import annotations

from typing import Any

from contextrail.models import Subject
from contextrail.policy.schema import Rule


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _Missing()


def resolve(obj: Any, dotted: str) -> Any:
    """Walk a dotted path through dicts, lists (numeric parts) and objects. Returns MISSING if any step is absent."""
    cur = obj
    for part in dotted.split("."):
        if cur is None or cur is MISSING:
            return MISSING
        if isinstance(cur, dict):
            cur = cur.get(part, MISSING)
        elif isinstance(cur, (list, tuple)) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else MISSING
        else:
            cur = getattr(cur, part, MISSING)
    return cur


def applies_to(rule: Rule, subject: Subject) -> bool:
    """True when every applies_to field of the rule holds for the subject record (Subject fields only)."""
    for field, allowed in rule.applies_to.items():
        value = getattr(subject, field)
        if value is None:
            return False
        if isinstance(value, list):
            if not set(value) & set(allowed):
                return False
        elif value not in allowed:
            return False
    return True


def _value_matches(actual: Any, expected: Any) -> bool:
    if actual is MISSING or actual is None:
        return False
    allowed = expected if isinstance(expected, list) else [expected]
    if isinstance(actual, (list, tuple, set)):
        return bool(set(actual) & set(allowed))      # e.g. repo_tags overlapping ['production']
    return actual in allowed


def matches(rule: Rule, action: Any) -> bool:
    """True when the action's kind and every 'target.<path>' in rule.match hold.

    Scalar expected values mean equality, lists mean membership; list-valued targets match on overlap.
    A path the target does not have never matches.
    """
    for key, expected in rule.match.items():
        actual = action.kind if key == "kind" else resolve(action.target, key.removeprefix("target."))
        if not _value_matches(actual, expected):
            return False
    return True

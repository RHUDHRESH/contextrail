"""Safe condition evaluator (checklist T057). No `eval`, no `exec`, no attribute access beyond dotted paths.

An expression is `<path> <op> <value-or-path>`:
    target.repo in subject.sow_repos
    target.permission == 'read'
    target.repo_tags contains 'production'
    target.seat_cost_usd > 0
Literals on the right are parsed with `yaml.safe_load` ('read', 3, [a, b], true). Blocks `{any: [...]}` and
`{all: [...]}` nest.

Unknown is false: a MISSING or mistyped operand makes the comparison False (both `==` and `!=`). Conditions
gate a rule's verdict, and else_verdict is REFUSE wherever it matters, so "we don't know" can never become ALLOW.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import yaml

from contextrail.policy.matchers import MISSING, resolve
from contextrail.policy.schema import CONDITION_RE, _right_is_path

_NUMBER = (int, float, Decimal)


def _operand(ctx: dict, right: str) -> Any:
    if _right_is_path(right):
        return resolve(ctx, right)
    try:
        return yaml.safe_load(right)
    except yaml.YAMLError:
        return MISSING


def _is_number(v: Any) -> bool:
    return isinstance(v, _NUMBER) and not isinstance(v, bool)


def _compare(left: Any, op: str, right: Any) -> bool:
    if left is MISSING or right is MISSING or left is None or right is None:
        return False
    if op in ("in", "not in"):
        if not isinstance(right, (list, tuple, set, str)):
            return False
        inside = left in right
        return inside if op == "in" else not inside
    if op in ("contains", "not contains"):
        if not isinstance(left, (list, tuple, set, str)):
            return False
        has = right in left
        return has if op == "contains" else not has
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if not (_is_number(left) and _is_number(right)):
        return False
    return {">": left > right, "<": left < right, ">=": left >= right, "<=": left <= right}[op]


def evaluate(expr: Any, ctx: dict) -> bool:
    if isinstance(expr, dict):
        (kind, items), = expr.items()
        results = (evaluate(i, ctx) for i in items)
        return any(results) if kind == "any" else all(results)
    m = CONDITION_RE.match(expr)
    if not m:  # the schema rejects these at load time; never guess at runtime
        return False
    return _compare(resolve(ctx, m["left"]), m["op"], _operand(ctx, m["right"]))


def evaluate_all(conditions: list[Any], ctx: dict) -> bool:
    return all(evaluate(c, ctx) for c in conditions)

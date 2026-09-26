"""Rule loader (checklist T054).

Loads `policy/rules/*.yaml` with `yaml.safe_load` (no tags, no object construction), validates every file against
the Rule schema, and reports *all* problems at once. The engine refuses to start with an invalid or duplicate
rule: running with a silently skipped rule would change verdicts without anyone noticing.

Each file holds one rule and is named after it: POL-CTR-001 lives in `pol-ctr-001.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from contextrail.policy.schema import Rule

RULES_DIR = Path(__file__).parent / "rules"


class RuleLoadError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid policy rules:\n  - " + "\n  - ".join(problems))
        self.problems = problems


def load_rules(directory: Path | str = RULES_DIR) -> list[Rule]:
    directory = Path(directory)
    problems: list[str] = []
    rules: dict[str, Rule] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            problems.append(f"{path.name}: YAML error: {e}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: expected one rule (a mapping), got {type(data).__name__}")
            continue
        try:
            rule = Rule.model_validate(data)
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "rule"
                problems.append(f"{path.name}: {loc}: {err['msg']}")
            continue
        if path.stem != rule.id.lower():
            problems.append(f"{path.name}: file must be named {rule.id.lower()}.yaml")
        if rule.id in rules:
            problems.append(f"{path.name}: duplicate rule id {rule.id}")
            continue
        rules[rule.id] = rule
    if problems:
        raise RuleLoadError(problems)
    return [rules[k] for k in sorted(rules)]

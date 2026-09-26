"""Connector registry and the honest status report behind GET /v1/connectors (checklist T081).

A connector or door appears with a `mode` only once it exists in code. Planned ones are listed with the task that
will build them and whether their credentials are configured, never with a mode they do not have (D-004).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from contextrail.connectors.base import Connector
from contextrail.connectors.fixture import FixtureEntitlements, FixtureGitHub, FixtureHRIS, FixtureSlackCorpus
from contextrail.connectors.state import FixtureState
from contextrail.settings import Settings

# name -> (kind, building task, settings flag that says credentials exist)
PLANNED: dict[str, tuple[str, str, str | None]] = {
    "freshservice": ("base", "T122", "freshservice_configured"),
    "slack": ("door", "T139", "slack_configured"),
    "email": ("door", "T230", "ses_configured"),
    "teams": ("door", "T241", "teams_configured"),
    "voice": ("door", "T194", None),
    "llm_router": ("model", "T109", None),
}


@dataclass
class Registry:
    connectors: dict[str, Connector] = field(default_factory=dict)

    def get(self, name: str) -> Connector:
        return self.connectors[name]

    def describe(self, settings: Settings) -> dict[str, list[dict]]:
        built = [{"name": c.name, "kind": "connector", "mode": c.mode, "status": "built"}
                 for c in self.connectors.values()]
        planned = []
        for name, (kind, task, flag) in PLANNED.items():
            if name in self.connectors:
                continue
            planned.append({"name": name, "kind": kind, "mode": None, "status": f"planned ({task})",
                            "credentials_configured": bool(getattr(settings, flag)) if flag else None})
        return {"connectors": built, "planned": planned}


def build_registry(state_directory: Path | None = None) -> Registry:
    def st(name: str) -> FixtureState:
        return FixtureState(name, directory=state_directory)

    return Registry({
        "hris": FixtureHRIS(st("hris")),
        "entitlements": FixtureEntitlements(st("entitlements")),
        "github": FixtureGitHub(st("github")),
        "slack_corpus": FixtureSlackCorpus(st("slack_corpus")),
    })

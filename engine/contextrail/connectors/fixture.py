"""FIXTURE connectors (checklist T079): real state on disk, real read-back, honest labels.

- FixtureEntitlements: access grants/revocations for non-GitHub systems (Okta, Slack, Jira, AWS, ...).
- FixtureGitHub: repository collaborator permissions.
- FixtureHRIS: read-only people records; exact lookups only (P1: relevance is not identity).
- FixtureSlackCorpus: read-only message search; results are untrusted evidence (P6).

Writes honour idempotency keys: the second write with the same key changes nothing and says `replayed=True`.
Faults can be injected per target key to exercise P3 ("a 200 is not done") and unknown-outcome reconciliation.
"""

from __future__ import annotations

from typing import Any

from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome, WriteResult
from contextrail.connectors.state import FixtureState
from contextrail.models import Action


async def _apply(state: FixtureState, fault_key: str, idem_key: str, ref: dict, apply_fn) -> WriteResult:
    def fn(doc: dict) -> tuple[str, dict]:
        if idem_key in doc["_ledger"]:
            return "replay", doc["_ledger"][idem_key]
        fault = doc["_faults"].pop(fault_key, None)
        if fault == "transient_once":
            return "transient", ref
        if fault == "timeout_before_apply":
            return "timeout", ref
        if fault != "ack_without_apply":  # the lying system: acknowledges, changes nothing
            apply_fn(doc)
        doc["_ledger"][idem_key] = ref
        return ("timeout" if fault == "timeout_after_apply" else "ok"), ref

    outcome, result_ref = await state.mutate(fn)
    if outcome == "transient":
        raise TransientError(f"{state.name}: 503 injected for {fault_key}")
    if outcome == "timeout":
        raise UnknownOutcome(f"{state.name}: timed out writing {fault_key}; outcome unknown")
    return WriteResult(ok=True, replayed=outcome == "replay", ref=result_ref, mode="FIXTURE")


def _need(target: dict, *keys: str) -> list[Any]:
    missing = [k for k in keys if not target.get(k)]
    if missing:
        raise ConnectorError(f"target missing {missing}")
    return [target[k] for k in keys]


class FixtureEntitlements:
    name = "entitlements"
    mode = "FIXTURE"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or FixtureState("entitlements")

    async def read(self, ref: dict) -> dict:
        doc = self.state.load()
        if "subject_id" in ref:
            return {"subject_id": ref["subject_id"], "holdings": list(doc["holdings"].get(ref["subject_id"], []))}
        if "entitlement" in ref:
            return dict(doc["catalog"][ref["entitlement"]])
        return {"catalog": doc["catalog"]}

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        subject_id, ent = _need(action.target, "subject_id", "entitlement")
        if action.kind not in ("grant", "revoke"):
            raise ConnectorError(f"unsupported kind {action.kind}")

        def apply(doc: dict) -> None:
            if ent not in doc["catalog"]:
                raise ConnectorError(f"unknown entitlement {ent}")
            held = doc["holdings"].setdefault(subject_id, [])
            if action.kind == "grant" and ent not in held:
                held.append(ent)
            elif action.kind == "revoke" and ent in held:
                held.remove(ent)

        return await _apply(self.state, ent, idem_key, {"subject_id": subject_id, "entitlement": ent}, apply)

    async def verify(self, action: Action) -> tuple[bool, dict]:
        subject_id, ent = _need(action.target, "subject_id", "entitlement")
        held = self.state.load()["holdings"].get(subject_id, [])
        present = ent in held
        ok = present if action.kind == "grant" else not present
        return ok, {"subject_id": subject_id, "entitlement": ent, "present": present}


class FixtureGitHub:
    name = "github"
    mode = "FIXTURE"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or FixtureState("github")

    def _login(self, doc: dict, subject_id: str) -> str:
        login = doc["logins"].get(subject_id)
        if not login:
            raise ConnectorError(f"no GitHub login mapped for {subject_id}")
        return login

    async def read(self, ref: dict) -> dict:
        doc = self.state.load()
        repo = doc["repos"].get(ref.get("repo", ""))
        if repo is None:
            raise ConnectorError(f"unknown repo {ref.get('repo')}")
        return {"repo": ref["repo"], "tags": repo["tags"], "collaborators": dict(repo["collaborators"])}

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        subject_id, repo, permission = _need(action.target, "subject_id", "repo", "permission")
        doc = self.state.load()
        login = self._login(doc, subject_id)
        if repo not in doc["repos"]:
            raise ConnectorError(f"unknown repo {repo}")

        def apply(d: dict) -> None:
            collaborators = d["repos"][repo]["collaborators"]
            if action.kind == "grant":
                collaborators[login] = permission
            elif action.kind == "revoke":
                collaborators.pop(login, None)
            else:
                raise ConnectorError(f"unsupported kind {action.kind}")

        return await _apply(self.state, f"{repo}:{login}", idem_key, {"repo": repo, "login": login}, apply)

    async def verify(self, action: Action) -> tuple[bool, dict]:
        subject_id, repo, permission = _need(action.target, "subject_id", "repo", "permission")
        doc = self.state.load()
        login = self._login(doc, subject_id)
        actual = doc["repos"][repo]["collaborators"].get(login)
        ok = actual == permission if action.kind == "grant" else actual is None
        return ok, {"repo": repo, "login": login, "permission": actual}


class FixtureHRIS:
    """Read-only. Lookups are exact: by ID, or by exact full/first name returning every match (never a best guess)."""

    name = "hris"
    mode = "FIXTURE"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or FixtureState("hris")

    async def read(self, ref: dict) -> dict:
        for p in self.state.load()["people"]:
            if p["source_id"] == ref.get("source_id"):
                return dict(p)
        raise ConnectorError(f"no HRIS record {ref.get('source_id')}")

    async def find_by_name(self, name: str) -> list[dict]:
        want = " ".join(name.split()).casefold()
        people = self.state.load()["people"]
        full = [p for p in people if p["display_name"].casefold() == want]
        if full:
            return [dict(p) for p in full]
        return [dict(p) for p in people if p["display_name"].split()[0].casefold() == want]

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        raise ConnectorError("HRIS connector is read-only")

    async def verify(self, action: Action) -> tuple[bool, dict]:
        raise ConnectorError("HRIS connector is read-only")


class FixtureSlackCorpus:
    """Read-only retrieval over the Slack corpus. Everything it returns is untrusted evidence."""

    name = "slack_corpus"
    mode = "FIXTURE"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or FixtureState("slack_corpus")

    async def read(self, ref: dict) -> dict:
        for m in self.state.load()["messages"]:
            if m["id"] == ref.get("id"):
                return dict(m)
        raise ConnectorError(f"no message {ref.get('id')}")

    async def search(self, terms: list[str], limit: int = 5) -> list[dict]:
        wanted = [t.casefold() for t in terms if t]
        hits = []
        for m in self.state.load()["messages"]:
            hay = " ".join([m["text"], *m["tags"]]).casefold()
            score = sum(1 for t in wanted if t in hay)
            if score:
                hits.append((score, m["posted_at"], m))
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
        return [dict(h[2]) for h in hits[:limit]]

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        raise ConnectorError("Slack corpus connector is read-only")

    async def verify(self, action: Action) -> tuple[bool, dict]:
        raise ConnectorError("Slack corpus connector is read-only")

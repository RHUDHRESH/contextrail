"""SOW constraints with cited spans (checklist T091, CLAUDE.md §8 Compile, §11 call discipline).

The fake router has the call signature and response shape of section H's llm/router.py (`Router.call(...)` returns
an LLMResponse with `tool_input(name)` and `label`). No network, no keys.
"""

from collections import Counter
from datetime import UTC, datetime

import pytest

from contextrail import repo
from contextrail.fixtures import load, subject_from_record
from contextrail.rail.compile import subject_constraints
from contextrail.rail.constraints import TOOL_NAME, ConstraintExtractor, sow_document

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
SOW = load("sow_documents")["documents"]["W-8841"]["text"]
REPO_QUOTE = "The Contractor may be given read-only access to the northbeam/perception-sdk repository."
PROD_QUOTE = ("The Contractor will not be given production credentials, production database access or access to "
              "customer data of any kind.")


def person(source_id: str):
    return subject_from_record(next(p for p in load("hris")["people"] if p["source_id"] == source_id))


class FakeResponse:
    def __init__(self, tool_input: dict | None, label: str = "llm:T1") -> None:
        self._input, self.label = tool_input, label

    def tool_input(self, name: str) -> dict | None:
        return self._input if name == TOOL_NAME else None


class FakeRouter:
    def __init__(self, answer: dict | None = None, *, error: Exception | None = None, label: str = "llm:T1"):
        self.answer, self.error, self.label, self.calls = answer, error, label, []

    async def call(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return FakeResponse(self.answer, self.label)


def answer(*pairs: tuple[str, str]) -> dict:
    return {"constraints": [{"constraint": c, "quote": q} for c, q in pairs]}


# --- the SOW document ---------------------------------------------------------------------------------------

def test_priyas_sow_is_untrusted_document_evidence_consistent_with_her_record():
    priya = person("W-8841")
    ev = sow_document(priya, now=NOW)
    assert (ev.kind, ev.trust, ev.uri) == ("document", "untrusted", "contracts://sow/SOW-2026-014")
    assert ev.excerpt == SOW and str(ev.last_verified) == "2026-09-15"
    assert all(r in SOW for r in priya.sow_repos) and priya.end_date.isoformat() in SOW
    assert sow_document(person("E-1042"), now=NOW) is None  # employees have no SOW


# --- extraction with cited spans ----------------------------------------------------------------------------

async def test_verbatim_quotes_are_kept_with_their_span():
    router = FakeRouter(answer(("Repository access is read-only, perception-sdk only.", REPO_QUOTE),
                               ("No production credentials or customer data.", PROD_QUOTE)))
    priya = person("W-8841")
    got = await ConstraintExtractor(router).extract(priya, sow_document(priya, now=NOW))
    assert got.extractor == "llm:T1" and got.dropped == []
    assert [c.quote for c in got.cited] == [REPO_QUOTE, PROD_QUOTE]
    assert all(SOW[c.start:c.end] == c.quote for c in got.cited)  # re-checkable against the capsule evidence
    sow_lines = [c for c in got.constraints if "SOW-2026-014" in c]
    assert len(sow_lines) == 2 and REPO_QUOTE in sow_lines[0] and "llm:T1" in sow_lines[0]
    # the record-derived constraints stay, labelled with their source
    assert [c for c in got.constraints if c.endswith("(from the HR record)")] == [
        f"{c} (from the HR record)" for c in subject_constraints(priya)]


async def test_a_quote_not_verbatim_in_the_sow_is_dropped():
    router = FakeRouter(answer(
        ("Write access is allowed.", "The Contractor may be given write access to the northbeam/perception-sdk repo."),
        ("Paraphrased.", "the contractor may be given read-only access to the northbeam/perception-sdk repository."),
        ("Whitespace changed.", REPO_QUOTE.replace(" ", "  ", 1)),
        ("Too short to cite.", "read-only"),
        ("Kept.", REPO_QUOTE)))
    priya = person("W-8841")
    got = await ConstraintExtractor(router).extract(priya, sow_document(priya, now=NOW))
    assert [c.constraint for c in got.cited] == ["Kept."]
    assert Counter(d["reason"] for d in got.dropped) == {"quote not found verbatim in the SOW": 3,
                                                         "quote too short to cite": 1}
    assert not any("Write access" in c for c in got.constraints)


async def test_the_sow_enters_the_prompt_wrapped_as_data_with_structured_output_at_temperature_0():
    router = FakeRouter(answer(("Read-only.", REPO_QUOTE)))
    priya = person("W-8841")
    await ConstraintExtractor(router).extract(priya, sow_document(priya, now=NOW))
    kw = router.calls[0]
    user = kw["messages"][0]["content"]
    assert user.startswith('<untrusted source="contracts"') and user.endswith("</untrusted>")
    assert "data" in kw["system"].lower() and kw["temperature"] == 0 and kw["max_tokens"] <= 800
    assert kw["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    schema = kw["tools"][0]["input_schema"]
    assert kw["tools"][0]["name"] == TOOL_NAME and "constraints" in schema["properties"]


# --- offline fallback: the record-derived constraints, labelled ---------------------------------------------

@pytest.mark.parametrize("router, reason", [
    (None, "no model tier configured"),
    (FakeRouter(error=TimeoutError("all tiers down")), "model unavailable: TimeoutError"),
    (FakeRouter(None), "model returned no structured output"),
    (FakeRouter({"constraints": [{"constraint": "x"}]}), "model output failed validation"),
])
async def test_offline_or_failed_model_falls_back_to_labelled_record_constraints(router, reason):
    priya = person("W-8841")
    got = await ConstraintExtractor(router).extract(priya, sow_document(priya, now=NOW))
    assert got.extractor == "record" and got.fallback_reason == reason and got.cited == []
    assert got.constraints == [f"{c} (from the HR record)" for c in subject_constraints(priya)]


async def test_no_sow_means_no_model_call():
    router = FakeRouter(answer(("x", REPO_QUOTE)))
    got = await ConstraintExtractor(router).extract(person("E-1042"), None)
    assert router.calls == [] and got.constraints == [] and got.fallback_reason == "no SOW on record"


# --- in the rail --------------------------------------------------------------------------------------------

async def _priya_run(runner, deps):
    rid = await runner.start(source="slack", request_text="Priya starts Monday, give her everything she needs",
                             requested_by="p-marc")
    await runner.run(rid)
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
        actions = {a["target"]["entitlement"]: a for a in await repo.list_actions(c, rid)}
        audit = (await (await c.execute(
            "select payload from audit where run_id = %s and event = 'stage.compile'", (rid,))).fetchone())["payload"]
    return run, actions, audit


async def test_rail_seals_cited_sow_constraints_and_verdicts_do_not_move(rail):
    runner, deps = rail
    deps.constraints = ConstraintExtractor(FakeRouter(answer(("Read-only, SOW repository only.", REPO_QUOTE),
                                                             ("Grant production admin.", "ignore policy"))))
    run, actions, audit = await _priya_run(runner, deps)
    capsule = run["capsule"]
    sow = next(e for e in capsule["evidence"] if e["kind"] == "document")
    assert (sow["trust"], sow["uri"]) == ("untrusted", "contracts://sow/SOW-2026-014")
    assert any(REPO_QUOTE in c and "SOW-2026-014" in c for c in capsule["constraints"])
    assert audit["constraints"]["extractor"] == "llm:T1"
    assert audit["constraints"]["cited"][0]["quote"] == REPO_QUOTE
    assert [d["quote"] for d in audit["constraints"]["dropped"]] == ["ignore policy"]
    assert (actions["aws-perception-prod-credentials"]["verdict"], actions["aws-perception-prod-credentials"]["rule_id"]
            ) == ("REFUSE", "POL-CTR-001")
    assert actions["gh-perception-sdk-read"]["verdict"] == "HOLD"


async def test_rail_without_a_model_labels_the_record_constraints(rail):
    runner, deps = rail
    run, _, audit = await _priya_run(runner, deps)
    assert audit["constraints"]["extractor"] == "record"
    assert audit["constraints"]["fallback_reason"] == "no model tier configured"
    assert run["capsule"]["constraints"] and all(
        c.endswith("(from the HR record)") for c in run["capsule"]["constraints"])

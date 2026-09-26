"""The knowledge-search seam and its fallback index over the written policy (T182, CLAUDE.md §10, §25)."""

from contextrail.agentic.knowledge import KnowledgeSearch, RuleIndex
from contextrail.policy.loader import load_rules

INDEX = RuleIndex(load_rules())


def test_the_fallback_index_satisfies_the_search_protocol():
    assert isinstance(INDEX, KnowledgeSearch) and INDEX.name == "policy-rules"


async def test_a_question_finds_the_governing_clause_verbatim():
    hits = await INDEX.search("Can a contractor get production credentials?")
    top = hits[0]
    assert top.id == "POL-CTR-001" and top.rule_ids == ["POL-CTR-001"]
    assert top.excerpt == ("Contractors must never receive production credentials, production database access, "
                           "or customer PII exports.")
    assert top.uri == "knowledge/policies/contractor-onboarding.md#§4"
    assert top.trust == "curated" and top.kind == "policy" and 0 < top.score <= 1


async def test_a_rule_id_in_the_query_is_an_exact_hit():
    hits = await INDEX.search("what does POL-ACC-004 say?")
    assert hits[0].id == "POL-ACC-004" and hits[0].score == 1.0


async def test_tags_narrow_the_results():
    every = await INDEX.search("approval", limit=20)
    narrowed = await INDEX.search("approval", tags=["repository"], limit=20)
    assert narrowed and {h.id for h in narrowed} < {h.id for h in every}
    assert all("repositor" in (h.title + h.excerpt).lower() for h in narrowed)


async def test_nothing_relevant_returns_nothing_rather_than_a_guess():
    assert await INDEX.search("quarterly lunch menu") == []


async def test_limit_is_respected():
    assert len(await INDEX.search("access approval security", limit=2)) == 2

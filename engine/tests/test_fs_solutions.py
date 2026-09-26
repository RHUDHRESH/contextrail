"""Freshservice Solutions articles as the policy source for knowledge ingest (T129, CLAUDE.md §10 ingest).

api.freshservice.com, Solution Article: GET /api/v2/solutions/articles/{id} -> `article`
(`description` is HTML; `status` 1 draft, 2 published).
"""

import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError
from contextrail.connectors.freshservice import FreshserviceClient, FreshserviceConnector, article_status
from contextrail.connectors.state import FixtureState
from contextrail.policy.loader import load_rules

POLICY_ARTICLE = 50001234
ARTICLE = {"id": POLICY_ARTICLE, "title": "Contractor Onboarding Policy", "description": "<p>§4 ...</p>",
           "status": 2, "folder_id": 2, "category_id": 2, "updated_at": "2026-09-20T10:00:00Z"}


async def test_get_solution_article_by_id():
    tenant = FakeTenant({("GET", f"/api/v2/solutions/articles/{POLICY_ARTICLE}"): ok({"article": ARTICLE})})
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport) as fs:
        got = await fs.get_solution_article(POLICY_ARTICLE)
    assert got == ARTICLE and tenant.requests[0].method == "GET"


@pytest.mark.parametrize(("status", "name"), [(1, "draft"), (2, "published"), (9, "unknown")])
def test_article_status_follows_the_documented_values(status, name):
    assert article_status({"status": status}) == name


async def test_an_article_response_without_its_envelope_is_an_error():
    tenant = FakeTenant({("GET", "/api/v2/solutions/articles/7"): ok({"articles": []})})
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport) as fs:
        with pytest.raises(ConnectorError, match="article"):
            await fs.get_solution_article(7)


async def test_the_fixture_policy_article_quotes_the_rule_clause_verbatim(tmp_path):
    conn = FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))
    got = await conn.get_solution_article(POLICY_ARTICLE)
    assert got.mode == "FIXTURE" and article_status(got.data) == "published"
    assert got.data["title"] == "Contractor Onboarding Policy"
    clause = next(r for r in load_rules() if r.id == "POL-CTR-001").clause_text
    assert clause in got.data["description"]  # the policy source and the rule cannot drift apart silently


async def test_an_unknown_fixture_article_is_a_404(tmp_path):
    conn = FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))
    with pytest.raises(ConnectorError) as e:
        await conn.get_solution_article(1)
    assert e.value.status == 404

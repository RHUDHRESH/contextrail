"""GET /v1/policy/studio (T072): Policy Studio over a stored run, behind the engine token. It reads, never writes."""

import uuid

import httpx
import psycopg
import pytest

from contextrail.app_state import build_platform
from contextrail.main import create_app
from contextrail.settings import Settings

TOKEN = "test-studio-token"  # a test value, not a credential
ANIL_REQUEST = "Give Anil the same access as Rahul Mehta"


def _app(runner, token=TOKEN, *, with_platform=True):
    settings = Settings(_env_file=None, engine_token=token)
    app = create_app(settings, platform=build_platform(settings, runner=runner))
    if not with_platform:
        app.state.platform = None
    return app


def _client(app, token=TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test", headers=headers)


async def _snapshot(deps, rid):
    async with deps.db.connection() as c:
        audit = (await (await c.execute("select count(*) as n from audit")).fetchone())["n"]
        actions = await (await c.execute(
            "select id, verdict, rule_id, state, expires_at from actions where run_id = %s order by id",
            (rid,))).fetchall()
        run = await (await c.execute("select status, capsule_digest, updated_at from runs where id = %s",
                                     (rid,))).fetchone()
    return audit, actions, run


async def test_studio_reports_the_blast_radius_of_a_stored_run_and_writes_nothing(rail):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text=ANIL_REQUEST, requested_by="p-anil")
    await runner.run(rid)
    before = await _snapshot(deps, rid)
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(rid), "hold_out": "POL-ACC-003"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["run_id"], body["hold_out"], body["simulation"]) == (str(rid), "POL-ACC-003", True)
    radius = body["blast_radius"]
    assert (radius["examined"], radius["unblocked"], radius["drift"]) == (18, 1, 0)
    assert radius["before"] == {"allow": 15, "hold": 2, "refuse": 1}
    admin = next(a for a in body["actions"] if a["label"] == "aws-payments-prod-admin")
    assert (admin["stored"]["verdict"], admin["after"]["verdict"], admin["change"]) == ("REFUSE", "ALLOW", "loosened")
    assert await _snapshot(deps, rid) == before  # no audit row, no action change, capsule untouched


@pytest.mark.parametrize("header", [None, "Bearer wrong-token", "Basic dXNlcjpwYXNz"])
async def test_the_studio_requires_the_engine_token(rail, header):
    runner, _ = rail
    async with _client(_app(runner), token=None) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(uuid.uuid4()), "hold_out": "POL-ACC-003"},
                             headers={"Authorization": header} if header else {})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("configured", ["", "change-me"])
async def test_an_unset_or_placeholder_token_closes_the_studio(rail, configured):
    runner, _ = rail
    async with _client(_app(runner, configured), token=configured) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(uuid.uuid4()), "hold_out": "POL-ACC-003"})
    assert r.status_code == 503 and "ENGINE_TOKEN" in r.json()["detail"]


async def test_without_the_engine_platform_the_studio_says_so(rail):
    runner, _ = rail
    async with _client(_app(runner, with_platform=False)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(uuid.uuid4()), "hold_out": "POL-ACC-003"})
    assert r.status_code == 503 and "database" in r.json()["detail"]


@pytest.mark.parametrize(("params", "status"), [
    ({"run_id": "not-a-uuid", "hold_out": "POL-ACC-003"}, 422),
    ({"run_id": str(uuid.UUID(int=1)), "hold_out": "ACC-3"}, 422),
    ({"hold_out": "POL-ACC-003"}, 422),
])
async def test_malformed_parameters_are_422(rail, params, status):
    runner, _ = rail
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params=params)
    assert r.status_code == status, r.text


async def test_an_unknown_run_is_404(rail):
    runner, _ = rail
    rid = uuid.UUID(int=1)
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(rid), "hold_out": "POL-ACC-003"})
    assert r.status_code == 404 and str(rid) in r.json()["detail"]  # the route's answer, not an unrouted path


async def test_an_unknown_rule_is_404(rail):
    runner, _ = rail
    rid = await runner.start(source="slack", request_text=ANIL_REQUEST, requested_by="p-anil")
    await runner.run(rid)
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(rid), "hold_out": "POL-XYZ-999"})
    assert r.status_code == 404 and "POL-XYZ-999" in r.json()["detail"]


async def test_a_run_without_a_sealed_case_file_is_409(rail):
    runner, _ = rail
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul", requested_by="p-anil")
    await runner.run(rid)  # two Rahuls: stops at needs_input before Compile seals anything
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(rid), "hold_out": "POL-ACC-003"})
    assert r.status_code == 409 and "sealed" in r.json()["detail"]


async def test_an_altered_capsule_is_refused_not_simulated(rail, migrated_db):
    runner, _ = rail
    rid = await runner.start(source="slack", request_text=ANIL_REQUEST, requested_by="p-anil")
    await runner.run(rid)
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("""update runs set capsule = jsonb_set(capsule, '{constraints}', '["forged"]') where id = %s""",
                  (rid,))
    async with _client(_app(runner)) as client:
        r = await client.get("/v1/policy/studio", params={"run_id": str(rid), "hold_out": "POL-ACC-003"})
    assert r.status_code == 409 and "digest" in r.json()["detail"]

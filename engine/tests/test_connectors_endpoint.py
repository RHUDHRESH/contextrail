from fastapi.testclient import TestClient

from contextrail.main import create_app
from contextrail.settings import Settings


def test_connectors_endpoint_is_honest_about_every_mode(monkeypatch):
    for k in ("FS_DOMAIN", "FS_API_KEY", "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "DODO_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    body = TestClient(create_app(Settings(_env_file=None))).get("/v1/connectors").json()
    built = {c["name"]: c for c in body["connectors"]}
    assert set(built) == {"hris", "entitlements", "github", "slack_corpus", "freshservice", "dodo"}
    assert all(c["mode"] == "FIXTURE" for c in built.values())  # nothing is configured, so nothing is LIVE
    assert built["dodo"]["environment"] == "fixture"   # never "test_mode" without a key (T206)
    planned = {p["name"]: p for p in body["planned"]}
    assert "freshservice" not in planned  # built (T122-T138), no longer planned
    assert all(p["mode"] is None for p in planned.values())  # nothing claims a mode before it exists
    assert {"slack", "email", "teams", "voice"} <= set(planned)


def test_freshservice_is_live_only_when_its_credentials_are_configured():
    s = Settings(_env_file=None, fs_domain="northbeam.freshservice.com", fs_api_key="x")
    body = TestClient(create_app(s)).get("/v1/connectors").json()
    modes = {c["name"]: c["mode"] for c in body["connectors"]}
    assert modes["freshservice"] == "LIVE"
    assert {m for n, m in modes.items() if n != "freshservice"} == {"FIXTURE"}  # nothing else became LIVE

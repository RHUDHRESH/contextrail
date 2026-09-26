from fastapi.testclient import TestClient

from contextrail.main import create_app
from contextrail.settings import Settings


def test_connectors_endpoint_is_honest_about_every_mode(monkeypatch):
    for k in ("FS_DOMAIN", "FS_API_KEY", "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"):
        monkeypatch.delenv(k, raising=False)
    body = TestClient(create_app(Settings(_env_file=None))).get("/v1/connectors").json()
    built = {c["name"]: c for c in body["connectors"]}
    assert set(built) == {"hris", "entitlements", "github", "slack_corpus", "dodo"}
    assert all(c["mode"] == "FIXTURE" for c in built.values())
    assert built["dodo"]["environment"] == "fixture"   # never "test_mode" without a key (T206)
    planned = {p["name"]: p for p in body["planned"]}
    assert planned["freshservice"] == {"name": "freshservice", "kind": "base", "mode": None,
                                       "status": "planned (T122)", "credentials_configured": False}
    assert all(p["mode"] is None for p in planned.values())  # nothing claims LIVE before it exists
    assert {"slack", "email", "teams", "voice"} <= set(planned)


def test_configured_credentials_are_reported_but_do_not_make_anything_live():
    s = Settings(_env_file=None, fs_domain="northbeam.freshservice.com", fs_api_key="x")
    body = TestClient(create_app(s)).get("/v1/connectors").json()
    fs = next(p for p in body["planned"] if p["name"] == "freshservice")
    assert fs["credentials_configured"] is True and fs["mode"] is None

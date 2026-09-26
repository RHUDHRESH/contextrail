"""CORS: browsers on the configured origins (the FDK app, the glass box) may call the API; nobody else, by default."""

import pytest
from fastapi.testclient import TestClient

from contextrail.main import create_app
from contextrail.settings import Settings

FDK = "https://northbeam.freshservice.com"
PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}


def client(origins: list[str]) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, cors_allowed_origins=origins)))


def test_no_origins_configured_means_no_cross_origin_access():
    r = client([]).get("/health", headers={"Origin": FDK})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_the_configured_origin_passes_preflight_with_the_bearer_header():
    r = client([FDK]).options("/v1/runs", headers={"Origin": FDK, **PREFLIGHT})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == FDK
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "POST" in r.headers["access-control-allow-methods"]


def test_other_origins_are_not_allowed():
    c = client([FDK])
    pre = c.options("/v1/runs", headers={"Origin": "https://evil.example", **PREFLIGHT})
    assert pre.status_code == 400 and "access-control-allow-origin" not in pre.headers
    simple = c.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_even_an_error_answer_carries_the_header_for_an_allowed_origin():
    r = client([FDK]).get("/v1/runs/00000000-0000-0000-0000-000000000000", headers={"Origin": FDK})
    assert r.status_code in (401, 503) and r.headers["access-control-allow-origin"] == FDK


def test_a_wildcard_origin_is_refused_at_startup():
    with pytest.raises(ValueError, match="explicit"):
        client(["*"])

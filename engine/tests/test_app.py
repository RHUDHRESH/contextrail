from fastapi.testclient import TestClient

from contextrail.main import create_app
from contextrail.settings import Settings


def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def test_health():
    r = client().get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_v1_is_mounted():
    r = client().get("/v1")
    assert r.status_code == 200
    assert r.json()["api"] == "v1"

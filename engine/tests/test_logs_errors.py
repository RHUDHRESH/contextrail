import json

from fastapi import APIRouter
from fastapi.testclient import TestClient

from contextrail.logs import _mask, bind_run, clear_context, configure_logging, get_logger
from contextrail.main import create_app
from contextrail.settings import Settings


def _app():
    app = create_app(Settings(_env_file=None))
    boom = APIRouter()

    @boom.get("/boom")
    async def _boom():
        raise RuntimeError("secret internal detail")

    app.include_router(boom)
    return app


def test_request_id_generated_and_echoed():
    c = TestClient(_app())
    r = c.get("/health")
    assert len(r.headers["x-request-id"]) == 32
    r2 = c.get("/health", headers={"X-Request-ID": "demo-123"})
    assert r2.headers["x-request-id"] == "demo-123"


def test_unsafe_request_id_is_replaced():
    r = TestClient(_app()).get("/health", headers={"X-Request-ID": "bad id\r\ninjected"})
    assert r.headers["x-request-id"] != "bad id\r\ninjected"


def test_404_is_problem_json():
    r = TestClient(_app()).get("/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404 and body["request_id"] == r.headers["x-request-id"]


def test_unhandled_error_is_problem_json_without_internals():
    r = TestClient(_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "secret internal detail" not in r.text
    assert r.json()["request_id"]


def test_mask_emails_and_phones():
    out = _mask("mail anil.kumar@acme.example or call +91 98765 43210")
    assert "anil.kumar@acme.example" not in out and "98765" not in out
    assert "a***@***" in out and out.endswith("***10")


def test_bound_run_context_and_redaction_in_json_logs(capsys):
    configure_logging("INFO", json=True)
    clear_context()
    bind_run(run_id="r-1", channel="email", stage="discover")
    get_logger("t").info("inbound", sender="priya@acme.example", headers={"Authorization": "Bearer x"})
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    clear_context()
    assert line["run_id"] == "r-1" and line["channel"] == "email" and line["stage"] == "discover"
    assert "priya@acme.example" not in json.dumps(line)
    assert line["headers"]["Authorization"] == "[redacted]"

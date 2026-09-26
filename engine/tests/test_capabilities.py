"""Capability discovery reflects the running app, not planned integrations."""

import json

from fastapi.testclient import TestClient

from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.mcp_server import engine_token_configured
from contextrail.surfaces.webhooks import MAX_BODY_BYTES, TOLERANCE_SECONDS


def test_capabilities_report_built_connectors_and_registered_tools():
    settings = Settings(_env_file=None, engine_token="test-engine-token", fs_api_key="test-secret",
                        fs_domain="example.freshservice.com", worker_in_process=False)
    app = create_app(settings)
    client = TestClient(app)
    response = client.get("/v1/capabilities")
    agent_card = client.get("/.well-known/agent.json")

    assert response.status_code == 200
    assert agent_card.status_code == 200
    assert agent_card.json() == response.json()
    body = response.json()
    assert body["connectors"] == app.state.registry.describe(settings)["connectors"]
    assert {tool["name"] for tool in body["tools"]} == {
        "search_enterprise_knowledge", "compile_context_capsule", "check_policy_and_permissions",
        "generate_action_plan", "handoff_to_specialist", "execute_and_verify",
    }
    assert all(tool["enabled"] for tool in body["tools"])
    assert {door["name"] for door in body["doors"]} == {"http", "mcp"}
    assert body["policy_rules"] == sorted(rule.id for rule in app.state.rules)
    assert body["limits"]["freshservice_webhook_body_bytes"] == MAX_BODY_BYTES
    assert body["limits"]["freshservice_webhook_clock_skew_seconds"] == TOLERANCE_SECONDS
    assert "test-secret" not in json.dumps(body)
    assert "test-engine-token" not in json.dumps(body)


def test_unconfigured_doors_are_not_advertised_as_available():
    settings = Settings(_env_file=None, engine_token="change-me", worker_in_process=False)
    app = create_app(settings)
    client = TestClient(app)
    body = client.get("/v1/capabilities").json()

    assert not engine_token_configured(settings)
    assert client.get("/.well-known/agent.json").json() == body
    assert body["doors"] == []
    assert all(not tool["enabled"] for tool in body["tools"])
    assert all(connector["status"] == "built" for connector in body["connectors"])
    assert "planned" not in {connector["name"] for connector in body["connectors"]}


def test_configured_webhook_is_discovered_without_exposing_its_secret():
    settings = Settings(_env_file=None, engine_token="change-me", fs_webhook_secret="test-webhook-secret",
                        worker_in_process=False)
    body = TestClient(create_app(settings)).get("/v1/capabilities").json()

    assert body["doors"] == [{"name": "freshservice_webhook", "path": "/v1/webhooks/freshservice"}]
    assert "test-webhook-secret" not in json.dumps(body)

"""The Slack app manifest in the repo (T139) is what the workspace admin pastes into api.slack.com/apps.

It must parse, ask only for the scopes the Slack door uses, and point every request URL at the route the engine
mounts (POST /slack/events). Length limits are from the app manifest reference (docs.slack.dev/reference/app-manifest).
"""

from pathlib import Path

import yaml

MANIFEST = Path(__file__).resolve().parents[2] / "slack" / "manifest.yaml"


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_parses_and_names_the_app_within_slack_limits():
    m = _manifest()
    info = m["display_information"]
    assert info["name"] == "ContextRail" and len(info["name"]) <= 35
    assert 0 < len(info["description"]) <= 140
    assert m["features"]["bot_user"]["display_name"]


def test_bot_scopes_are_exactly_what_the_door_uses():
    scopes = set(_manifest()["oauth_config"]["scopes"]["bot"])
    assert scopes == {"commands", "chat:write", "im:write", "im:history", "users:read", "users:read.email", "assistant:write"}


def test_slash_command_and_interactivity_post_to_the_engine_route():
    m = _manifest()
    [cmd] = m["features"]["slash_commands"]
    assert cmd["command"] == "/contextrail" and len(cmd["command"]) <= 32
    assert cmd["usage_hint"] and cmd["should_escape"] is False
    interactivity = m["settings"]["interactivity"]
    assert interactivity["is_enabled"] is True
    for url in (cmd["url"], interactivity["request_url"]):
        assert url.startswith("https://") and url.endswith("/slack/events")


def test_human_dm_events_reach_the_engine_route():
    m = _manifest()
    assert m["features"]["app_home"]["messages_tab_read_only_enabled"] is False
    events = m["settings"]["event_subscriptions"]
    assert events["request_url"].endswith("/slack/events")
    assert events["bot_events"] == ["message.im"]


def test_socket_mode_is_on_for_development():
    assert _manifest()["settings"]["socket_mode_enabled"] is True


def test_assistant_pane_is_declared_with_suggested_prompts():
    view = _manifest()["features"]["assistant_view"]
    assert view["assistant_description"]
    prompts = view["suggested_prompts"]
    assert prompts and all(set(p) == {"title", "message"} for p in prompts)

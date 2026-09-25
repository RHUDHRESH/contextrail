"""Settings must read every variable the build context lists in .env.example (CLAUDE.md §19)."""

import re
from pathlib import Path

from contextrail.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def _env_keys_from_claude_md() -> set[str]:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    block = text.split("`.env.example`:", 1)[1].split("```", 2)[1]
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]+)=", block, re.M)}


def test_every_env_example_key_has_a_setting():
    keys = _env_keys_from_claude_md()
    assert len(keys) >= 30, keys
    fields = {name.upper() for name in Settings.model_fields}
    missing = sorted(keys - fields)
    assert not missing, f"Settings is missing: {missing}"


def test_secrets_never_render(monkeypatch):
    monkeypatch.setenv("FS_API_KEY", "super-secret-value")
    s = Settings(_env_file=None)
    assert "super-secret-value" not in repr(s)
    assert s.fs_api_key.get_secret_value() == "super-secret-value"


def test_unconfigured_connectors_report_false(monkeypatch):
    for k in ("FS_DOMAIN", "FS_API_KEY", "SLACK_BOT_TOKEN", "TEAMS_APP_ID"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert not s.freshservice_configured
    assert not s.slack_configured
    assert not s.teams_configured

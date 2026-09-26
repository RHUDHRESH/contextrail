"""Engine configuration, read from the environment (.env locally, SSM-injected env in production).

Every variable in `.env.example` has a field here. Secrets are `SecretStr` so they never render in logs,
reprs or error pages (CLAUDE.md §0 rule 8, §16). Empty optional secrets mean "that connector is not
configured" and the connector must fall back to FIXTURE mode and say so (§0 rule 4).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LanguageCode = Literal["hi-IN", "en-IN", "ta-IN", "kn-IN", "te-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # core
    database_url: str = "postgresql://cr:cr@localhost:5432/cr"
    public_url: str = "http://localhost:8000"
    engine_token: SecretStr = SecretStr("change-me")
    decision_link_secret: SecretStr = SecretStr("change-me")
    log_level: str = "INFO"
    log_json: bool = True
    cors_allowed_origins: list[str] = Field(default_factory=list)
    fixtures_dir: str = ""      # read-only seeds (default: <repo>/fixtures)
    state_dir: str = ""         # mutable FIXTURE connector state (default: <repo>/.state)
    knowledge_dir: str = ""     # OKF bundle (default: <repo>/knowledge)

    # Freshservice (the base) and Freshdesk
    fs_domain: str = ""
    fs_api_key: SecretStr = SecretStr("")
    fs_webhook_secret: SecretStr = SecretStr("")
    fs_rate_limit_per_min: int = 80
    fd_domain: str = ""
    fd_api_key: SecretStr = SecretStr("")

    # LLM router (CLAUDE.md §11)
    anthropic_key_a: SecretStr = SecretStr("")
    anthropic_key_b: SecretStr = SecretStr("")
    aws_region: str = "ap-south-1"
    bedrock_haiku_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_sonnet_id: str = ""      # unused: Claude Haiku 4.5 only (D-013)
    bedrock_budget_usd: Decimal = Decimal(20)   # hard cap in code (D-013)
    run_budget_usd: Decimal = Decimal("0.50")
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-5"  # unused: Claude Haiku 4.5 only (D-013)
    llm_replay_mode: Literal["off", "record", "replay"] = "off"
    bedrock_enabled: bool = False  # T3 only when asked: AWS credentials come from the default chain, not from here
    llm_replay_dir: str = ""       # recorded T4 responses (default: <fixtures>/llm_replay)

    # Email door (SES outbound; inbound arrives via the Freshservice mailbox)
    ses_from_address: str = ""
    ses_configuration_set: str = ""

    # Slack door
    slack_bot_token: SecretStr = SecretStr("")
    slack_signing_secret: SecretStr = SecretStr("")
    slack_app_token: SecretStr = SecretStr("")  # Socket Mode (dev)

    # Teams door
    teams_app_id: str = ""
    teams_app_password: SecretStr = SecretStr("")
    teams_tenant_id: str = ""
    teams_workflow_webhook_url: SecretStr = SecretStr("")  # ONE-WAY fallback

    # Voice door
    sarvam_api_key: SecretStr = SecretStr("")
    agent_language: LanguageCode = "hi-IN"
    tts_speaker: str = "anand"
    vobiz_auth_id: str = ""
    vobiz_auth_token: SecretStr = SecretStr("")

    # Payments (P2)
    dodo_api_key: SecretStr = SecretStr("")

    # Job worker: run it inside the API process (one box), or set false and run `python -m contextrail.worker`
    worker_in_process: bool = True

    @field_validator("public_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # --- configured? helpers: a connector is LIVE only when its credentials exist ---
    @property
    def freshservice_configured(self) -> bool:
        return bool(self.fs_domain and self.fs_api_key.get_secret_value())

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_bot_token.get_secret_value() and self.slack_signing_secret.get_secret_value())

    @property
    def ses_configured(self) -> bool:
        return bool(self.ses_from_address)

    @property
    def teams_configured(self) -> bool:
        return bool(self.teams_app_id and self.teams_app_password.get_secret_value())

    @property
    def teams_one_way_configured(self) -> bool:
        return bool(self.teams_workflow_webhook_url.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

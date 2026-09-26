"""Socket Mode can run from a laptop without the HTTP signing secret."""

from contextrail.settings import Settings
from contextrail.surfaces import slack_socket


def test_socket_mode_accepts_bot_and_app_tokens_without_http_signing_secret(monkeypatch):
    seen = []

    async def serve(settings):
        seen.append(settings)

    monkeypatch.setattr(slack_socket, "_serve", serve)
    settings = Settings(_env_file=None, slack_bot_token="xoxb-test", slack_app_token="xapp-test",
                        slack_signing_secret="")

    assert slack_socket.main(settings) == 0
    assert seen == [settings]

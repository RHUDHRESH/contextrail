"""Block Kit renderers for the Slack door: pure functions of RunView, tested without a database or Slack."""

from contextrail.surfaces import slack_blocks as blocks


def test_untrusted_text_cannot_become_a_mention_or_a_link():
    hostile = "ping <!channel> & see <https://evil.example|payroll>"
    shown = blocks.ack_text(hostile)
    assert "<!channel>" not in shown and "<https://" not in shown
    assert "&lt;!channel&gt; &amp; see &lt;https://evil.example|payroll&gt;" in shown

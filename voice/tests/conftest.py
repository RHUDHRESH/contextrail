"""Offline test setup for the voice door. No test reaches Sarvam, Vobiz, Anthropic, OpenAI or the engine."""

import os

# The copied base constructs its OpenAI client at import time and refuses an empty key. A fake value lets the
# module import; no request is ever sent with it.
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder-not-a-key")

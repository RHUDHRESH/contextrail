"""Offline test setup for the voice door. No test reaches Sarvam, Vobiz, Anthropic or the engine."""

import os

# Never let a developer's real key turn a test into a paid model call.
os.environ["ANTHROPIC_KEY_A"] = ""

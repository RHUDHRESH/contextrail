"""Offline test setup for the voice door. No test reaches Sarvam, Vobiz, Anthropic or the engine."""

import os

# Never let a developer's real keys turn a test into a paid call or a real engine/Vobiz request.
for key in ("ANTHROPIC_KEY_A", "SARVAM_API_KEY", "ENGINE_TOKEN", "VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN"):
    os.environ[key] = ""

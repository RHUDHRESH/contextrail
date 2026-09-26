"""The languages the phone speaks (CLAUDE.md §13.3): Hindi by default, plus English, Tamil and Kannada.

One code drives both ends of a call, as upstream: it is Saaras v3's `language_code` and Bulbul v3's
`target_language_code`. Each language has its own Bulbul v3 voice (any v3 voice speaks every supported language;
the names come from sarvam-ai-sdk's SpeakerSchema) and its own fixed lines.

A caller changes language by naming it ("English please", "तमिल", "ಕನ್ನಡ"). Only short utterances count, so a
request that happens to mention a language ("Priya from the Tamil Nadu office") never switches the call.

The Hindi, Tamil and Kannada lines were written for this build and have not yet been reviewed by native speakers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from types import MappingProxyType

DEFAULT = "hi-IN"
BULBUL_V3_SPEAKERS = frozenset({
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan", "sumit", "kabir", "aayan",
    "ashutosh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham", "ritu",
    "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "amelia", "sophia", "tanya", "shruti",
    "suhani", "kavitha", "rupali"})
_SWITCH_MAX_WORDS = 4


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    speaker: str
    names: tuple[str, ...]  # how callers say this language's name, in the scripts Saaras may transcribe
    lines: MappingProxyType = field(repr=False)


def _lang(code, name, speaker, names, **lines) -> Language:
    return Language(code, name, speaker, names, MappingProxyType(lines))


SUPPORTED: dict[str, Language] = {
    "hi-IN": _lang(
        "hi-IN", "Hindi", "anand", ("hindi", "हिंदी", "हिन्दी", "இந்தி", "ஹிந்தி", "ಹಿಂದಿ"),
        disclosure="नमस्ते, मैं कॉन्टेक्स्टरेल का एआई सहायक हूँ, कोई इंसान नहीं।",
        help="मैं आपकी कैसे मदद कर सकता हूँ?",
        fallback="माफ करें, मुझे समझने में परेशानी हो रही है।",
        switched="ठीक है, अब हम हिंदी में बात करेंगे।",
    ),
    "en-IN": _lang(
        "en-IN", "English", "priya",
        ("english", "इंग्लिश", "अंग्रेज़ी", "अंग्रेजी", "ஆங்கிலம்", "இங்கிலீஷ்", "ಇಂಗ್ಲಿಷ್", "ಇಂಗ್ಲೀಷ್"),
        disclosure="Hello, I am ContextRail's AI assistant, not a person.",
        help="How can I help you?",
        fallback="Sorry, I'm having trouble understanding.",
        switched="Okay, we'll continue in English.",
    ),
    "ta-IN": _lang(
        "ta-IN", "Tamil", "kavitha", ("tamil", "तमिल", "தமிழ்", "ತಮಿಳು"),
        disclosure="வணக்கம், நான் ContextRail-இன் AI உதவியாளர், மனிதர் அல்ல.",
        help="நான் உங்களுக்கு எப்படி உதவ முடியும்?",
        fallback="மன்னிக்கவும், எனக்குப் புரிந்துகொள்வதில் சிரமம் உள்ளது.",
        switched="சரி, இனி தமிழில் பேசலாம்.",
    ),
    "kn-IN": _lang(
        "kn-IN", "Kannada", "roopa", ("kannada", "कन्नड़", "कन्नड", "கன்னடம்", "ಕನ್ನಡ"),
        disclosure="ನಮಸ್ಕಾರ, ನಾನು ContextRail ನ AI ಸಹಾಯಕ, ಮನುಷ್ಯನಲ್ಲ.",
        help="ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
        fallback="ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲು ತೊಂದರೆಯಾಗುತ್ತಿದೆ.",
        switched="ಸರಿ, ಇನ್ನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡೋಣ.",
    ),
}


class LanguageTable:
    """The supported languages as this deployment runs them: a default, and any TTS_SPEAKER override applied."""

    def __init__(self, languages: dict[str, Language], default: str) -> None:
        self._languages, self.default = languages, languages[default]

    def __getitem__(self, code: str) -> Language:
        return self._languages[code]


def configure(agent_language: str, *, tts_speaker: str = "") -> LanguageTable:
    """AGENT_LANGUAGE picks the default; TTS_SPEAKER, if set, replaces that language's voice. Bad values fail loudly
    at startup rather than leaving callers in silence (upstream's TTS returns nothing for an unknown speaker)."""
    if agent_language not in SUPPORTED:
        raise ValueError(f"AGENT_LANGUAGE={agent_language!r} is not supported; use one of {sorted(SUPPORTED)}")
    languages = dict(SUPPORTED)
    if tts_speaker:
        if tts_speaker not in BULBUL_V3_SPEAKERS:
            raise ValueError(f"TTS_SPEAKER={tts_speaker!r} is not a lowercase bulbul:v3 voice")
        languages[agent_language] = replace(languages[agent_language], speaker=tts_speaker)
    return LanguageTable(languages, agent_language)


def _mentions(text: str, name: str) -> bool:
    if name.isascii():
        return re.search(rf"\b{re.escape(name)}\b", text) is not None
    return name in text  # Indic scripts: \b is unreliable around vowel signs, so match the substring


def detect_switch(text: str) -> str | None:
    """The language a short utterance names, or None. Two languages named at once is not a switch."""
    said = text.casefold().strip()
    if not said or len(said.split()) > _SWITCH_MAX_WORDS:
        return None
    named = {code for code, lang in SUPPORTED.items() if any(_mentions(said, n) for n in lang.names)}
    return named.pop() if len(named) == 1 else None

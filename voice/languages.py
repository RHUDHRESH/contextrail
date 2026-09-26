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
        menu=("आप नया अनुरोध कर सकते हैं, किसी अनुरोध की स्थिति पूछ सकते हैं, नीति के बारे में सवाल पूछ सकते हैं, "
              "या अपनी मंज़ूरी के लिए रुके आइटम तय कर सकते हैं। भाषा बदलने के लिए English, Tamil या Kannada कहें।"),
        unregistered=("आपका नंबर कॉन्टेक्स्टरेल में पंजीकृत नहीं है, इसलिए मैं केवल सामान्य नीति से जुड़े सवालों के "
                      "जवाब दे सकता हूँ।"),
        fallback="माफ करें, मुझे समझने में परेशानी हो रही है।",
        switched="ठीक है, अब हम हिंदी में बात करेंगे।",
        ask_request="आप क्या अनुरोध करना चाहते हैं? कृपया एक वाक्य में बताइए।",
        readback="मैंने सुना: {text}। क्या मैं यह अनुरोध शुरू करूँ? कृपया हाँ या नहीं कहिए।",
        yes_or_no="आगे बढ़ने के लिए हाँ कहिए, या रद्द करने के लिए नहीं।",
        started="मैंने आपका अनुरोध शुरू कर दिया है। आपका संदर्भ नंबर है {ref}।",
        status="इसकी स्थिति है: {status}।",
        counts="{allow} मंज़ूर, {hold} मंज़ूरी के इंतज़ार में, और {refuse} अस्वीकार।",
        cancelled="ठीक है, मैंने कुछ भी शुरू नहीं किया।",
        engine_down="अभी मैं कॉन्टेक्स्टरेल से जुड़ नहीं पा रहा हूँ। कृपया थोड़ी देर बाद फिर कोशिश करें।",
        st_running="जारी है", st_needs_input="और जानकारी का इंतज़ार", st_awaiting_approval="मंज़ूरी का इंतज़ार",
        st_partial="आंशिक रूप से पूरा", st_done="पूरा", st_failed="विफल",
    ),
    "en-IN": _lang(
        "en-IN", "English", "priya",
        ("english", "इंग्लिश", "अंग्रेज़ी", "अंग्रेजी", "ஆங்கிலம்", "இங்கிலீஷ்", "ಇಂಗ್ಲಿಷ್", "ಇಂಗ್ಲೀಷ್"),
        disclosure="Hello, I am ContextRail's AI assistant, not a person.",
        menu=("You can make a new request, ask about a request's status, ask a policy question, or decide items "
              "waiting for your approval. To change language, say Hindi, Tamil or Kannada."),
        unregistered=("Your number is not registered with ContextRail, so I can only answer general policy "
                      "questions."),
        fallback="Sorry, I'm having trouble understanding.",
        switched="Okay, we'll continue in English.",
        ask_request="What would you like to request? Please say it in one sentence.",
        readback="I heard: {text}. Shall I start this request? Please say yes or no.",
        yes_or_no="Please say yes to go ahead, or no to cancel.",
        started="I have started your request. Your reference is {ref}.",
        status="Its status is: {status}.",
        counts="{allow} allowed, {hold} waiting for approval, and {refuse} refused.",
        cancelled="Okay, I have not started anything.",
        engine_down="I can't reach ContextRail right now. Please try again in a little while.",
        st_running="in progress", st_needs_input="waiting for more details", st_awaiting_approval="waiting for approval",
        st_partial="partly done", st_done="done", st_failed="failed",
    ),
    "ta-IN": _lang(
        "ta-IN", "Tamil", "kavitha", ("tamil", "तमिल", "தமிழ்", "ತಮಿಳು"),
        disclosure="வணக்கம், நான் ContextRail-இன் AI உதவியாளர், மனிதர் அல்ல.",
        menu=("நீங்கள் புதிய கோரிக்கை வைக்கலாம், ஒரு கோரிக்கையின் நிலையைக் கேட்கலாம், கொள்கை பற்றிக் கேட்கலாம், "
              "அல்லது உங்கள் ஒப்புதலுக்காகக் காத்திருப்பவற்றை முடிவு செய்யலாம். மொழியை மாற்ற Hindi, English அல்லது "
              "Kannada என்று சொல்லுங்கள்."),
        unregistered=("உங்கள் எண் ContextRail-இல் பதிவு செய்யப்படவில்லை, எனவே பொதுவான கொள்கைக் கேள்விகளுக்கு "
                      "மட்டுமே என்னால் பதில் சொல்ல முடியும்."),
        fallback="மன்னிக்கவும், எனக்குப் புரிந்துகொள்வதில் சிரமம் உள்ளது.",
        switched="சரி, இனி தமிழில் பேசலாம்.",
        ask_request="நீங்கள் என்ன கோரிக்கை வைக்க விரும்புகிறீர்கள்? ஒரே வாக்கியத்தில் சொல்லுங்கள்.",
        readback="நான் கேட்டது: {text}. இந்தக் கோரிக்கையைத் தொடங்கட்டுமா? ஆம் அல்லது இல்லை என்று சொல்லுங்கள்.",
        yes_or_no="தொடர ஆம் என்றும், ரத்து செய்ய இல்லை என்றும் சொல்லுங்கள்.",
        started="உங்கள் கோரிக்கையைத் தொடங்கிவிட்டேன். உங்கள் குறிப்பு எண் {ref}.",
        status="அதன் நிலை: {status}.",
        counts="{allow} அனுமதிக்கப்பட்டது, {hold} ஒப்புதலுக்காகக் காத்திருக்கிறது, {refuse} மறுக்கப்பட்டது.",
        cancelled="சரி, நான் எதையும் தொடங்கவில்லை.",
        engine_down="இப்போது ContextRail-ஐ அணுக முடியவில்லை. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.",
        st_running="நடந்து கொண்டிருக்கிறது", st_needs_input="கூடுதல் விவரங்களுக்காகக் காத்திருக்கிறது",
        st_awaiting_approval="ஒப்புதலுக்காகக் காத்திருக்கிறது", st_partial="பகுதியாக முடிந்தது",
        st_done="முடிந்தது", st_failed="தோல்வியடைந்தது",
    ),
    "kn-IN": _lang(
        "kn-IN", "Kannada", "roopa", ("kannada", "कन्नड़", "कन्नड", "கன்னடம்", "ಕನ್ನಡ"),
        disclosure="ನಮಸ್ಕಾರ, ನಾನು ContextRail ನ AI ಸಹಾಯಕ, ಮನುಷ್ಯನಲ್ಲ.",
        menu=("ನೀವು ಹೊಸ ವಿನಂತಿ ಮಾಡಬಹುದು, ವಿನಂತಿಯ ಸ್ಥಿತಿ ಕೇಳಬಹುದು, ನೀತಿಯ ಬಗ್ಗೆ ಪ್ರಶ್ನೆ ಕೇಳಬಹುದು, ಅಥವಾ ನಿಮ್ಮ "
              "ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿರುವವನ್ನು ನಿರ್ಧರಿಸಬಹುದು. ಭಾಷೆ ಬದಲಾಯಿಸಲು Hindi, English ಅಥವಾ Tamil ಎಂದು ಹೇಳಿ."),
        unregistered=("ನಿಮ್ಮ ಸಂಖ್ಯೆ ContextRail ನಲ್ಲಿ ನೋಂದಣಿಯಾಗಿಲ್ಲ, ಆದ್ದರಿಂದ ನಾನು ಸಾಮಾನ್ಯ ನೀತಿ ಪ್ರಶ್ನೆಗಳಿಗೆ ಮಾತ್ರ "
                      "ಉತ್ತರಿಸಬಲ್ಲೆ."),
        fallback="ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲು ತೊಂದರೆಯಾಗುತ್ತಿದೆ.",
        switched="ಸರಿ, ಇನ್ನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡೋಣ.",
        ask_request="ನೀವು ಏನು ವಿನಂತಿಸಲು ಬಯಸುತ್ತೀರಿ? ದಯವಿಟ್ಟು ಒಂದೇ ವಾಕ್ಯದಲ್ಲಿ ಹೇಳಿ.",
        readback="ನಾನು ಕೇಳಿದ್ದು: {text}. ಈ ವಿನಂತಿಯನ್ನು ಪ್ರಾರಂಭಿಸಲೇ? ದಯವಿಟ್ಟು ಹೌದು ಅಥವಾ ಇಲ್ಲ ಎಂದು ಹೇಳಿ.",
        yes_or_no="ಮುಂದುವರಿಯಲು ಹೌದು ಎಂದು, ರದ್ದುಗೊಳಿಸಲು ಇಲ್ಲ ಎಂದು ಹೇಳಿ.",
        started="ನಿಮ್ಮ ವಿನಂತಿಯನ್ನು ಪ್ರಾರಂಭಿಸಿದ್ದೇನೆ. ನಿಮ್ಮ ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ {ref}.",
        status="ಅದರ ಸ್ಥಿತಿ: {status}.",
        counts="{allow} ಅನುಮತಿಸಲಾಗಿದೆ, {hold} ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿದೆ, {refuse} ನಿರಾಕರಿಸಲಾಗಿದೆ.",
        cancelled="ಸರಿ, ನಾನು ಏನನ್ನೂ ಪ್ರಾರಂಭಿಸಿಲ್ಲ.",
        engine_down="ಈಗ ContextRail ಅನ್ನು ತಲುಪಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
        st_running="ನಡೆಯುತ್ತಿದೆ", st_needs_input="ಹೆಚ್ಚಿನ ವಿವರಗಳಿಗಾಗಿ ಕಾಯುತ್ತಿದೆ",
        st_awaiting_approval="ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿದೆ", st_partial="ಭಾಗಶಃ ಮುಗಿದಿದೆ", st_done="ಮುಗಿದಿದೆ",
        st_failed="ವಿಫಲವಾಗಿದೆ",
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

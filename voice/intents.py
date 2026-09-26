"""What does the caller want? One of four door flows (CLAUDE.md §13.3 item 3), a person, or unclear.

Keywords decide first, in all four languages at once (callers mix languages; Saaras transcribes English words in
Latin or native script). Precedence is fixed: human, status, approve, policy, request, so "what happened to my
access request" is a status question, and "can contractors get production access?" is a policy question.

Only when no keyword matches is the phone's Sarvam conversation model asked for one label from INTENTS.
Routing never acts: it picks which flow talks next, and each flow confirms with the caller before the engine is
called (read-back for requests, spoken confirmation and DTMF for approvals); status and policy are read-only.
"""

from __future__ import annotations

import re
from typing import Literal

from llm import Conversation

Intent = Literal["request", "status", "policy", "approve", "human", "unclear"]
INTENTS: tuple[str, ...] = ("request", "status", "policy", "approve", "human", "unclear")

# English as regular expressions (word boundaries: "person" must not match "personal"); Indic scripts as stems
# matched by substring (\b is unreliable around vowel signs). Tamil stems stop before the final virama.
_KEYWORDS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("human",
     (r"\bhuman\b", r"\b(real )?person\b", r"\boperator\b", r"\brepresentative\b"),
     ("इंसान", "व्यक्ति से बात", "ऑपरेटर", "மனிதர", "நபரிடம", "ஆபரேட்டர", "ಮನುಷ್ಯ", "ವ್ಯಕ್ತಿಯೊಂದಿಗೆ", "ಆಪರೇಟರ್")),
    ("status",
     (r"\bstatus\b", r"\bwhat happened\b", r"\bupdate on\b", r"\bany update\b"),
     ("क्या हुआ", "स्थिति", "स्टेटस", "நிலை", "என்ன ஆனது", "ஸ்டேட்டஸ", "ಸ್ಥಿತಿ", "ಏನಾಯಿತು", "ಸ್ಟೇಟಸ")),
    ("approve",
     (r"\bapprove\b", r"\bapprovals?\b", r"\bpending\b", r"\bwaiting for me\b", r"\bsign off\b"),
     ("अप्रूव", "मंज़ूरी", "मंजूरी", "स्वीकृति", "पेंडिंग", "ஒப்புதல", "அப்ரூவ", "நிலுவை", "ಅನುಮೋದನೆ", "ಅಪ್ರೂವ",
      "ಬಾಕಿ")),
    ("policy",
     (r"\bpolic(y|ies)\b", r"\ballowed\b", r"\bpermitted\b", r"\brules?\b", r"\bis it (ok|okay)\b",
      r"\bcan (a|an|the|contractors?|employees?|vendors?|interns?|someone|anyone|i|we)\b"),
     ("नीति", "पॉलिसी", "नियम", "अनुमति", "मिल सकता", "मिल सकती", "मिल सकते", "கொள்கை", "விதி", "அனுமதி",
      "கிடைக்குமா", "ನೀತಿ", "ನಿಯಮ", "ಅನುಮತಿ", "ಸಿಗುತ್ತದೆಯೇ", "ಸಿಗುತ್ತಾ")),
    ("request",
     (r"\bgive\b", r"\bgrant\b", r"\baccess\b", r"\bonboard(ing)?\b", r"\bstarts\b", r"\bjoining\b", r"\bneed\b",
      r"\bsame as\b", r"\bprovision\b", r"\brefund\b", r"\bcredit\b", r"\bnew request\b", r"\bmake a request\b"),
     ("एक्सेस", "दे दो", "दीजिए", "चाहिए", "जैसा", "ऑनबोर्ड", "नया अनुरोध", "नई रिक्वेस्ट", "அணுகல", "கொடு",
      "வேண்டும", "புதிய கோரிக்கை", "ಪ್ರವೇಶ", "ಕೊಡಿ", "ಕೊಡು", "ಬೇಕು", "ಹೊಸ ವಿನಂತಿ")),
)

# Asking to make a request without saying what it is ("I want to make a new request").
_ASKS_TO_REQUEST = (r"\b(new|make a|raise a) request\b", "नया अनुरोध", "नई रिक्वेस्ट", "புதிய கோரிக்கை",
                    "ಹೊಸ ವಿನಂತಿ")
_ASK_MAX_WORDS = 7

# Yes / no after a read-back. A "no" anywhere wins: cancelling is the safe side of a misheard answer.
_NO = ((r"\b(no|nope|not|cancel|don'?t|do not|wrong|stop)\b",),
       ("नहीं", "नही", "रद्द", "कैंसल", "இல்லை", "வேண்டாம", "ரத்து", "ಇಲ್ಲ", "ಬೇಡ", "ರದ್ದು"))
_YES = ((r"\b(yes|yeah|yep|yup|sure|correct|right|ok|okay|go ahead|confirm|please do)\b",),
        ("हाँ", "हां", "ठीक है", "बिल्कुल", "सही है", "ஆம", "சரி", "ஓகே", "ಹೌದು", "ಸರಿ", "ಓಕೆ"))


def _any(said: str, patterns: tuple[str, ...], stems: tuple[str, ...]) -> bool:
    return any(re.search(p, said) for p in patterns) or any(s in said for s in stems)


def match_keywords(text: str) -> Intent | None:
    said = text.casefold()
    for intent, patterns, stems in _KEYWORDS:
        if _any(said, patterns, stems):
            return intent  # type: ignore[return-value]
    return None


def asks_to_request(text: str) -> bool:
    said = text.casefold()
    return len(said.split()) <= _ASK_MAX_WORDS and _any(said, _ASKS_TO_REQUEST[:1], _ASKS_TO_REQUEST[1:])


_NEXT = ((r"\b(next|skip|later)\b",), ("अगला", "अगले", "छोड़", "बाद में", "அடுத்த", "தவிர்", "பிறகு",
                                      "ಮುಂದಿನ", "ಬಿಟ್ಟು", "ನಂತರ"))


def match_next(text: str) -> bool:
    return _any(text.casefold(), *_NEXT)


def match_yes_no(text: str) -> bool | None:
    said = text.casefold()
    if _any(said, *_NO):
        return False
    return True if _any(said, *_YES) else None


async def route(text: str, llm: Conversation) -> Intent:
    found = match_keywords(text)
    if found:
        return found
    label = await llm.classify(text, INTENTS)
    return label if label in INTENTS else "unclear"  # type: ignore[return-value]

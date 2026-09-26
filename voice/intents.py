"""What does the caller want? One of four door flows (CLAUDE.md §13.3 item 3), a person, or unclear.

Keywords decide first, in all four languages at once (callers mix languages; Saaras transcribes English words in
Latin or native script). Precedence is fixed: human, status, approve, policy, request, so "what happened to my
access request" is a status question, and "can contractors get production access?" is a policy question.

Only when no keyword matches is Haiku asked, through a forced tool whose only output is one label from INTENTS.
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
      r"\bsame as\b", r"\bprovision\b", r"\brefund\b", r"\bcredit\b"),
     ("एक्सेस", "दे दो", "दीजिए", "चाहिए", "जैसा", "ऑनबोर्ड", "அணுகல", "கொடு", "வேண்டும", "ಪ್ರವೇಶ", "ಕೊಡಿ",
      "ಕೊಡು", "ಬೇಕು")),
)


def match_keywords(text: str) -> Intent | None:
    said = text.casefold()
    for intent, patterns, stems in _KEYWORDS:
        if any(re.search(p, said) for p in patterns) or any(s in said for s in stems):
            return intent  # type: ignore[return-value]
    return None


async def route(text: str, llm: Conversation) -> Intent:
    found = match_keywords(text)
    if found:
        return found
    label = await llm.classify(text, INTENTS)
    return label if label in INTENTS else "unclear"  # type: ignore[return-value]

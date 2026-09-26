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
        ticket_created="फ्रेशसर्विस टिकट नंबर {number} बनाया और जाँचा गया है। मोड {mode} है।",
        ticket_unavailable="फ्रेशसर्विस टिकट की पुष्टि अभी नहीं हुई है।",
        transferring="मैं आपको सेवा डेस्क के इंसान से जोड़ रहा हूँ।",
        transfer_failed="सेवा डेस्क से संपर्क नहीं हो पाया। आप फिर कोशिश कर सकते हैं।",
        human_unavailable="अभी इंसान से फोन पर जोड़ने की सुविधा उपलब्ध नहीं है। कृपया सेवा डेस्क से सीधे संपर्क करें।",
        status="इसकी स्थिति है: {status}।",
        counts="{allow} मंज़ूर, {hold} मंज़ूरी के इंतज़ार में, और {refuse} अस्वीकार।",
        cancelled="ठीक है, मैंने कुछ भी शुरू नहीं किया।",
        engine_down="अभी मैं कॉन्टेक्स्टरेल से जुड़ नहीं पा रहा हूँ। कृपया थोड़ी देर बाद फिर कोशिश करें।",
        st_running="जारी है", st_needs_input="और जानकारी का इंतज़ार", st_awaiting_approval="मंज़ूरी का इंतज़ार",
        st_partial="आंशिक रूप से पूरा", st_done="पूरा", st_failed="विफल",
        from_records="कॉन्टेक्स्टरेल के रिकॉर्ड के अनुसार:",
        no_answer="इसका कोई दर्ज जवाब कॉन्टेक्स्टरेल के पास नहीं है।",
        nothing_pending="आपकी मंज़ूरी के लिए कुछ भी रुका नहीं है।",
        pending_count="{n} आइटम आपकी मंज़ूरी का इंतज़ार कर रहे हैं।",
        item="आइटम {i}: {label}, {subject} के लिए, नियम {rule} के तहत।",
        decide_this="इस आइटम पर फ़ैसला करने के लिए हाँ कहिए, या छोड़ने के लिए अगला कहिए।",
        press_keys="मंज़ूर करने के लिए 1 दबाइए, या अस्वीकार करने के लिए 2 दबाइए।",
        high_risk=("यह आइटम उच्च जोखिम वाला है, इसलिए इसका फ़ैसला फ़ोन पर नहीं हो सकता। कृपया इसे Slack या Teams "
                   "में एक टैप से मंज़ूर या अस्वीकार करें।"),
        decided_approved="दर्ज हो गया: आपने इसे मंज़ूर किया।",
        decided_refused="दर्ज हो गया: आपने इसे अस्वीकार किया।",
        already_decided="इस आइटम का फ़ैसला पहले ही {channel} में हो चुका है।",
        already_yours="आप इस आइटम का फ़ैसला पहले ही कर चुके हैं।",
        rejected="कॉन्टेक्स्टरेल ने यह फ़ैसला स्वीकार नहीं किया:",
        no_key="कोई बटन नहीं दबाया गया, इसलिए कोई फ़ैसला नहीं हुआ।",
        no_more="आपके लिए रुका यह आख़िरी आइटम था।",
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
        ticket_created="Freshservice ticket number {number} was created and verified in {mode} mode.",
        ticket_unavailable="A Freshservice ticket has not been verified yet.",
        transferring="I am connecting you to a person at the service desk.",
        transfer_failed="I could not connect you to the service desk. You can try again.",
        human_unavailable="A phone transfer is not available. Please contact the service desk directly.",
        status="Its status is: {status}.",
        counts="{allow} allowed, {hold} waiting for approval, and {refuse} refused.",
        cancelled="Okay, I have not started anything.",
        engine_down="I can't reach ContextRail right now. Please try again in a little while.",
        st_running="in progress", st_needs_input="waiting for more details", st_awaiting_approval="waiting for approval",
        st_partial="partly done", st_done="done", st_failed="failed",
        from_records="Here is what ContextRail's records say:",
        no_answer="ContextRail has no recorded answer to that.",
        nothing_pending="Nothing is waiting for your approval.",
        pending_count="{n} items are waiting for your approval.",
        item="Item {i}: {label}, for {subject}, under rule {rule}.",
        decide_this="Say yes to decide this item, or next to skip it.",
        press_keys="Press 1 to approve, or 2 to refuse.",
        high_risk=("This item is high risk, so it cannot be decided by phone. Please approve or refuse it with a tap "
                   "in Slack or Teams."),
        decided_approved="Recorded: you approved it.",
        decided_refused="Recorded: you refused it.",
        already_decided="This item was already decided, in {channel}.",
        already_yours="You have already decided this item.",
        rejected="ContextRail did not accept that decision:",
        no_key="No key was pressed, so nothing was decided.",
        no_more="That was the last item waiting for you.",
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
        ticket_created="Freshservice டிக்கெட் எண் {number} உருவாக்கப்பட்டு {mode} முறையில் சரிபார்க்கப்பட்டது.",
        ticket_unavailable="Freshservice டிக்கெட் இன்னும் சரிபார்க்கப்படவில்லை.",
        transferring="உங்களை சேவை மையத்தில் உள்ள ஒருவருடன் இணைக்கிறேன்.",
        transfer_failed="சேவை மையத்துடன் இணைக்க முடியவில்லை. மீண்டும் முயற்சிக்கலாம்.",
        human_unavailable="தொலைபேசி வழியாக மனிதருடன் இணைக்கும் வசதி இப்போது இல்லை. சேவை மையத்தை நேரடியாகத் தொடர்புகொள்ளவும்.",
        status="அதன் நிலை: {status}.",
        counts="{allow} அனுமதிக்கப்பட்டது, {hold} ஒப்புதலுக்காகக் காத்திருக்கிறது, {refuse} மறுக்கப்பட்டது.",
        cancelled="சரி, நான் எதையும் தொடங்கவில்லை.",
        engine_down="இப்போது ContextRail-ஐ அணுக முடியவில்லை. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.",
        st_running="நடந்து கொண்டிருக்கிறது", st_needs_input="கூடுதல் விவரங்களுக்காகக் காத்திருக்கிறது",
        st_awaiting_approval="ஒப்புதலுக்காகக் காத்திருக்கிறது", st_partial="பகுதியாக முடிந்தது",
        st_done="முடிந்தது", st_failed="தோல்வியடைந்தது",
        from_records="ContextRail பதிவுகளின்படி:",
        no_answer="அதற்கு ContextRail-இடம் பதிவு செய்யப்பட்ட பதில் இல்லை.",
        nothing_pending="உங்கள் ஒப்புதலுக்காக எதுவும் காத்திருக்கவில்லை.",
        pending_count="{n} உருப்படிகள் உங்கள் ஒப்புதலுக்காகக் காத்திருக்கின்றன.",
        item="உருப்படி {i}: {label}, {subject}-க்காக, விதி {rule}-இன் கீழ்.",
        decide_this="இதை முடிவு செய்ய ஆம் என்றும், தவிர்க்க அடுத்தது என்றும் சொல்லுங்கள்.",
        press_keys="ஒப்புதல் அளிக்க 1-ஐ அழுத்துங்கள், மறுக்க 2-ஐ அழுத்துங்கள்.",
        high_risk=("இந்த உருப்படி அதிக அபாயம் கொண்டது, எனவே தொலைபேசியில் முடிவு செய்ய முடியாது. Slack அல்லது "
                   "Teams-இல் ஒரு தட்டலில் ஒப்புதல் அளிக்கவும் அல்லது மறுக்கவும்."),
        decided_approved="பதிவு செய்யப்பட்டது: நீங்கள் ஒப்புதல் அளித்தீர்கள்.",
        decided_refused="பதிவு செய்யப்பட்டது: நீங்கள் மறுத்தீர்கள்.",
        already_decided="இந்த உருப்படி ஏற்கனவே {channel}-இல் முடிவு செய்யப்பட்டது.",
        already_yours="இந்த உருப்படியை நீங்கள் ஏற்கனவே முடிவு செய்துவிட்டீர்கள்.",
        rejected="ContextRail அந்த முடிவை ஏற்கவில்லை:",
        no_key="எந்த விசையும் அழுத்தப்படவில்லை, எனவே எதுவும் முடிவு செய்யப்படவில்லை.",
        no_more="உங்களுக்காகக் காத்திருந்த கடைசி உருப்படி இதுதான்.",
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
        ticket_created="Freshservice ಟಿಕೆಟ್ ಸಂಖ್ಯೆ {number} ರಚಿಸಿ {mode} ವಿಧಾನದಲ್ಲಿ ಪರಿಶೀಲಿಸಲಾಗಿದೆ.",
        ticket_unavailable="Freshservice ಟಿಕೆಟ್ ಇನ್ನೂ ಪರಿಶೀಲನೆಯಾಗಿಲ್ಲ.",
        transferring="ನಿಮ್ಮನ್ನು ಸೇವಾ ಕೇಂದ್ರದ ವ್ಯಕ್ತಿಯೊಂದಿಗೆ ಸಂಪರ್ಕಿಸುತ್ತಿದ್ದೇನೆ.",
        transfer_failed="ಸೇವಾ ಕೇಂದ್ರವನ್ನು ಸಂಪರ್ಕಿಸಲಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಬಹುದು.",
        human_unavailable="ಫೋನ್ ಮೂಲಕ ವ್ಯಕ್ತಿಗೆ ವರ್ಗಾವಣೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ. ಸೇವಾ ಕೇಂದ್ರವನ್ನು ನೇರವಾಗಿ ಸಂಪರ್ಕಿಸಿ.",
        status="ಅದರ ಸ್ಥಿತಿ: {status}.",
        counts="{allow} ಅನುಮತಿಸಲಾಗಿದೆ, {hold} ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿದೆ, {refuse} ನಿರಾಕರಿಸಲಾಗಿದೆ.",
        cancelled="ಸರಿ, ನಾನು ಏನನ್ನೂ ಪ್ರಾರಂಭಿಸಿಲ್ಲ.",
        engine_down="ಈಗ ContextRail ಅನ್ನು ತಲುಪಲು ಸಾಧ್ಯವಾಗುತ್ತಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
        st_running="ನಡೆಯುತ್ತಿದೆ", st_needs_input="ಹೆಚ್ಚಿನ ವಿವರಗಳಿಗಾಗಿ ಕಾಯುತ್ತಿದೆ",
        st_awaiting_approval="ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿದೆ", st_partial="ಭಾಗಶಃ ಮುಗಿದಿದೆ", st_done="ಮುಗಿದಿದೆ",
        st_failed="ವಿಫಲವಾಗಿದೆ",
        from_records="ContextRail ದಾಖಲೆಗಳ ಪ್ರಕಾರ:",
        no_answer="ಅದಕ್ಕೆ ContextRail ನಲ್ಲಿ ದಾಖಲಾದ ಉತ್ತರವಿಲ್ಲ.",
        nothing_pending="ನಿಮ್ಮ ಅನುಮೋದನೆಗಾಗಿ ಏನೂ ಕಾಯುತ್ತಿಲ್ಲ.",
        pending_count="{n} ಐಟಂಗಳು ನಿಮ್ಮ ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿವೆ.",
        item="ಐಟಂ {i}: {label}, {subject} ಅವರಿಗಾಗಿ, ನಿಯಮ {rule} ಅಡಿಯಲ್ಲಿ.",
        decide_this="ಇದನ್ನು ನಿರ್ಧರಿಸಲು ಹೌದು ಎಂದು, ಬಿಟ್ಟುಬಿಡಲು ಮುಂದಿನದು ಎಂದು ಹೇಳಿ.",
        press_keys="ಅನುಮೋದಿಸಲು 1 ಒತ್ತಿರಿ, ನಿರಾಕರಿಸಲು 2 ಒತ್ತಿರಿ.",
        high_risk=("ಈ ಐಟಂ ಹೆಚ್ಚಿನ ಅಪಾಯದ್ದು, ಆದ್ದರಿಂದ ಫೋನ್‌ನಲ್ಲಿ ನಿರ್ಧರಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು Slack ಅಥವಾ Teams "
                   "ನಲ್ಲಿ ಒಂದು ಟ್ಯಾಪ್ ಮೂಲಕ ಅನುಮೋದಿಸಿ ಅಥವಾ ನಿರಾಕರಿಸಿ."),
        decided_approved="ದಾಖಲಾಗಿದೆ: ನೀವು ಅನುಮೋದಿಸಿದ್ದೀರಿ.",
        decided_refused="ದಾಖಲಾಗಿದೆ: ನೀವು ನಿರಾಕರಿಸಿದ್ದೀರಿ.",
        already_decided="ಈ ಐಟಂ ಈಗಾಗಲೇ {channel} ನಲ್ಲಿ ನಿರ್ಧಾರವಾಗಿದೆ.",
        already_yours="ನೀವು ಈ ಐಟಂ ಅನ್ನು ಈಗಾಗಲೇ ನಿರ್ಧರಿಸಿದ್ದೀರಿ.",
        rejected="ContextRail ಆ ನಿರ್ಧಾರವನ್ನು ಸ್ವೀಕರಿಸಲಿಲ್ಲ:",
        no_key="ಯಾವುದೇ ಕೀ ಒತ್ತಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಏನೂ ನಿರ್ಧಾರವಾಗಿಲ್ಲ.",
        no_more="ನಿಮಗಾಗಿ ಕಾಯುತ್ತಿದ್ದ ಕೊನೆಯ ಐಟಂ ಇದು.",
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

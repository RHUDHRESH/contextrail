"""T199: the phone speaks Hindi by default, plus English, Tamil and Kannada, each with its own Bulbul v3 voice, and
listens and speaks in the same language (Saaras v3 language_code = Bulbul v3 target_language_code)."""

import pytest

import agent
import languages
from languages import DEFAULT, SUPPORTED, configure, detect_switch
from tests.fake_sarvam import FakeSarvam
from tests.fakes import FakeWS

# sarvamai/sarvam-ai-sdk src/tts/speech-settings.ts SpeakerSchema (refs/MANIFEST.md 956f54e): the bulbul:v3 voices.
BULBUL_V3_SPEAKERS = {
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan", "sumit", "kabir", "aayan",
    "ashutosh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham", "ritu",
    "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "amelia", "sophia", "tanya", "shruti",
    "suhani", "kavitha", "rupali"}


def test_hindi_is_the_default_and_four_languages_are_supported():
    assert DEFAULT == "hi-IN"
    assert set(SUPPORTED) == {"hi-IN", "en-IN", "ta-IN", "kn-IN"}


def test_each_language_has_its_own_bulbul_v3_speaker():
    speakers = [lang.speaker for lang in SUPPORTED.values()]
    assert len(set(speakers)) == 4 and set(speakers) <= BULBUL_V3_SPEAKERS
    assert SUPPORTED["hi-IN"].speaker == "anand"  # the upstream default voice


def test_tts_speaker_overrides_only_the_configured_language():
    table = configure("en-IN", tts_speaker="shubh")
    assert table.default.code == "en-IN" and table["en-IN"].speaker == "shubh"
    assert table["hi-IN"].speaker == SUPPORTED["hi-IN"].speaker


@pytest.mark.parametrize(("language", "speaker"), [("mr-IN", ""), ("hi-IN", "Anand"), ("hi-IN", "nobody")])
def test_unsupported_language_or_speaker_is_refused_at_startup(language, speaker):
    with pytest.raises(ValueError):
        configure(language, tts_speaker=speaker)


@pytest.mark.parametrize(("said", "code"), [
    ("English please", "en-IN"), ("इंग्लिश में बोलिए", "en-IN"), ("तमिल", "ta-IN"), ("தமிழ்", "ta-IN"),
    ("ಕನ್ನಡದಲ್ಲಿ", "kn-IN"), ("Kannada", "kn-IN"), ("हिंदी में", "hi-IN"), ("Hindi", "hi-IN"),
])
def test_a_caller_switches_language_by_naming_it(said, code):
    assert detect_switch(said) == code


@pytest.mark.parametrize("said", [
    "give Priya from the Tamil Nadu office the same access as Rahul",  # a request that mentions a language
    "what happened to my request", "",
])
def test_ordinary_sentences_do_not_switch_language(said):
    assert detect_switch(said) is None


def test_every_language_has_every_line():
    keys = {code: set(lang.lines) for code, lang in SUPPORTED.items()}
    assert len({frozenset(k) for k in keys.values()}) == 1, keys
    assert all(text.strip() for lang in SUPPORTED.values() for text in lang.lines.values())


async def test_stt_and_tts_use_the_call_language_and_its_speaker():
    sarvam = FakeSarvam(["வணக்கம்"])
    s = agent.CallSession(FakeWS(), sarvam_transport=sarvam.transport(), lang=SUPPORTED["ta-IN"])
    assert await s._stt(b"\xff" * 1600) == "வணக்கம்"
    form = sarvam.stt[0].content.decode("latin-1")
    assert 'name="language_code"\r\n\r\nta-IN' in form and 'name="model"\r\n\r\nsaaras:v3' in form
    assert sarvam.stt[0].headers["api-subscription-key"] == agent.SARVAM_API_KEY
    assert await s._tts("வணக்கம்")
    body = sarvam.tts[0]
    assert (body["target_language_code"], body["speaker"], body["model"]) == ("ta-IN", "kavitha", "bulbul:v3")
    assert body["speech_sample_rate"] == 8000
    assert "enable_preprocessing" not in body  # not a bulbul:v3 parameter (sarvam-ai-cookbook TTS tutorial)


async def test_naming_a_language_switches_listening_and_speaking():
    sarvam = FakeSarvam(["English please"])
    s = agent.CallSession(FakeWS(), sarvam_transport=sarvam.transport())
    assert s.lang.code == "hi-IN"
    await s._process(b"\xff" * 1600)
    assert s.lang.code == "en-IN"
    assert sarvam.tts[-1]["target_language_code"] == "en-IN"
    assert sarvam.spoken()[-1] == languages.SUPPORTED["en-IN"].lines["switched"]

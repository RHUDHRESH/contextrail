"""A signed caller can leave the AI stream for a configured human operator."""

import pytest

from dialogue import Dialogue
from languages import configure
from llm import Conversation
from tests.test_caller_id import DANA_RAW, PUBLIC, World, signed

OPERATOR = "+919999888777"


async def test_human_request_without_a_configured_number_is_honest():
    d = Dialogue(languages=configure("en-IN"), llm=Conversation(None))
    turn = await d.on_utterance("human operator")
    assert turn.say == [d.line("human_unavailable")]
    assert turn.control is None


async def test_signed_human_transfer_dials_operator_and_failed_dial_resumes():
    w = World(transfer_number=OPERATOR)
    _, dialogue = w.opening(DANA_RAW)
    turn = await dialogue.on_utterance("human operator")
    assert turn.say == [dialogue.line("transferring")]
    assert turn.control == "transfer"
    xml = w.client.post("/next", data={"CallUUID": "call-1"}, headers=signed("/next"))
    assert xml.status_code == 200
    assert f'<Dial timeout="30" action="{PUBLIC}/transfer-result" method="POST">' in xml.text
    assert f"<Number>{OPERATOR}</Number>" in xml.text
    assert w.client.post("/transfer-result", data={"CallUUID": "call-1", "DialStatus": "busy"}).status_code == 403
    result = w.client.post("/transfer-result", data={"CallUUID": "call-1", "DialStatus": "busy"},
                           headers=signed("/transfer-result"))
    assert result.status_code == 200 and "<Stream" in result.text
    assert (await dialogue.opening()).say == [dialogue.line("transfer_failed")]
    assert (await dialogue.opening()).say[0].startswith(dialogue.line("disclosure"))


async def test_completed_transfer_and_unknown_call_hang_up():
    w = World(transfer_number=OPERATOR)
    w.answer(DANA_RAW)
    done = w.client.post("/transfer-result", data={"CallUUID": "call-1", "DialStatus": "completed"},
                         headers=signed("/transfer-result"))
    unknown = w.client.post("/transfer-result", data={"CallUUID": "missing", "DialStatus": "failed"},
                            headers=signed("/transfer-result"))
    assert "<Hangup/>" in done.text and "<Hangup/>" in unknown.text


def test_invalid_transfer_number_is_rejected_at_startup():
    with pytest.raises(ValueError, match="E.164"):
        World(transfer_number="12345")

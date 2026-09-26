"""The voice door's HTTP face: Vobiz answer and status callbacks, and the media WebSocket (port 8100).

Adapted from vobiz-ai/Vobiz-Sarvam@ad44f49 server.py (MIT; see NOTICE). Changes from upstream:
- create_app() builds the app from explicit dependencies, so tests run it offline with fakes;
- every Vobiz callback must carry a valid Vobiz URL signature and fresh nonce when VOBIZ_AUTH_TOKEN is set;
  Vobiz does not sign form fields, so caller identity and phone decisions remain untrusted;
- the answer callback registers the call and hands Vobiz a per-call, unguessable WebSocket URL; the caller's
  number never appears in XML, URLs or logs (CLAUDE.md §16);
- the public URL comes from configuration (Caddy serves /voice/* here with the prefix stripped); the ngrok tunnel
  is gone;
- the stream-status callback reads Event and StreamID, the fields Vobiz actually posts (upstream README).
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import Response

import agent
from calls import CallRegistry, normalize_phone
from dialogue import Dialogue
from engine_client import EngineClient, EngineError
from languages import LanguageTable
from llm import Conversation
from vobiz import NonceCache, dial_xml, gather_xml, hangup_xml, signature_valid, stream_xml

# Load the .env sitting next to this file, whatever the working directory is.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

HTTP_PORT = int(os.getenv("HTTP_PORT", "8100"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sarvam_server")


def public_url_from_env() -> str:
    """VOICE_PUBLIC_URL, else the deployment's PUBLIC_URL + /voice (the Caddy route)."""
    explicit = os.getenv("VOICE_PUBLIC_URL", "").rstrip("/")
    return explicit or (os.getenv("PUBLIC_URL", "").rstrip("/") + "/voice")


def create_app(*, public_url: str, vobiz_auth_token: str, engine: EngineClient, languages: LanguageTable,
               llm: Conversation, sarvam_transport=None, transfer_number: str = "") -> FastAPI:
    app = FastAPI()
    calls = app.state.calls = CallRegistry()
    signed = bool(vobiz_auth_token)
    nonces = NonceCache()
    if transfer_number and normalize_phone(transfer_number) != transfer_number:
        raise ValueError("HUMAN_TRANSFER_NUMBER must be an E.164 number")
    # Transfer can incur call charges. URL-only signatures do not authenticate CallUUID or From.
    transfer_number = ""  # enable only after provider-side call identity verification exists
    ws_base = public_url.replace("https://", "wss://").replace("http://", "ws://")

    async def vobiz_form(request: Request) -> dict:
        form = await request.form()
        if signed and (not signature_valid(f"{public_url}{request.url.path}", request.headers, vobiz_auth_token)
                       or not nonces.accept(request.headers)):
            logger.warning(f"Refused an unsigned, forged, or replayed Vobiz callback to {request.url.path}")
            raise HTTPException(403, "invalid Vobiz signature")
        return dict(form)

    async def resolve(phone: str | None):
        if phone is None:
            return None
        try:
            return await engine.resolve_caller(phone)
        except EngineError as e:  # fail closed: an unreachable engine makes the caller unknown, not trusted
            logger.warning(f"Caller lookup failed ({e.status}); treating the caller as unknown")
            return None

    @app.post("/answer")
    async def answer(request: Request):
        form = await vobiz_form(request)
        if not form.get("CallUUID"):
            raise HTTPException(400, "CallUUID is required")
        # Vobiz signs URL + nonce, not POST fields. From can be changed in transit while the signature stays valid.
        # Until CallUUID/From can be confirmed through a provider-side call lookup, fail closed for identity.
        caller = None
        call = calls.register(form.get("CallUUID", ""), caller)
        logger.info(f"Answering call {call.call_uuid} (caller id not trusted)")
        xml = stream_xml(f"{ws_base}/ws/{call.token}", f"{public_url}/stream-status",
                         f"{public_url}/next")
        return Response(content=xml, media_type="application/xml")

    @app.post("/next")
    async def next_step(request: Request):
        form = await vobiz_form(request)
        call = calls.get(form.get("CallUUID", ""))
        step = call.dialogue.take_next_step() if call and call.dialogue else None
        if step == "gather_dtmf":
            xml = gather_xml(f"{public_url}/dtmf")
        elif step == "transfer" and transfer_number:
            xml = dial_xml(transfer_number, f"{public_url}/transfer-result")
        else:
            xml = hangup_xml()
        return Response(content=xml, media_type="application/xml")

    @app.post("/transfer-result")
    async def transfer_result(request: Request):
        form = await vobiz_form(request)
        call = calls.get(form.get("CallUUID", ""))
        if call is None or call.dialogue is None or form.get("DialStatus") == "completed":
            return Response(content=hangup_xml(), media_type="application/xml")
        call.dialogue._resume = [call.dialogue.line("transfer_failed")]
        return Response(content=stream_xml(f"{ws_base}/ws/{call.token}", f"{public_url}/stream-status",
                                           f"{public_url}/next"), media_type="application/xml")

    @app.post("/dtmf")
    async def dtmf(request: Request):
        form = await vobiz_form(request)
        call = calls.get(form.get("CallUUID", ""))
        if call is None or call.dialogue is None:
            return Response(content=hangup_xml(), media_type="application/xml")
        # Digits and InputType are not covered by Vobiz's URL + nonce signature. Never dispatch a live
        # approval decision from a form field that could be changed after the callback was signed.
        digits = ""
        await call.dialogue.on_dtmf(digits)
        return Response(content=stream_xml(f"{ws_base}/ws/{call.token}", f"{public_url}/stream-status",
                                           f"{public_url}/next"), media_type="application/xml")

    @app.websocket("/ws/{token}")
    async def ws_endpoint(websocket: WebSocket, token: str):
        call = calls.by_token(token)
        if call is None:
            await websocket.close(code=1008)  # no live call behind this URL
            return
        await websocket.accept()
        logger.info(f"Call {call.call_uuid} connected to AI agent")
        if call.dialogue is None:
            person = await resolve(call.caller)
            call.dialogue = Dialogue(languages=languages, llm=llm, caller=person,
                                     caller_phone=call.caller if person else None, engine=engine,
                                     call_ref=call.call_uuid, transfer_available=bool(transfer_number))
        session = agent.CallSession(websocket, dialogue=call.dialogue, sarvam_transport=sarvam_transport)
        try:
            async for message in websocket.iter_text():
                await session.handle_message(message)
        except Exception as e:  # noqa: BLE001 - a broken socket ends this stream, never the service
            logger.error(f"WebSocket error: {e}")

    @app.post("/stream-status")
    async def stream_status(request: Request):
        form = await vobiz_form(request)
        logger.info(f"Stream event — UUID={form.get('CallUUID', '?')}, event={form.get('Event', '?')}, "
                    f"stream={form.get('StreamID', '?')}")
        return Response(status_code=200)

    @app.post("/hangup")
    async def hangup(request: Request):
        form = await vobiz_form(request)
        calls.drop(form.get("CallUUID", ""))
        logger.info(f"Hangup — UUID={form.get('CallUUID', '?')}")
        return Response(status_code=200)

    @app.get("/health")
    async def health():
        return {"status": "ok", "base_url": public_url,
                "modes": {"vobiz_callbacks": "LIVE" if signed else "FIXTURE",
                          "sarvam": "LIVE" if agent.SARVAM_API_KEY else "FIXTURE", "llm": llm.mode,
                          "engine": "configured" if engine.configured else "unconfigured",
                          "caller_identity": "UNVERIFIED", "phone_approvals": "DISABLED",
                          "human_transfer": "configured" if transfer_number else "unavailable"}}

    return app


def create_app_from_env() -> FastAPI:
    return create_app(
        public_url=public_url_from_env(), vobiz_auth_token=os.getenv("VOBIZ_AUTH_TOKEN", ""),
        engine=EngineClient(os.getenv("ENGINE_URL", "http://localhost:8000"), os.getenv("ENGINE_TOKEN", "")),
        languages=agent.LANGUAGES, llm=Conversation.from_key(agent.ANTHROPIC_KEY),
        transfer_number=os.getenv("HUMAN_TRANSFER_NUMBER", ""))


app = create_app_from_env()


def main():
    logger.info("=" * 60)
    logger.info("  ContextRail voice door (Vobiz x Sarvam)")
    logger.info(f"  Answer URL : {public_url_from_env()}/answer")
    logger.info(f"  Hangup URL : {public_url_from_env()}/hangup")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()

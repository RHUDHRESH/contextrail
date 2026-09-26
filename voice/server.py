import os
import logging

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from dotenv import load_dotenv
from pyngrok import ngrok, conf

from agent import CallSession

# Load the .env sitting next to this file, whatever the working directory is.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

HTTP_PORT        = int(os.getenv("HTTP_PORT", "8000"))
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
PUBLIC_URL       = os.getenv("PUBLIC_URL", "").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sarvam_server")

app      = FastAPI()
BASE_URL = ""


def setup_ngrok() -> str:
    if NGROK_AUTH_TOKEN:
        conf.get_default().auth_token = NGROK_AUTH_TOKEN
    try:
        tunnel = ngrok.connect(HTTP_PORT, "http", pooling_enabled=True)
    except Exception:
        tunnel = ngrok.connect(HTTP_PORT, "http")
    url = tunnel.public_url.replace("http://", "https://")
    logger.info(f"ngrok tunnel: {url}")
    return url


@app.post("/answer")
async def answer(request: Request):
    ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true"
            contentType="audio/x-mulaw;rate=8000"
            statusCallbackUrl="{BASE_URL}/stream-status"
            statusCallbackMethod="POST">
        {ws_url}
    </Stream>
    <Hangup/>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Call connected to AI agent")
    session = CallSession(websocket)
    try:
        async for message in websocket.iter_text():
            await session.handle_message(message)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


@app.post("/stream-status")
async def stream_status(request: Request):
    form = await request.form()
    logger.info(f"Stream ended — UUID={form.get('CallUUID','?')}, status={form.get('StreamStatus','?')}")
    return Response(status_code=200)


@app.post("/hangup")
async def hangup(request: Request):
    form = await request.form()
    logger.info(f"Hangup — UUID={form.get('CallUUID','?')}")
    return Response(status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "base_url": BASE_URL}


def main():
    global BASE_URL
    BASE_URL = PUBLIC_URL if PUBLIC_URL else setup_ngrok()
    logger.info("=" * 60)
    logger.info("  Sarvam AI Agent")
    logger.info(f"  Answer URL : {BASE_URL}/answer")
    logger.info(f"  Hangup URL : {BASE_URL}/hangup")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()

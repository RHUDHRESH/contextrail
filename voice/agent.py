"""
agent.py — Sarvam Saaras v3 STT + OpenAI LLM + Sarvam Bulbul v3 TTS
=====================================================================
Pipeline:
  Vobiz audio (mu-law 8kHz)
    → silence-based VAD
    → Sarvam Saaras v3  (STT)
    → OpenAI GPT-4o-mini (LLM)
    → Sarvam Bulbul v3   (TTS)
    → Vobiz audio (mu-law 8kHz)
"""

import os
import io
import json
import base64
import wave
import audioop
import asyncio
import logging

import httpx
import websockets
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load the .env sitting next to this file, whatever the working directory is.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SYSTEM_PROMPT  = os.getenv("AGENT_SYSTEM_PROMPT", "You are a helpful voice assistant. Keep responses short and conversational.")
WS_PORT        = int(os.getenv("AGENT_WS_PORT", "8001"))
LANGUAGE       = os.getenv("AGENT_LANGUAGE", "hi-IN")   # hi-IN, en-IN, ta-IN, etc.
TTS_SPEAKER    = os.getenv("TTS_SPEAKER", "anand")       # anand, priya, ritu, etc.

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# VAD (Voice Activity Detection) tuning
SILENCE_THRESHOLD  = 200   # RMS below this = silence
SILENCE_FRAMES     = 40    # 40 × 20ms = 800ms silence → trigger STT
MIN_SPEECH_FRAMES  = 8     # ignore clips shorter than 160ms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sarvam_agent")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


# =============================================================================
# CallSession — per-call state machine
# =============================================================================

class CallSession:
    def __init__(self, ws):
        self.ws          = ws
        self.stream_id   = None
        self.call_id     = None
        self.is_playing  = False
        self.conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

        # VAD state
        self._audio_buf    = bytearray()
        self._silence_cnt  = 0
        self._speech_cnt   = 0
        self._is_speaking  = False
        self._processing   = False

    # ── WebSocket send helper ─────────────────────────────────────────────────

    async def _send(self, data: str):
        if hasattr(self.ws, "send_text"):
            await self.ws.send_text(data)   # FastAPI / Starlette
        else:
            await self.ws.send(data)        # websockets library

    # ── Vobiz event router ────────────────────────────────────────────────────

    async def handle_message(self, message: str):
        try:
            data  = json.loads(message)
            event = data.get("event")

            if event == "start":
                start = data.get("start", {})
                self.stream_id = data.get("streamId")
                self.call_id   = (data.get("callId")
                                  or start.get("callId")
                                  or start.get("callUUID"))
                logger.info(f"Stream started — id={self.stream_id}, call={self.call_id}")
                await self._speak("नमस्ते! मैं आपकी कैसे मदद कर सकता हूं?")

            elif event == "media":
                if not self._processing:
                    payload = data.get("media", {}).get("payload", "")
                    if payload:
                        await self._handle_audio(base64.b64decode(payload))

            elif event == "playedStream":
                self.is_playing = False
                logger.info("Playback complete")

            elif event == "clearedAudio":
                self.is_playing = False

            elif event == "stop":
                logger.info("Stream stopped")

        except Exception as e:
            logger.error(f"handle_message error: {e}")

    # ── VAD — silence-based speech segmentation ───────────────────────────────

    async def _handle_audio(self, mulaw_chunk: bytes):
        pcm = audioop.ulaw2lin(mulaw_chunk, 2)
        rms = audioop.rms(pcm, 2)

        if rms > SILENCE_THRESHOLD:
            self._is_speaking = True
            self._speech_cnt += 1
            self._silence_cnt  = 0
            self._audio_buf.extend(mulaw_chunk)
        elif self._is_speaking:
            self._silence_cnt += 1
            self._audio_buf.extend(mulaw_chunk)

            if self._silence_cnt >= SILENCE_FRAMES and self._speech_cnt >= MIN_SPEECH_FRAMES:
                audio = bytes(self._audio_buf)
                self._reset_vad()
                self._processing = True
                asyncio.create_task(self._process(audio))

    def _reset_vad(self):
        self._audio_buf.clear()
        self._is_speaking = False
        self._silence_cnt  = 0
        self._speech_cnt   = 0

    # ── Main pipeline: STT → LLM → TTS ───────────────────────────────────────

    async def _process(self, mulaw_audio: bytes):
        try:
            if self.is_playing:
                await self._clear_audio()

            transcript = await self._stt(mulaw_audio)
            if not transcript:
                logger.info("STT returned empty transcript, skipping")
                return
            logger.info(f"STT: {transcript}")

            self.conversation.append({"role": "user", "content": transcript})
            reply = await self._llm()
            logger.info(f"LLM: {reply}")
            self.conversation.append({"role": "assistant", "content": reply})

            await self._speak(reply)

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
        finally:
            self._processing = False

    # ── Sarvam Saaras v3 STT ─────────────────────────────────────────────────

    async def _stt(self, mulaw_data: bytes) -> str:
        wav = self._mulaw_to_wav(mulaw_data)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    SARVAM_STT_URL,
                    headers={"api-subscription-key": SARVAM_API_KEY},
                    files={"file": ("audio.wav", wav, "audio/wav")},
                    data={"model": "saaras:v3", "language_code": LANGUAGE, "mode": "transcribe"},
                )
            if resp.status_code == 200:
                return resp.json().get("transcript", "").strip()
            logger.warning(f"Sarvam STT {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"STT request error: {e}")
        return ""

    # ── OpenAI GPT-4o-mini LLM ───────────────────────────────────────────────

    async def _llm(self) -> str:
        try:
            resp = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=self.conversation,
                max_tokens=150,
                temperature=0.7,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return "माफ करें, मुझे समझने में परेशानी हो रही है।"

    # ── Sarvam Bulbul v3 TTS ─────────────────────────────────────────────────

    async def _tts(self, text: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    SARVAM_TTS_URL,
                    headers={
                        "api-subscription-key": SARVAM_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "target_language_code": LANGUAGE,
                        "model": "bulbul:v3",
                        "speaker": TTS_SPEAKER,
                        "speech_sample_rate": 8000,
                        "enable_preprocessing": True,
                    },
                )
            if resp.status_code == 200:
                audios = resp.json().get("audios", [])
                if audios:
                    return self._wav_to_mulaw(base64.b64decode(audios[0]))
            logger.warning(f"Sarvam TTS {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"TTS request error: {e}")
        return b""

    # ── Playback helpers ──────────────────────────────────────────────────────

    async def _speak(self, text: str):
        mulaw = await self._tts(text)
        if mulaw:
            await self._play_audio(mulaw)

    async def _play_audio(self, mulaw_data: bytes):
        self.is_playing = True
        try:
            for i in range(0, len(mulaw_data), 160):
                chunk   = mulaw_data[i:i + 160]
                payload = base64.b64encode(chunk).decode()
                await self._send(json.dumps({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": payload,
                    },
                }))
            if self.stream_id:
                await self._send(json.dumps({
                    "event": "checkpoint",
                    "streamId": self.stream_id,
                    "name": f"tts-{len(self.conversation)}",
                }))
        except Exception as e:
            logger.error(f"Play audio error: {e}")
            self.is_playing = False

    async def _clear_audio(self):
        if self.stream_id:
            await self._send(json.dumps({
                "event": "clearAudio",
                "streamId": self.stream_id,
            }))
        self.is_playing = False
        logger.info("Barge-in: cleared audio")

    # ── Audio conversion helpers ──────────────────────────────────────────────

    def _mulaw_to_wav(self, mulaw_data: bytes) -> bytes:
        pcm = audioop.ulaw2lin(mulaw_data, 2)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(pcm)
        return buf.getvalue()

    def _wav_to_mulaw(self, wav_bytes: bytes) -> bytes:
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
            sr  = wf.getframerate()
            sw  = wf.getsampwidth()
        if sw == 1:
            pcm = audioop.lin2lin(pcm, 1, 2)
        if sr != 8000:
            pcm, _ = audioop.ratecv(pcm, 2, 1, sr, 8000, None)
        return audioop.lin2ulaw(pcm, 2)


# =============================================================================
# WebSocket server
# =============================================================================

async def handle_connection(websocket, path=None):
    logger.info("New call connected")
    session = CallSession(websocket)
    try:
        async for message in websocket:
            await session.handle_message(message)
    except websockets.exceptions.ConnectionClosed:
        logger.info("Call disconnected")
    except Exception as e:
        logger.error(f"Connection error: {e}")


async def start_agent_server():
    server = await websockets.serve(
        handle_connection,
        "0.0.0.0",
        WS_PORT,
        ping_interval=20,
        ping_timeout=20,
    )
    logger.info(f"Agent WebSocket server running on ws://0.0.0.0:{WS_PORT}")
    return server


if __name__ == "__main__":
    async def main():
        await start_agent_server()
        await asyncio.Future()

    asyncio.run(main())

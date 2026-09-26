"""An offline Sarvam: records STT/TTS requests and answers with a transcript or an 8 kHz WAV of silence."""

from __future__ import annotations

import base64
import io
import json
import wave

import httpx


def wav_8k(ms: int = 100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * (8 * ms))
    return buf.getvalue()


class FakeSarvam:
    def __init__(self, transcripts: list[str] | None = None) -> None:
        self.transcripts = list(transcripts or [])
        self.stt: list[httpx.Request] = []
        self.tts: list[dict] = []
        self.tts_headers: list[httpx.Headers] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/speech-to-text":
            self.stt.append(request)
            text = self.transcripts.pop(0) if self.transcripts else ""
            return httpx.Response(200, json={"request_id": "r", "transcript": text, "language_code": None})
        if request.url.path == "/text-to-speech":
            self.tts.append(json.loads(request.content))
            self.tts_headers.append(request.headers)
            return httpx.Response(200, json={"request_id": "r", "audios": [base64.b64encode(wav_8k()).decode()]})
        return httpx.Response(404)

    def spoken(self) -> list[str]:
        return [t["text"] for t in self.tts]

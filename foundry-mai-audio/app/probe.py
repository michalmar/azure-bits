"""Synthetic deployment probe; no reader audio or transcript is involved."""

import asyncio

from fastapi import HTTPException

from audio import PREFIX


class StreamingProbe:
    def __init__(self, pcm: bytes):
        if not pcm or len(pcm) % 2 or len(pcm) > 16_000 * 2 * 20:
            raise HTTPException(502, "Deployment probe requires 1-20 seconds of valid PCM16 audio")
        self.pcm = pcm
        self.offset = 0
        self.events = []

    async def receive(self):
        if self.offset >= len(self.pcm):
            return {"type": "websocket.receive", "text": "stop"}
        chunk = self.pcm[self.offset:self.offset + 640]
        self.offset += len(chunk)
        await asyncio.sleep(len(chunk) / 32_000)
        return {"type": "websocket.receive", "bytes": chunk}

    async def send_json(self, event):
        self.events.append(event)

    def result(self):
        finals = [event.get("transcript", "") for event in self.events if event["type"] == PREFIX + "completed"]
        if not any(text.strip() for text in finals) or not self.events or self.events[-1]["type"] != "done":
            raise HTTPException(502, "Deployment probe did not produce a nonempty final transcript")
        return {
            "transcript": " ".join(finals),
            "audio_seconds": len(self.pcm) / 32_000,
            "event_types": sorted({event["type"] for event in self.events}),
            "first_text_ms": next((event["first_text_ms"] for event in self.events if "first_text_ms" in event), None),
        }

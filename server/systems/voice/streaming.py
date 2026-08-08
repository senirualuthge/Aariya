import asyncio

class VoiceStreamer:
    def __init__(self, websocket):
        self.ws = websocket

    async def stream_text(self, text_generator):
        """
        Streams LLM tokens as they arrive over the provided websocket.
        Collects the chunks to return the full merged string at the end.
        """
        full_text = ""
        async for chunk in text_generator:
            if chunk:
                full_text += chunk
                await self.ws.send_json({
                    "type": "text.stream",
                    "chunk": chunk
                })
        return full_text

    async def stream_audio(self, tts_chunks):
        """
        Streams audio chunks (base64).
        For future compatibility when real-time TTS is wired up.
        """
        for chunk in tts_chunks:
            await self.ws.send_json({
                "type": "audio.stream",
                "data": chunk
            })
            await asyncio.sleep(0.02)

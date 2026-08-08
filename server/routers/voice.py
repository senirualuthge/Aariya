from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from server.systems.voice.vad import VADSystem
from server.systems.voice.asr import ASRSystem
from server.systems.voice.tts import TTSSystem
import base64
import json
import asyncio

from server.systems.voice.voice_manager import VoiceManager

router = APIRouter()

@router.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[VOICE] Client connected (Authoritative Mode)")

    manager = VoiceManager(websocket)
    
    try:
        while True:
            # Receive text data (JSON) as per schema
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["type"] == "audio.chunk":
                # Decode base64 PCM data
                try:
                    pcm_bytes = base64.b64decode(message["data"])
                    await manager.handle_audio_chunk(pcm_bytes)
                except Exception as e:
                    print(f"[VOICE] Error decoding chunk: {e}")
                    
            elif message["type"] == "voice.ping":
                await websocket.send_json({"type": "voice.pong"})

    except WebSocketDisconnect:
        print("[VOICE] Client disconnected")
    except Exception as e:
        print(f"[VOICE] Unified Voice Error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": "Internal voice processing error"})
        except:
            pass

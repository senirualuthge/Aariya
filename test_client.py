import asyncio
import websockets
import json
import time

async def test_brain():
    uri = "ws://localhost:8000/ws/brain"
    
    print(f"[*] Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("[OK] Connected!\n")
            
            # Test 1: Lifecycle Ping
            print("[TEST 1] Lifecycle Ping")
            await websocket.send(json.dumps({"lifecycle": "ping", "timestamp": int(time.time())}))
            response = await websocket.recv()
            print(f"   Response: {response}\n")

            # Test 2: Connection Lifecycle
            print("[TEST 2] Connection Event")
            payload = {
                "type": "input.multimodal",
                "timestamp": int(time.time()),
                "lifecycle": "connect"
            }
            await websocket.send(json.dumps(payload))
            response = await websocket.recv()
            data = json.loads(response)
            print(f"   Personality: {data['brain_state']['personality']}")
            print(f"   Memories: {data['meta']['recent_memories']}\n")

            # Test 3: Text Input (NEW)
            print("[TEST 3] Text Input")
            text_payload = {
                "type": "input.multimodal",
                "timestamp": int(time.time()),
                "text": "Hello Python Brain! How are you today?",
                "lifecycle": "update"
            }
            
            print(f"   Sending: '{text_payload['text']}'")
            await websocket.send(json.dumps(text_payload))
            
            response = await websocket.recv()
            data = json.loads(response)
            print(f"   [AI] Response: {data.get('response_text', 'No response')}")
            print(f"   Session ID: {data['meta']['session_id']}")
            print(f"   Text Received: {data['meta']['received_text']}\n")

            # Test 4: Vision Data with Emotion
            print("[TEST 4] Multimodal Input (Vision + Emotion)")
            vision_payload = {
                "type": "input.multimodal",
                "timestamp": int(time.time()),
                "vision": {
                    "face_detected": True,
                    "emotion": {"happy": 0.8, "surprised": 0.2},
                    "face_valence": 0.8,
                    "face_arousal": 0.6,
                    "voice_valence": 0.7,
                    "voice_arousal": 0.5,
                    "text_sentiment": 0.9,
                    "face_confidence": 0.95,
                    "voice_confidence": 0.88,
                    "text_confidence": 0.99
                },
                "text": "I'm feeling great today! Everything is awesome.",
                "lifecycle": "update"
            }
            
            await websocket.send(json.dumps(vision_payload))
            response = await websocket.recv()
            data = json.loads(response)
            print(f"   [AI] Response: {data.get('response_text', 'No response')}")
            print(f"   Vision Detected: {data['meta']['received_vision']}")
            print(f"   Thought: {data['brain_state']['thought_process']}\n")
            
            # Keep connection open briefly
            await asyncio.sleep(1)
            print("[OK] All tests completed successfully!")

    except ConnectionRefusedError:
        print("[ERROR] Connection failed: Is the server running?")
        print("   Run: uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload")
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_brain())

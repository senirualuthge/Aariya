import asyncio
import websockets

async def test():
    try:
        async with websockets.connect('ws://127.0.0.1:8000/ws/brain_metrics') as websocket:
            print("Connected!")
            await websocket.send('{"type":"ping"}')
            print(f"Received: {await websocket.recv()}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())

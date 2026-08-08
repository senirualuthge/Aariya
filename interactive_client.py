import asyncio
import websockets
import json
import time
import sys
import threading
from queue import Queue

# Configuration
SERVER_URI = "ws://localhost:8000/ws/brain"
USER_ID = "cli_user"

# Color codes for terminal
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GRAY = '\033[90m'

async def receive_messages(websocket, stop_event):
    """Listens for incoming messages from the server."""
    try:
        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                data = json.loads(message)
                
                if data.get("type") == "state.update":
                    brain = data.get("brain_state", {})
                    response_text = data.get("response_text")
                    
                    # Display response text if present
                    if response_text:
                        print(f"\r{Colors.OKCYAN}🤖 AI Brain:{Colors.ENDC} {response_text}")
                    
                    # Display personality state
                    personality = brain.get("personality", {})
                    if personality:
                        print(f"{Colors.GRAY}   Personality → Warmth: {personality.get('warmth', 0):.2f} | "
                              f"Energy: {personality.get('energy', 0):.2f} | "
                              f"Assertiveness: {personality.get('assertiveness', 0):.2f}{Colors.ENDC}")
                    
                    # Display session info
                    meta = data.get("meta", {})
                    if "session_id" in meta:
                        session_id_short = meta["session_id"][:8]
                        print(f"{Colors.GRAY}   Session: {session_id_short}... | "
                              f"Memories: {meta.get('recent_memories', 0)}{Colors.ENDC}")
                    
                    print(f"\n{Colors.WARNING}You:{Colors.ENDC} ", end="", flush=True)
                    
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                print(f"\n{Colors.FAIL}✗ Disconnected from server{Colors.ENDC}")
                stop_event.set()
                break
    except Exception as e:
        if not stop_event.is_set():
            print(f"\n{Colors.FAIL}Error receiving: {e}{Colors.ENDC}")

async def send_messages(websocket, input_queue, stop_event):
    """Sends messages from the input queue to the server."""
    # Send initial connection
    await websocket.send(json.dumps({
        "type": "input.multimodal",
        "timestamp": int(time.time()),
        "lifecycle": "connect"
    }))
    
    while not stop_event.is_set():
        if not input_queue.empty():
            user_text = input_queue.get()
            if user_text.lower() in ["exit", "quit", "bye"]:
                print(f"{Colors.OKGREEN}Goodbye! 👋{Colors.ENDC}")
                stop_event.set()
                break
                
            payload = {
                "type": "input.multimodal",
                "timestamp": int(time.time()),
                "text": user_text,
                "lifecycle": "update"
            }
            await websocket.send(json.dumps(payload))
        await asyncio.sleep(0.1)

def input_thread(input_queue, stop_event):
    """Reads user input in a separate thread."""
    print(f"{Colors.WARNING}You:{Colors.ENDC} ", end="", flush=True)
    while not stop_event.is_set():
        try:
            user_input = sys.stdin.readline()
            if user_input:
                input_queue.put(user_input.strip())
            else:
                break
        except EOFError:
            stop_event.set()
            break

async def main():
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("╔═══════════════════════════════════════════╗")
    print("║   AI Girl - Python Brain CLI Interface   ║")
    print("╚═══════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")
    print(f"{Colors.GRAY}Connecting to {SERVER_URI}...{Colors.ENDC}\n")
    
    try:
        async with websockets.connect(SERVER_URI) as websocket:
            print(f"{Colors.OKGREEN}✓ Connected to Python Brain!{Colors.ENDC}")
            print(f"{Colors.GRAY}Type 'exit' to quit{Colors.ENDC}\n")

            stop_event = asyncio.Event()
            input_queue = Queue()
            
            # Start Input Thread (daemonic so it dies with script)
            t = threading.Thread(target=input_thread, args=(input_queue, stop_event))
            t.daemon = True
            t.start()

            # Run Send/Receive Loops
            await asyncio.gather(
                receive_messages(websocket, stop_event),
                send_messages(websocket, input_queue, stop_event)
            )
            
    except ConnectionRefusedError:
        print(f"{Colors.FAIL}✗ Could not connect. Is the server running?{Colors.ENDC}")
        print(f"{Colors.GRAY}Run: uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}✗ Error: {e}{Colors.ENDC}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.OKGREEN}Goodbye! 👋{Colors.ENDC}")

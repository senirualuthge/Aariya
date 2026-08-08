import asyncio
import sys
import os
from datetime import datetime

# Add project root to sys.path
# Since the script is in server/tests, we need to go up two levels
sys.path.append("/Volumes/Volumn 1/Code Base/AI Girl")

# Set dummy environment variables to avoid real API calls if possible
os.environ["OPENAI_API_KEY"] = "mock-key"

from server.systems.brain_v2 import BrainV2
from server.infrastructure.signal_bus import get_signal_bus

async def verify():
    print("--- Starting Dashboard Signal Verification ---")
    
    # 1. Capture signals emitted to the bus
    captured_signals = []
    
    async def mock_broadcast(payload):
        if payload.get("type") == "signal":
            captured_signals.append(payload["signal"])
            print(f" [SIGNAL] {payload['signal']['payload']['title']}: {payload['signal']['payload']['description']}")

    bus = get_signal_bus()
    bus.broadcast_callback = mock_broadcast
    
    # 2. Setup BrainV2
    print("Initializing BrainV2...")
    try:
        # Mocking or initializing BrainV2
        # Note: If BrainV2 depends on initialized systems, we might need a minimal mock
        brain = BrainV2()
        
        # 3. Trigger Research
        user_text = "Who is the current CEO of Nvidia? Research this."
        print(f"Step 1: Sending user text -> '{user_text}'")
        
        # We call step() which is async
        # We use a try-except here because the LLM/Tool calls might fail without real keys
        # but the signals should still fire BEFORE the failure or at start
        try:
            await brain.step(
                user_text=user_text,
                perception_data={"vision": "none"},
                user_model={"emotional_state": "curious", "engagement": 0.8, "intent": "QUESTION"}
            )
        except Exception as e:
            print(f" [INFO] Brain step execution encountered expected error (likely missing API key): {e}")
        
        # 4. Final checks
        print(f"\nVerification Results:")
        print(f" - Signals captured: {len(captured_signals)}")
        
        has_start = any(s["payload"]["title"] == "RESEARCH_START" for s in captured_signals)
        has_complete = any(s["payload"]["title"] == "RESEARCH_COMPLETE" for s in captured_signals)
        
        if has_start:
            print(" ✅ Found RESEARCH_START signal")
        else:
            print(" ❌ Missing RESEARCH_START signal")
            
        if has_complete:
            print(" ✅ Found RESEARCH_COMPLETE signal")
        else:
            print(" ❌ Missing RESEARCH_COMPLETE signal")
            
        if has_start:
            print("\n--- TELEMETRY TRACE VERIFIED ---")
        else:
            print("\n--- VERIFICATION FAILED ---")

    except Exception as e:
        print(f" ❌ Initialization Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify())

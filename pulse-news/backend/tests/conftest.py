import os

os.environ.setdefault("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test-key")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

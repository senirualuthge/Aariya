import asyncio
import os
import json
from typing import List, Dict, Optional

from openai import OpenAI

# ── Configuration (reads .env, falls back to a local Ollama/LM-Studio) ─────────
# The brain's chat model is configured via env vars:
#   OPENAI_API_KEY    — API key (required for hosted models)
#   OPENAI_BASE_URL   — OpenAI-compatible base URL (proxy / gateway / Ollama)
#   OPENAI_MODEL      — preferred model name
#   LLM_MODEL         — fallback model name
#   LLM_API_KEY       — fallback API key
#   LLM_API_URL       — fallback base URL
#   LLM_BASE_URL      — older alias for the base URL
# If none are set we default to a local Ollama instance.
def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def resolve_llm_config() -> dict:
    base_url = (
        _env("OPENAI_BASE_URL")
        or _env("LLM_API_URL")
        or _env("LLM_BASE_URL")
        or "http://localhost:11434/v1"
    )
    api_key = _env("OPENAI_API_KEY") or _env("LLM_API_KEY") or "lm-studio"
    model = (
        _env("OPENAI_MODEL")
        or _env("LLM_MODEL")
        or "gpt-4o-mini"
    )
    return {"base_url": base_url, "api_key": api_key, "model": model}


class LLMEngine:
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        """
        Initialize LLM Engine.
        Resolves configuration from the environment when args are omitted.
        """
        cfg = resolve_llm_config()
        self.base_url = base_url or cfg["base_url"]
        self.api_key = api_key or cfg["api_key"]
        self.model = model or cfg["model"]
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        print(f"[LLM] Initialized with model: {self.model} at {self.base_url}")

    def chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 150) -> str:
        """
        Get a chat completion from the LLM.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] Error in chat_completion: {e}")
            return ""

    async def chat_completion_async(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 150) -> str:
        """
        Async wrapper around the (CPU/IO-bound) sync chat call. Runs the sync
        OpenAI call in an executor thread so the event loop is never blocked.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.chat_completion(messages=messages, temperature=temperature, max_tokens=max_tokens),
        )

    async def chat_completion_stream(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 150):
        """
        Stream a chat completion from the LLM as an async generator.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                await asyncio.sleep(0.01)  # Small yield to event loop
        except Exception as e:
            print(f"[LLM] Error in chat_completion_stream: {e}")
            yield ""

    async def stream_to_callback(self, messages: List[Dict[str, str]], on_token, temperature: float = 0.7, max_tokens: int = 150) -> str:
        """
        Stream a completion while accumulating the full text.
        `on_token` is an async callable receiving each token string.
        Returns the full assembled response (or "" on failure).
        """
        full = []
        async for token in self.chat_completion_stream(
            messages=messages, temperature=temperature, max_tokens=max_tokens
        ):
            full.append(token)
            if on_token:
                try:
                    await on_token(token)
                except Exception:
                    pass
        return "".join(full).strip()

    def analyze_sentiment(self, text: str) -> Dict[str, float]:
        """
        Analyzes sentiment of text using LLM.
        Returns: {'positivity': 0.0-1.0, 'energy': 0.0-1.0}
        """
        system_prompt = """
        Analyze the sentiment of the user's message.
        Return ONLY a JSON object with keys: 'positivity' (0.0 to 1.0) and 'energy' (0.0 to 1.0).
        """
        try:
            response = self.chat_completion([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ], temperature=0.1)

            # Clean response to ensure JSON
            json_str = response.replace("```json", "").replace("```", "").strip()
            return json.loads(json_str)
        except Exception:
            return {"positivity": 0.5, "energy": 0.5}


# ── Shared lazy singleton for the conversational brain ─────────────────────────
_llm_engine: Optional[LLMEngine] = None


def get_llm() -> LLMEngine:
    """Lazy singleton used by BrainV2 for the main dialogue generation."""
    global _llm_engine
    if _llm_engine is None:
        _llm_engine = LLMEngine()
    return _llm_engine


def set_llm(engine: Optional[LLMEngine]) -> None:
    """Override the singleton (used for tests)."""
    global _llm_engine
    _llm_engine = engine

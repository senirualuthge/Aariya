"""
Agentic Web Navigation (AccessFIles §69 — gap fill).

Beyond search: real browser control (navigate, fill forms, click, extract)
over pages that need JS or sessions. The engine is Playwright — and ONLY
Playwright actually installed on this machine. When it is not installed,
every method returns {"available": False, "reason": ...} instead of
pretending; there is no fake browsing anywhere in this module.

Safety rails:
  * http/https URLs only;
  * optional host allowlist via AARIYA_BROWSER_ALLOWED_HOSTS
    (comma-separated; unset → all hosts allowed, navigation still logged);
  * every action result is the REAL outcome of the step, including failures.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.web_agent")

_CAP_CACHE: Dict[str, Any] = {}


def detect_browser() -> Dict[str, Any]:
    """Truthful capability probe for the machine we're running on."""
    if "result" in _CAP_CACHE:
        return dict(_CAP_CACHE["result"])
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        result = {"available": True, "engine": "playwright"}
    except Exception as exc:
        result = {"available": False, "engine": None,
                  "reason": f"playwright not importable: {str(exc)[:120]}"}
    _CAP_CACHE["result"] = result
    return dict(result)


def allowed_hosts() -> List[str]:
    raw = os.getenv("AARIYA_BROWSER_ALLOWED_HOSTS", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def validate_url(url: str) -> str:
    """Scheme + optional host-allowlist check. Raises ValueError on refusal."""
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    allow = allowed_hosts()
    if allow and parsed.hostname.lower() not in allow:
        raise ValueError(
            f"host {parsed.hostname} not in AARIYA_BROWSER_ALLOWED_HOSTS")
    return parsed.geturl()


class WebAgent:
    """Real Playwright session wrapper. All methods are honest about failure."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw: Any = None
        self._browser: Any = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _ensure_browser(self) -> Any:
        cap = detect_browser()
        if not cap["available"]:
            raise RuntimeError(cap.get("reason") or "playwright unavailable")
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
        return self._browser

    def close(self) -> None:
        for obj in (self._browser, self._pw):
            try:
                if obj is not None:
                    obj.close() if obj is self._browser else obj.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None

    # ── actions ───────────────────────────────────────────────────────────

    def navigate(self, url: str, timeout_ms: int = 20000) -> Dict[str, Any]:
        """Load a page and return its real title/URL/text."""
        clean = validate_url(url)
        started = time.time()
        page = None
        try:
            browser = self._ensure_browser()
            page = browser.new_page()
            page.goto(clean, timeout=timeout_ms, wait_until="domcontentloaded")
            title = page.title()
            body_text = page.inner_text("body")
            logger.info("[web_agent] navigated %s (%.1fs)", clean, time.time() - started)
            return {
                "ok": True,
                "url": page.url,
                "title": title,
                "text": (body_text or "")[:8000],
                "elapsed_s": round(time.time() - started, 2),
            }
        except Exception as exc:
            return {"ok": False, "url": clean, "error": str(exc)[:300]}
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass

    def act(self, url: str, actions: List[Dict[str, Any]],
            timeout_ms: int = 20000) -> Dict[str, Any]:
        """Run a real action sequence on a page.

        Actions: {"fill": selector, "text": ...} | {"click": selector} |
                 {"press": key} | {"extract": selector} | {"wait_ms": n}.
        Each returned step records what ACTUALLY happened.
        """
        clean = validate_url(url)
        page = None
        steps: List[Dict[str, Any]] = []
        extracted: Dict[str, str] = {}
        try:
            browser = self._ensure_browser()
            page = browser.new_page()
            page.goto(clean, timeout=timeout_ms, wait_until="domcontentloaded")
            for i, action in enumerate(actions or []):
                step: Dict[str, Any] = {"step": i}
                try:
                    if "wait_ms" in action:
                        page.wait_for_timeout(int(action["wait_ms"]))
                        step["did"] = "wait"
                    elif "fill" in action:
                        page.fill(str(action["fill"]), str(action.get("text", "")),
                                  timeout=timeout_ms)
                        step["did"] = f"fill {action['fill']}"
                    elif "click" in action:
                        page.click(str(action["click"]), timeout=timeout_ms)
                        step["did"] = f"click {action['click']}"
                    elif "press" in action:
                        page.press("body", str(action["press"]))
                        step["did"] = f"press {action['press']}"
                    elif "extract" in action:
                        sel = str(action["extract"])
                        text = page.inner_text(sel)
                        extracted[sel] = text[:4000]
                        step["did"] = f"extract {sel}"
                    else:
                        step.update({"ok": False,
                                     "error": f"unknown action keys: {sorted(action)}"})
                        steps.append(step)
                        continue
                    step["ok"] = True
                except Exception as exc:
                    step.update({"ok": False, "error": str(exc)[:200]})
                steps.append(step)
            return {"ok": all(s.get("ok") for s in steps) if steps else True,
                    "url": page.url, "steps": steps, "extracted": extracted}
        except Exception as exc:
            return {"ok": False, "url": clean, "steps": steps,
                    "error": str(exc)[:300]}
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass


# ── async wrappers (routers / swarm agents run on the event loop) ─────────────

async def navigate_async(url: str) -> Dict[str, Any]:
    import asyncio

    agent = WebAgent()
    try:
        return await asyncio.get_running_loop().run_in_executor(None, agent.navigate, url)
    finally:
        await asyncio.get_running_loop().run_in_executor(None, agent.close)


async def act_async(url: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    import asyncio

    agent = WebAgent()
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: agent.act(url, actions))
    finally:
        await asyncio.get_running_loop().run_in_executor(None, agent.close)

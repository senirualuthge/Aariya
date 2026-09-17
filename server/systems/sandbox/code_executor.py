"""
Sandboxed code executor (AccessFIles §72 — SANDBOXED VIRTUAL ENVIRONMENTS).

Two execution backends, chosen by what is ACTUALLY installed on this machine:

1. Container runtime (docker or podman, detected via PATH): the code runs in
   an ephemeral container (--rm) with no network, capped CPU/memory, and a
   read-only rootfs — a real isolation boundary.
2. Subprocess fallback: when no container runtime exists, code runs in a
   child process with a strict timeout. This isolates the server from
   crashes/timeouts but does NOT block filesystem/network access.

Every result reports which backend ran ("runtime" field) — never pretended
otherwise. Capability-triggering callers must still gate on user confirmation.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Any, Optional

logger = logging.getLogger("aariya.code_executor")

_CONTAINER_IMAGE = os.getenv("AARIYA_SANDBOX_IMAGE", "python:3.11-slim")
_CPU_LIMIT = os.getenv("AARIYA_SANDBOX_CPUS", "1.0")
_MEM_LIMIT = os.getenv("AARIYA_SANDBOX_MEMORY", "256m")


def detect_container_runtime() -> Optional[str]:
    """Return 'docker' | 'podman' | None based on what is really on PATH."""
    for name in ("podman", "docker"):
        path = shutil.which(name)
        if path:
            return name
    return None


class SandboxedExecutor:
    def __init__(self, timeout: float = 10.0, max_output_chars: int = 20_000,
                 prefer_container: bool = True):
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        self.prefer_container = prefer_container

    @property
    def interpreter(self) -> str:
        # Prefer the current venv's interpreter so the fallback sandbox sees
        # the same installed packages as the server.
        return sys.executable or shutil.which("python3") or "python3"

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_python(self, code: str) -> Dict[str, Any]:
        if not code or not isinstance(code, str):
            return {"error": "No code supplied."}

        runtime = detect_container_runtime() if self.prefer_container else None
        if runtime:
            result = self._execute_in_container(runtime, code)
            if result.get("error") and result.get("recoverable"):
                logger.warning("[sandbox] container path failed (%s); "
                               "falling back to subprocess",
                               result["error"])
                result = self._execute_in_subprocess(code)
                result["runtime"] = "subprocess-fallback"
            return result
        result = self._execute_in_subprocess(code)
        result["runtime"] = "subprocess"
        return result

    # ── Backend 1: real container ─────────────────────────────────────────────

    def _execute_in_container(self, runtime: str, code: str) -> Dict[str, Any]:
        workdir = tempfile.mkdtemp(prefix="aariya_sandbox_")
        script = os.path.join(workdir, "main.py")
        try:
            with open(script, "w", encoding="utf-8") as f:
                f.write(code)

            proc = subprocess.run(
                [
                    runtime, "run",
                    "--rm",                       # ephemeral: rollback == nothing survives
                    "--network", "none",          # no exfiltration / C2 channel
                    "--read-only",                # immutable rootfs
                    "--cpus", _CPU_LIMIT,
                    "--memory", _MEM_LIMIT,
                    "--security-opt", "no-new-privileges",
                    "-v", f"{workdir}:/sandbox:rw",  # only the staged script mounts
                    "-w", "/sandbox",
                    _CONTAINER_IMAGE,
                    "python", "/sandbox/main.py",
                ],
                capture_output=True, text=True, timeout=self.timeout,
            )
            out: Dict[str, Any] = {
                "stdout": proc.stdout[: self.max_output_chars],
                "stderr": proc.stderr[: self.max_output_chars],
                "returncode": proc.returncode,
                "runtime": runtime,
                "image": _CONTAINER_IMAGE,
            }
            # Image not pulled yet — surface an honest, actionable error but
            # let execute_python fall back rather than hard-fail autonomy.
            if proc.returncode != 0 and "Unable to find image" in (proc.stderr or ""):
                return {**out,
                        "error": f"image {_CONTAINER_IMAGE} not pulled "
                                 f"(set AARIYA_SANDBOX_PULL=1 or pull manually)",
                        "recoverable": True}
            return out
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out after {self.timeout}s.",
                    "runtime": runtime}
        except FileNotFoundError:
            # runtime vanished between detect and run — recoverable
            return {"error": f"{runtime} disappeared mid-run", "recoverable": True}
        except Exception as e:
            logger.warning("[sandbox] container execution failed: %s", e)
            return {"error": str(e), "runtime": runtime, "recoverable": False}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ── Backend 2: subprocess fallback ────────────────────────────────────────

    def _execute_in_subprocess(self, code: str) -> Dict[str, Any]:
        fd, temp_path = tempfile.mkstemp(suffix=".py", prefix="aariya_sandbox_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)

            proc = subprocess.run(
                [self.interpreter, temp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            return {
                "stdout": proc.stdout[: self.max_output_chars],
                "stderr": proc.stderr[: self.max_output_chars],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Execution timed out after {self.timeout}s."}
        except Exception as e:
            logger.warning(f"[sandbox] execution failed: {e}")
            return {"error": str(e)}
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ── Image pull helper (explicit operator action, never automatic) ─────────────

def pull_sandbox_image() -> Dict[str, Any]:
    """Pull the sandbox image so container runs work offline afterwards.
    Only ever called explicitly (endpoint / operator CLI) — never on boot."""
    runtime = detect_container_runtime()
    if not runtime:
        return {"ok": False, "error": "no container runtime on PATH"}
    try:
        proc = subprocess.run(
            [runtime, "pull", _CONTAINER_IMAGE],
            capture_output=True, text=True, timeout=600,
        )
        return {"ok": proc.returncode == 0, "runtime": runtime,
                "image": _CONTAINER_IMAGE,
                "stderr": proc.stderr[-500:] if proc.returncode else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}

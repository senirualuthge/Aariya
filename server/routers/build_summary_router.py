"""Build summary router — serves the production build summary written by
scripts/dev.mjs after each `npm run dev -- --prod` build (dist stats, per-type
breakdown, largest files, build time). The analytics dashboard reads it via
GET /api/build/summary."""

import json
import os

from fastapi import APIRouter

router = APIRouter(prefix="/api/build", tags=["build"])

# server/routers/… → server → project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUMMARY_PATH = os.path.join(PROJECT_ROOT, ".build-summary.json")


@router.get("/summary")
async def get_build_summary():
    """Return the latest production build summary, or {found: false} if none yet."""
    if not os.path.exists(SUMMARY_PATH):
        return {"found": False}
    try:
        with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["found"] = True
        return data
    except (OSError, json.JSONDecodeError):
        # Corrupt/partial write — treat as no summary rather than 500ing.
        return {"found": False}

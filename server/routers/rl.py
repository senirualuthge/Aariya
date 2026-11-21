"""
RL Router — /api/rl/* for the conversational-style PPO policy (Track E).

GET /api/rl/status → the trained flag, durable transition count, last-train age,
and the recent action distribution — all read from the real checkpoint + the
`rl_transitions` log. Nothing is synthesised; an untrained policy reports so.
"""

from fastapi import APIRouter, Depends

from server.systems.security.device_auth import require_personal_device

# Policy status describes the owner's trained model; keep it behind a device.
router = APIRouter(
    prefix="/api/rl",
    tags=["rl"],
    dependencies=[Depends(require_personal_device)],
)


@router.get("/status")
async def rl_status():
    """Live status of the conversational-style PPO policy."""
    try:
        from server.systems.rl.rl_policy import get_ppo_policy
    except Exception as e:  # torch may be missing in a minimal install
        return {"available": False, "trained": False, "error": str(e)}

    try:
        status = get_ppo_policy().get_status()
    except Exception as e:
        return {"available": False, "trained": False, "error": str(e)}

    status["available"] = True
    return status

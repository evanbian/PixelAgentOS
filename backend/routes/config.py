"""Config API routes — global PM configuration."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_config, set_config, delete_config

router = APIRouter(prefix="/api/config", tags=["config"])


class PMConfigUpdate(BaseModel):
    model: str
    api_key: str


def _mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    # Handle key|||api_base format
    if "|||" in key:
        k, base = key.split("|||", 1)
        masked_k = "****" + k[-4:] if len(k) > 4 else "****"
        return f"{masked_k}|||{base}"
    return "****" + key[-4:]


@router.get("/pm")
async def get_pm_config():
    """Get PM configuration (key is masked)."""
    model = await get_config("PM_MODEL")
    api_key = await get_config("PM_API_KEY")
    return {
        "model": model or "",
        "api_key": _mask_key(api_key or ""),
    }


@router.put("/pm")
async def set_pm_config(body: PMConfigUpdate):
    """Set PM configuration."""
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="PM model is required")
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="PM API key is required")
    await set_config("PM_MODEL", body.model.strip())
    await set_config("PM_API_KEY", body.api_key.strip())
    return {"status": "ok", "model": body.model.strip()}


@router.delete("/pm")
async def clear_pm_config():
    """Clear PM configuration."""
    await delete_config("PM_MODEL")
    await delete_config("PM_API_KEY")
    return {"status": "ok"}


@router.get("/pm/status")
async def pm_config_status():
    """Check if PM is configured."""
    model = await get_config("PM_MODEL")
    api_key = await get_config("PM_API_KEY")
    configured = bool(model and api_key)
    return {"configured": configured, "model": model or ""}

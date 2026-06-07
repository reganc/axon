from fastapi import APIRouter

from ... import db
from ...config import get_settings

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": get_settings().app_name,
        "version": "0.4.0-phase4",
        "db": await db.ping(),
    }

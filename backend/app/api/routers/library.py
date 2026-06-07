from fastapi import APIRouter, Query
from pydantic import BaseModel

from ...deps import library

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/search")
async def search(q: str = Query(...), k: int = 10):
    return await library().search(q, k)


class CheckoutReq(BaseModel):
    user_id: str
    spine_id: str | None = None
    subject: str | None = None


@router.post("/checkout")
async def checkout(req: CheckoutReq):
    return await library().checkout(req.user_id, req.spine_id, req.subject)


@router.get("/checkout/{checkout_id}")
async def overlay(checkout_id: str):
    return await library().overlay_state(checkout_id)

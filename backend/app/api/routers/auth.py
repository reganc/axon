from fastapi import APIRouter
from pydantic import BaseModel

from ...deps import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenReq(BaseModel):
    user_id: str
    role: str = "learner"


@router.post("/token")
async def issue(req: TokenReq):
    return {"token": auth().issue_token(req.user_id, req.role)}

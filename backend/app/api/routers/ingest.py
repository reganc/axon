from fastapi import APIRouter
from pydantic import BaseModel

from ...deps import ingestion

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class SeedReq(BaseModel):
    path: str = "artifacts/lecun_seed_graph.json"


@router.post("/seed")
async def seed(req: SeedReq):
    return await ingestion().ingest_seed(req.path)

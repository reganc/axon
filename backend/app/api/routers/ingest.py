from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...deps import ingestion
from ...ports import IngestReport, Principal
from ..security import require_perm

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class SeedReq(BaseModel):
    path: str = "artifacts/lecun_seed_graph.json"


@router.post("/seed", response_model=IngestReport)
async def seed(req: SeedReq, _: Principal = Depends(require_perm("graph:write"))):
    return await ingestion().ingest_seed(req.path)

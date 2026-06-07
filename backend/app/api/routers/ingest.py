from typing import Literal

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


class MineReq(BaseModel):
    source_kind: Literal["claude_code_transcript", "obsidian_note"]
    path: str


@router.post("/mine", response_model=IngestReport)
async def mine(req: MineReq, _: Principal = Depends(require_perm("graph:write"))):
    return await ingestion().mine(req.source_kind, req.path)


class PurgeReq(BaseModel):
    source_tag: str


@router.post("/purge")
async def purge(req: PurgeReq, _: Principal = Depends(require_perm("graph:write"))):
    deleted = await ingestion().purge_by_source(req.source_tag)
    return {"deleted": deleted}

from uuid import UUID

from fastapi import APIRouter, Depends

from ...deps import content
from ...ports import Principal, SpineSummary, SpineWithNodes, Subgraph
from ..security import require_perm

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/spines", response_model=list[SpineSummary])
async def list_spines(_: Principal = Depends(require_perm("graph:read"))):
    return await content().list_spines()


@router.get("/nodes/{node_id}", response_model=Subgraph)
async def get_node(node_id: UUID, _: Principal = Depends(require_perm("graph:read"))):
    return await content().get_subgraph([node_id], depth=1)


@router.get("/spines/{spine_id}", response_model=SpineWithNodes)
async def get_spine(spine_id: UUID, _: Principal = Depends(require_perm("graph:read"))):
    return await content().get_spine(spine_id)

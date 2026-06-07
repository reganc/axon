from fastapi import APIRouter

from ...deps import content

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    return await content().get_subgraph([node_id], depth=1)


@router.get("/spines/{spine_id}")
async def get_spine(spine_id: str):
    return await content().get_spine(spine_id)

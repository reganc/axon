"""Browse — the derived taxonomy lens (Phase 5 §8).

`GET /browse/facets` returns a hierarchy computed live from the graph and cached
briefly. It is a *view*, not a stored tree: add nodes and the facets change.
"""

import time

from fastapi import APIRouter, Depends, Query

from ...deps import library
from ...ports import Facets, Principal
from ..security import require_perm

router = APIRouter(prefix="/browse", tags=["browse"])

_CACHE_TTL = 60.0  # seconds — a cheap lens cache; ?fresh=1 bypasses it
_cache: dict = {"facets": None, "at": 0.0}


@router.get("/facets", response_model=Facets)
async def facets(
    fresh: bool = Query(False, description="bypass the short-lived cache"),
    _: Principal = Depends(require_perm("graph:read")),
):
    now = time.monotonic()
    if not fresh and _cache["facets"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["facets"]
    result = await library().facets()
    _cache["facets"] = result
    _cache["at"] = now
    return result

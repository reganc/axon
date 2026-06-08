from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...deps import auth, library
from ...errors import NotFoundError
from ...ports import (
    Checkout,
    CheckoutSummary,
    ConversationEvent,
    Node,
    NodeState,
    Principal,
    ScoredNode,
)
from ..security import require_perm

router = APIRouter(prefix="/library", tags=["library"])


async def _require_own_checkout(checkout_id: UUID, principal: Principal) -> None:
    owner = await library().checkout_owner(checkout_id)
    if owner is None:
        raise NotFoundError(f"checkout {checkout_id} not found")
    if owner != principal.user_id:
        auth().require(principal, "checkout:read:any")  # only admin reads others'


@router.get("/entry-points", response_model=list[Node])
async def entry_points(
    limit: int = Query(24, ge=1, le=100),
    _: Principal = Depends(require_perm("graph:read")),
):
    return await library().entry_points(limit)


@router.get("/search", response_model=list[ScoredNode])
async def search(
    q: str = Query(..., min_length=1),
    k: int = Query(10, ge=1, le=100),
    kinds: str | None = Query(
        None, description="comma-separated node kinds to filter by"
    ),
    _: Principal = Depends(require_perm("graph:read")),
):
    kind_list = [s.strip() for s in kinds.split(",") if s.strip()] if kinds else None
    return await library().search(q, k, kind_list)


class CheckoutReq(BaseModel):
    spine_id: UUID | None = None
    subject: str | None = None


@router.post("/checkout", response_model=Checkout)
async def checkout(
    req: CheckoutReq, principal: Principal = Depends(require_perm("checkout:create"))
):
    # The owner is always the authenticated principal — never a client-supplied id.
    return await library().checkout(principal.user_id, req.spine_id, req.subject)


@router.get("/checkouts", response_model=list[CheckoutSummary])
async def my_checkouts(
    principal: Principal = Depends(require_perm("checkout:read:self")),
):
    """The caller's learning sessions, most-recently-active first."""
    return await library().list_checkouts(principal.user_id)


@router.get("/checkout/{checkout_id}", response_model=list[NodeState])
async def overlay(
    checkout_id: UUID,
    principal: Principal = Depends(require_perm("checkout:read:self")),
):
    await _require_own_checkout(checkout_id, principal)
    return await library().overlay_state(checkout_id)


@router.get(
    "/checkout/{checkout_id}/conversation", response_model=list[ConversationEvent]
)
async def conversation(
    checkout_id: UUID,
    principal: Principal = Depends(require_perm("checkout:read:self")),
):
    """The stored event stream — replayed by the client to restore the session."""
    await _require_own_checkout(checkout_id, principal)
    return await library().get_conversation(checkout_id)

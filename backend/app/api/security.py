"""api/security.py — HTTP auth dependencies.

Extract the bearer token, verify it through the identity seam, and gate routes by
permission. Domain errors (AuthError/ForbiddenError) propagate to main.py's
handler, which maps them to 401/403.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header

from ..deps import auth
from ..errors import AuthError
from ..ports import Principal


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return auth().verify(token)


def require_perm(perm: str) -> Callable[[Principal], Principal]:
    """Dependency factory: gate a route on a single permission."""

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        auth().require(principal, perm)
        return principal

    return _dep

"""identity seam — JWT issue/verify + role-based access control.

Phase 1. Roles: learner | author | admin. Permissions are coarse and additive
(admin ⊇ author ⊇ learner). The port (`AuthPort`) is the only surface other seams
and the routers see; `JwtAuth` is the concrete behind it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from ...config import Settings, get_settings
from ...errors import AuthError, ForbiddenError
from ...ports import Principal, Role

# RBAC matrix. A role holds every permission listed for it.
ROLE_PERMS: dict[str, set[str]] = {
    "learner": {"graph:read", "checkout:create", "checkout:read:self"},
    "author": {
        "graph:read",
        "graph:write",
        "node:lock",
        "checkout:create",
        "checkout:read:self",
    },
    "admin": {
        "graph:read",
        "graph:write",
        "node:lock",
        "checkout:create",
        "checkout:read:self",
        "checkout:read:any",
    },
}

VALID_ROLES = frozenset(ROLE_PERMS)


class JwtAuth:
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()

    def issue_token(self, user_id: UUID | str, role: Role | str = "learner") -> str:
        if role not in VALID_ROLES:
            raise AuthError(f"unknown role: {role!r}")
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self._s.jwt_expire_min)).timestamp()),
        }
        return jwt.encode(payload, self._s.jwt_secret, algorithm=self._s.jwt_alg)

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(token, self._s.jwt_secret, algorithms=[self._s.jwt_alg])
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid token") from exc
        try:
            return Principal(user_id=UUID(claims["sub"]), role=claims["role"])
        except (KeyError, ValueError) as exc:
            raise AuthError("malformed token claims") from exc

    def require(self, principal: Principal, perm: str) -> None:
        if perm not in ROLE_PERMS.get(principal.role, set()):
            raise ForbiddenError(f"role {principal.role!r} lacks permission {perm!r}")


# Back-compat alias so deps.py can swap cleanly; the stub name is retired.
StubAuth = JwtAuth

"""identity seam — JWT/RBAC. Phase 1 lifts the real implementation from carecore/havencore."""


class StubAuth:
    def issue_token(self, user_id, role): raise NotImplementedError("identity seam — Phase 1")
    def verify(self, token): raise NotImplementedError("identity seam — Phase 1")
    def require(self, principal, perm): raise NotImplementedError("identity seam — Phase 1")

"""identity seam — JWT + RBAC unit tests (no DB)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.config import Settings
from app.errors import AuthError, ForbiddenError
from app.ports import Principal
from app.seams.identity import JwtAuth


def _auth(expire_min: int = 720) -> JwtAuth:
    return JwtAuth(Settings(jwt_secret="unit-secret", jwt_expire_min=expire_min))


def test_issue_and_verify_roundtrip():
    auth = _auth()
    uid = uuid4()
    principal = auth.verify(auth.issue_token(uid, "author"))
    assert principal == Principal(user_id=uid, role="author")


def test_verify_rejects_garbage():
    with pytest.raises(AuthError):
        _auth().verify("not.a.jwt")


def test_verify_rejects_wrong_secret():
    other = JwtAuth(Settings(jwt_secret="different"))
    token = _auth().issue_token(uuid4(), "learner")
    with pytest.raises(AuthError):
        other.verify(token)


def test_verify_rejects_expired():
    token = _auth(expire_min=-1).issue_token(uuid4(), "learner")
    with pytest.raises(AuthError):
        _auth().verify(token)


def test_issue_rejects_unknown_role():
    with pytest.raises(AuthError):
        _auth().issue_token(uuid4(), "wizard")


def test_rbac_learner_denied_write():
    auth = _auth()
    learner = Principal(user_id=uuid4(), role="learner")
    auth.require(learner, "graph:read")  # allowed, no raise
    auth.require(learner, "checkout:create")
    with pytest.raises(ForbiddenError):
        auth.require(learner, "graph:write")


def test_rbac_author_can_write_admin_reads_any():
    auth = _auth()
    author = Principal(user_id=uuid4(), role="author")
    auth.require(author, "graph:write")
    auth.require(author, "node:lock")
    with pytest.raises(ForbiddenError):
        auth.require(author, "checkout:read:any")
    auth.require(Principal(user_id=uuid4(), role="admin"), "checkout:read:any")

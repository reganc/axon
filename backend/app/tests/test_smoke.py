"""Smoke tests — app boots and auth gating is wired (no DB required)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_protected_route_requires_token():
    # Phase 1 gates graph reads behind a bearer token; no header -> 401.
    with TestClient(app) as c:
        r = c.get("/graph/spines/69f5cb6a-449a-518d-8a5b-6b182a1ac320")
    assert r.status_code == 401

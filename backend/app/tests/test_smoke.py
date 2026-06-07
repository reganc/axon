from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unimplemented_returns_501():
    with TestClient(app) as c:
        r = c.get("/graph/spines/some-id")
    assert r.status_code == 501

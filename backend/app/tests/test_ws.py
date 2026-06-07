"""WebSocket companion stream — end-to-end over the ASGI app (DB + scripted LLM)."""

from __future__ import annotations

from uuid import uuid4

from .conftest import requires_db, scripted_handler

pytestmark = requires_db


def _scripted_companion(plan):
    from app import deps
    from app.seams.companion import Companion
    from app.seams.companion.llm import LLMGateway

    gateway = LLMGateway.scripted(scripted_handler(plan), deps.embedder())
    return Companion(
        llm=gateway,
        library=deps.library(),
        ingestion=deps.ingestion(),
        content=deps.content(),
        learning=deps.learning(),
    )


def test_ws_requires_token(client, seeded):
    # connecting without a token is refused (policy violation, no accept)
    import pytest
    from starlette.websockets import WebSocketDisconnect

    fake_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/companion/{fake_id}") as ws:
            ws.receive_json()


def test_ws_streams_a_turn(client, seeded, monkeypatch):
    comp = _scripted_companion(["The convolutional network"])
    monkeypatch.setattr("app.api.ws.companion.companion", lambda: comp)

    uid = str(uuid4())
    tok = client.post("/auth/token", json={"user_id": uid, "role": "learner"}).json()[
        "token"
    ]
    checkout = client.post(
        "/library/checkout", json={}, headers={"Authorization": f"Bearer {tok}"}
    )
    cid = checkout.json()["id"]

    events = []
    with client.websocket_connect(f"/ws/companion/{cid}?token={tok}") as ws:
        ws.send_json({"type": "subject", "text": "convolutional networks"})
        for _ in range(50):
            msg = ws.receive_json()
            events.append(msg)
            if msg["type"] == "done":
                break
        ws.send_json({"type": "close"})

    types = [e["type"] for e in events]
    assert "node.create" in types
    assert types[-1] == "done"

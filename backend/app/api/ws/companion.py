from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws/companion/{checkout_id}")
async def companion_ws(ws: WebSocket, checkout_id: str):
    # Phase 0 placeholder: real typed event stream (say/ask/node.create/...) lands in Phase 2.
    await ws.accept()
    await ws.send_json({"type": "status", "data": {"phase": "skeleton", "detail": "companion lands in Phase 2"}})
    await ws.send_json({"type": "done", "data": {}})
    await ws.close()

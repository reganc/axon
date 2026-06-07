"""WebSocket: the companion event stream.

`WS /ws/companion/{checkout_id}` — JWT passed in the connect handshake (query
param `token`, or an Authorization header). The server verifies it, checks the
checkout belongs to the caller, then runs a bidirectional loop:

  client -> server : {type: subject|start, text}      start/continue a turn
                     {type: interrupt|answer, text}    barge-in (re-enters Tutor)
                     {type: pull_thread, node_id}      spawn a rabbit-hole
                     {type: close}                     end
  server -> client : StreamEvent JSON (say/ask/node.create/node.update/...)

Every emitted event is also published to Redis for multi-device fan-out.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ... import bus
from ...deps import auth, companion, library
from ...errors import DomainError
from ...ports import StreamEvent

log = logging.getLogger("axon.ws")
router = APIRouter()

_POLICY_VIOLATION = 1008


@router.websocket("/ws/companion/{checkout_id}")
async def companion_ws(ws: WebSocket, checkout_id: UUID):
    token = ws.query_params.get("token") or _bearer(ws.headers.get("authorization"))
    try:
        if not token:
            raise DomainError("missing token")
        principal = auth().verify(token)
        owner = await library().checkout_owner(checkout_id)
        if owner is None:
            raise DomainError("checkout not found")
        if owner != principal.user_id:
            auth().require(principal, "checkout:read:any")  # only admins read others'
    except DomainError as exc:
        await ws.close(code=_POLICY_VIOLATION, reason=str(exc))
        return

    await ws.accept()
    cid = checkout_id
    inbox: asyncio.Queue = asyncio.Queue()
    turn: asyncio.Task | None = None

    async def stream(agen) -> None:
        async for ev in agen:
            await _send(ws, cid, ev)

    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")

            if kind in ("subject", "start"):
                if turn and not turn.done():
                    await inbox.put({"type": "interrupt", "text": msg.get("text", "")})
                else:
                    turn = asyncio.create_task(
                        stream(companion().run_turn(cid, msg.get("text", ""), inbox))
                    )
            elif kind in ("interrupt", "answer"):
                await inbox.put(msg)
            elif kind == "pull_thread":
                await stream(companion().pull_thread(cid, msg.get("node_id")))
            elif kind == "close":
                break
            else:
                await _send(
                    ws,
                    cid,
                    StreamEvent(type="status", data={"detail": f"ignored {kind!r}"}),
                )
    except WebSocketDisconnect:
        pass
    finally:
        if turn and not turn.done():
            turn.cancel()
        await _safe_close(ws)


def _bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


async def _send(ws: WebSocket, cid, ev: StreamEvent) -> None:
    payload = {"type": ev.type, "data": ev.data}
    await ws.send_json(payload)
    await bus.publish(cid, payload)


async def _safe_close(ws: WebSocket) -> None:
    try:
        await ws.close()
    except RuntimeError:
        pass  # already closed

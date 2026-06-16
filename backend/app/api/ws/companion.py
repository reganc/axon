"""WebSocket: the companion event stream.

`WS /ws/companion/{checkout_id}` — JWT passed in the connect handshake (query
param `token`, or an Authorization header). The server verifies it, checks the
checkout belongs to the caller, then runs a bidirectional loop:

  client -> server : {type: subject|start, text}      start/continue a turn
                     {type: interrupt|answer, text}    barge-in (re-enters Tutor)
                     {type: pull_thread, node_id}      spawn a rabbit-hole
                     {type: explain, node_id}          deep-dive a selected card
                     {type: discuss, node_id, text}    node-scoped follow-up chat
                     {type: set_level, level}          pitch talk to a learner level
                     {type: request_media, node_id}    visual aids for a card
                     {type: close}                     end

`set_level` is a transient, per-connection presentation hint (kid|high_school|
undergrad|expert) that shapes only the spoken/streamed talk — deep-dive
explanations and discussion replies. It never touches the canonical graph: the
same nodes/bodies are generated and persisted regardless of the level a learner
reads them at.
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

# Background session-mining tasks, held so the event loop doesn't GC them mid-run
# (asyncio keeps only a weak reference to a bare create_task result).
_mining_tasks: set[asyncio.Task] = set()


@router.websocket("/ws/companion/{checkout_id}")
async def companion_ws(ws: WebSocket, checkout_id: UUID):
    # Accept first, then validate. Closing *before* accept surfaces to browsers as
    # an opaque 1006 abnormal-closure with no code or reason, so clients can't tell
    # a permanently-dead checkout (retry is pointless) from a transient blip and
    # reconnect forever. Accepting then closing with 1008 + reason gives the client
    # an actionable signal.
    await ws.accept()
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
        # Direct send (not _send): a transient error must not be persisted to the
        # durable conversation log or replayed on the next connect.
        try:
            await ws.send_json({"type": "error", "data": {"reason": str(exc)}})
        except RuntimeError:
            pass  # socket already gone
        await ws.close(code=_POLICY_VIOLATION, reason=str(exc))
        return

    cid = checkout_id
    inbox: asyncio.Queue = asyncio.Queue()
    turn: asyncio.Task | None = None
    aux: asyncio.Task | None = None  # deep-dive / discuss; cancelled when superseded
    media: asyncio.Task | None = None  # enrichment stream; its own cancellable slot
    level: str | None = None  # transient delivery level for this connection's talk

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
            elif kind == "explore_question":
                await stream(companion().explore_question(cid, msg.get("node_id")))
            elif kind == "set_level":
                # Transient presentation hint; unknown values degrade to no
                # conditioning downstream. Not persisted to the durable log.
                level = msg.get("level")
            elif kind == "explain":
                # Deep-dive on a selected card. Runs as a cancellable task so the
                # receive loop keeps reading — opening another card supersedes it.
                if aux and not aux.done():
                    aux.cancel()
                aux = asyncio.create_task(
                    stream(companion().explain_node(cid, msg.get("node_id"), level))
                )
            elif kind == "discuss":
                # A node-scoped follow-up. Shares the cancellable aux slot with the
                # deep-dive, so a new question (or opening another card) supersedes
                # an in-flight answer — barge-in — while the receive loop drains.
                if aux and not aux.done():
                    aux.cancel()
                aux = asyncio.create_task(
                    stream(
                        companion().discuss(
                            cid, msg.get("node_id"), msg.get("text", ""), level
                        )
                    )
                )
            elif kind == "request_media":
                # Visual aids for a card (diagram, neighbor graph, web media). Its
                # own cancellable slot so it can run alongside a deep-dive/chat and
                # not be cancelled by them.
                if media and not media.done():
                    media.cancel()
                media = asyncio.create_task(
                    stream(companion().enrich(cid, msg.get("node_id")))
                )
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
        for task in (turn, aux, media):
            if task and not task.done():
                task.cancel()
        # Distil this session's learner dialogue into the library off the hot path:
        # fire-and-forget so the close returns immediately while mining runs in the
        # background. Resolve the companion now (so a test monkeypatch still wins).
        _schedule_session_mining(companion(), cid)
        await _safe_close(ws)


def _schedule_session_mining(comp, checkout_id) -> None:
    task = asyncio.create_task(_mine_session_safe(comp, checkout_id))
    _mining_tasks.add(task)
    task.add_done_callback(_mining_tasks.discard)


async def _mine_session_safe(comp, checkout_id) -> None:
    try:
        produced = await comp.mine_session(checkout_id)
        if produced:
            log.info(
                "session %s mined %d node(s) from live dialogue",
                checkout_id,
                produced,
            )
    except Exception:  # never let background mining surface on the closed socket
        log.exception("session mining failed for checkout %s", checkout_id)


def _bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


async def _send(ws: WebSocket, cid, ev: StreamEvent) -> None:
    payload = {"type": ev.type, "data": ev.data}
    await ws.send_json(payload)
    await bus.publish(cid, payload)
    # durable log: replayable events are persisted so the session survives the tab
    await library().record_event(cid, ev.type, ev.data)


async def _safe_close(ws: WebSocket) -> None:
    try:
        await ws.close()
    except RuntimeError:
        pass  # already closed

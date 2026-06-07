"""main.py — FastAPI entry. Mounts routers + the companion WebSocket, maps the
phase-0 NotImplementedError stubs to HTTP 501, and pings the DB on startup
without crashing if it's unreachable (skeleton boots standalone)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import bus, db
from .api.routers import auth, browse, graph, health, ingest, library
from .api.ws import companion as companion_ws
from .config import get_settings
from .errors import DomainError

log = logging.getLogger("axon")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not await db.ping():
        log.warning("database not reachable at startup — running without persistence")
    yield
    await bus.close()
    await db.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="AXON", version="0.4.0-phase4", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(request: Request, exc: NotImplementedError):
        return JSONResponse(
            status_code=501,
            content={"detail": str(exc) or "not implemented in this phase"},
        )

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    for r in (health, auth, graph, library, ingest, browse):
        app.include_router(r.router)
    app.include_router(companion_ws.router)
    return app


app = create_app()

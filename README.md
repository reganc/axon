# AXON — Phase 0 skeleton

A compiling FastAPI scaffold: all six seam contracts (`app/ports.py`), config, async DB,
Docker Compose, and a smoke test. Every seam ships a stub that returns HTTP 501 with its
phase label, so the app boots and you can implement seams one at a time without breaking the rest.

## Run locally (no Docker)

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 4100
# GET http://localhost:4100/health   -> 200
# GET http://localhost:4100/docs     -> OpenAPI; unimplemented routes return 501
pytest app/tests
```

## Run with Docker

```bash
cp .env.example .env            # edit secrets (POSTGRES_PASSWORD, JWT secret); ports default to the 4100 block
docker compose up --build
# api on :4100, db on :4102, redis on :4103 (see CLAUDE.md → Network & ports)
# db (timescaledb-ha: pgvector + timescaledb) applies ./artifacts/schema.sql on first init
```

## Layout

```
docker-compose.yml      db (pgvector+timescale) + cache (redis) + api
.env.example
backend/
  app/
    main.py             FastAPI app, lifespan, 501 handler, router/WS mounts
    config.py           pydantic-settings, AXON_ env prefix
    db.py               async engine/session, fail-soft ping
    ports.py            THE SEAMS: 6 port Protocols + DTOs
    deps.py             wiring (stubs now; swap per phase)
    seams/{identity,content,library,learning,companion,ingestion}/
    api/routers/        health, auth, graph, library, ingest
    api/ws/companion.py placeholder event stream (real one = Phase 2)
    workers/librarian.py
    tests/test_smoke.py
```

## Build order

Implement seams against `ports.py` following `specs/01..04`. Each replaces a stub in
`deps.py`; routers never change. Start with Phase 1 (`identity`, `content`, `library`,
`ingestion`) and load `artifacts/lecun_seed_graph.json`.

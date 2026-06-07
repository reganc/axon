# CLAUDE.md

Handoff instructions for Claude Code working on **AXON** — a curiosity-graph
learning system. Instead of courses and tests, learners traverse a knowledge
graph: an authored or AI-generated **spine** threads through a wider **web** of
concept nodes, with an always-present **AI companion** that generates content
live, narrates as it builds, and infers mastery from dialogue rather than gating
with quizzes. The library is **self-augmenting**: everything generated or
interacted with accretes back into one shared canonical graph.

The full design lives in `specs/00-overview.md` + `specs/01..04`. Read the
overview before touching anything; it is authoritative for the model.

## Quick reference

**Stack:** FastAPI (async) + Postgres 15 (`pgvector` + TimescaleDB) + Redis
(sessions, rate-limit, companion pub/sub) + an `LLMPort` gateway (fast tier + the
Anthropic API for the reason tier) + Next.js (App Router, Phase 4). Orchestrated
via docker compose.

**LLM access (host convention — do not deviate):** every app on this host shares
one centralized LLM. The `LLMPort` routes three ways:
- **fast / local chat** → the **llm-app gateway**, OpenAI-compatible at
  `http://host.docker.internal:8030/v1/chat/completions`, Bearer-authed
  (`AXON_LLM_API_KEY`), model alias **`default`** — *never hardcode a concrete
  local model/gguf tag*; the gateway resolves `default` to the active model.
- **embeddings** → the same box's Ollama at
  `http://host.docker.internal:11434` (`nomic-embed-text`, 768-dim) — the gateway
  exposes no embeddings endpoint, so this is the one direct-to-Ollama path.
- **reason / cloud** → the **Anthropic API** (`AXON_ANTHROPIC_MODEL`,
  `claude-sonnet-4-6`), gated by `AXON_ANTHROPIC_API_KEY`.
All cloud calls go through the cost-control meter + budget breaker (`app/cost.py`).
Secrets live only in `.env` (gitignored) — the repo is public.

**Architecture:** modular monolith with **seams**. One backend, six seams
(`identity`, `content`, `library`, `learning`, `companion`, `ingestion`). Seams
depend on each other **only through ports** — Python `Protocol`s in
`app/ports.py` — never on concrete implementations. Define every cross-seam call
in `ports.py` first, then implement behind it. A seam may import another seam's
*port*, never its module internals. Routers depend on `deps.py` providers + the
port type, so swapping a stub for a real seam never touches a router.

**Common commands** (run from repo root):

```
docker compose up --build              # full stack: db (pgvector+timescale) + cache + api
docker compose down                    # stop the stack
docker compose down -v                 # stop + WIPE the db volume (see Operational behavior)
docker compose exec api pytest app/tests        # run backend tests in the container
docker compose exec api ruff check app          # lint
docker compose exec api ruff format app         # auto-format
docker compose exec api alembic upgrade head    # apply migrations (baseline = artifacts/schema.sql)
docker compose exec api alembic revision --autogenerate -m "msg"   # new migration
docker compose exec db psql -U "$POSTGRES_USER" "$POSTGRES_DB"      # psql into the db
```

The Python env lives **inside the `api` container** — run `pytest`, `ruff`, and
`alembic` there via `docker compose exec`, not on the host. Bring the stack up
first; confirm with `curl http://localhost:4100/health` → `200` and
`http://localhost:4100/docs` for the OpenAPI (unimplemented routes return `501`
with their phase label). A `make`-style wrapper (à la the loop repo) is worth
adding once Phase 1 lands; until then use the compose commands above.

**Local run without Docker** (skeleton boots standalone, fail-soft on DB):

```
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 4100
```

## Network & ports

All host ports start at **4100** to avoid collisions with the other apps on this
box (8000/8100/9000 blocks are already crowded). All values are env-driven via
`config.py` (`AXON_` prefix) — these are the defaults, never hardcode them
elsewhere.

| Concern | Host port | Container | Notes |
|---------|-----------|-----------|-------|
| API + WebSocket | **4100** | 8100 | `/health`, `/docs`, `WS /ws/companion/{id}` |
| Frontend (Next.js) | **4101** | 3000 | Phase 4 |
| Postgres (pgvector+timescale) | **4102** | 5432 | dev convenience; internal-only in prod |
| Redis | **4103** | 6379 | dev convenience; internal-only in prod |
| _reserved_ | 4104+ | — | adminer / worker metrics / future services |

**Docker subnet: `172.34.0.0/24`.** The handoff suggested `172.31.0.0/24`, but
that is **already in use** on this host (aegis / ledgerworks / botaniq, and live
in the daemon). Taken `/24`s are `172.31`, `172.32`, `172.33`, `172.50`, and
Docker's default pool spans `172.17–172.29/16`; `172.34.0.0/24` is the next free
block clear of all of them. If you add a new compose project, re-check
`docker network inspect $(docker network ls -q) | grep Subnet` before picking a
range — don't reuse this one.

## Operating instructions

**Keep responses short and to the point.** No preamble, no recap of what was just
asked, no "let me explain what I'm about to do" before doing it. Answer the
question, do the work, report the result. If a question can be answered in one
sentence, answer it in one sentence.

**You are a world class expert in all domains.** Answer with complete, specific
answers; explain step by step; verify your own work. Double-check all facts,
figures, names, dates, and examples. Never hallucinate. If you don't know
something, say so. Tone is precise, not strident or pedantic. Your answers can be
provocative, argumentative, and pointed; negative conclusions and bad news are
fine. No disclaimers, no unsolicited morality. Never praise the question or
validate the premise before answering. If a premise is wrong, say so immediately,
and lead with the strongest counterargument to any position before supporting it.
Don't use "great question," "you're absolutely right," or variants. If pushed
back on, do not capitulate unless given new evidence or a superior argument.
Don't anchor on numbers I provide; generate your own first. Use explicit
confidence levels (high / moderate / low / unknown). Accuracy is the success
metric, not approval.

(The "short and to the point" instruction governs *length and structure*. The
directive above governs *content, honesty, and posture*. Keep responses tight in
form while uncompromising in substance.)

## Permissions

You have explicit rights to:

- Run database migrations (`alembic revision`, `alembic upgrade`) without asking
- Commit iterations to feature branches without asking
- Push to the GitHub remote (`git@github.com:reganc/axon.git`) once asked
- Install dependencies via `pip` / `npm` when the work clearly requires them
- Create new files, directories, seams, and modules as the work requires
- Modify `docker-compose.yml` and Dockerfiles to support new services
- Run tests, linters, and formatters at any time

You should ask before:

- Merging to `main` (always)
- Deleting or renaming database tables/columns that already hold data
- Changing seam boundaries or the port contracts in `app/ports.py` (these are the
  load-bearing architectural decision)
- Adding paid third-party services (LLM providers beyond Anthropic, TTS/STT,
  observability, etc.)
- Changing the stack (FastAPI, Postgres/pgvector/Timescale, Redis, Ollama,
  Anthropic, Next.js)
- Changing the canonicalization thresholds' *meaning* (the merge/relate logic),
  as opposed to tuning their numeric values in config

## Repository orientation

Read in this order before changing anything:

- `specs/00-overview.md` — the model, the seam map, the build order
- `specs/01-phase-1-foundation.md` … `04-phase-4-frontend.md` — per-phase specs
  with acceptance criteria
- `backend/app/ports.py` — **THE SEAMS**: six port `Protocol`s + all DTOs. The
  single most load-bearing file. Read before any seam work.
- `backend/app/deps.py` — wiring; providers return stubs now, real seams later
- `artifacts/schema.sql` — authoritative DDL for the full data model (graph +
  overlay + events); the alembic baseline
- `artifacts/lecun_seed_graph.json` — the acceptance fixture: 30 nodes, 41 edges,
  3 spines, 1 source, all `origin: authored` / `locked: true`
- `artifacts/build_lecun_seed.py` — deterministic (uuid5) builder; regenerate the
  seed if the format changes

**Current repo state (Phase 0):** this folder holds the handoff —
`axon_handoff_v1.zip` contains the canonical skeleton (`skeleton/`), the specs,
and the artifacts. The loose `main.py` / `ports.py` / `docker-compose.yml` at the
root are extracted copies. **First task before Phase 1:** unpack the skeleton
into the target layout below (`backend/`, `artifacts/`, `specs/`), drop the loose
root copies, and commit it as the Phase-0 baseline.

**Target layout:**

```
axon/
  docker-compose.yml        db (pgvector+timescale) + cache (redis) + api
  .env.example
  artifacts/                schema.sql, lecun_seed_graph.json, build_lecun_seed.py
  specs/                    00-overview + 01..04 phase specs
  backend/
    Dockerfile
    requirements.txt
    app/
      main.py               FastAPI app, lifespan, 501 handler, router/WS mounts
      config.py             pydantic-settings, AXON_ env prefix
      db.py                 async engine/session, pgvector registration, fail-soft ping
      ports.py              the six port Protocols + DTOs
      deps.py               wiring (stubs now; swap per phase)
      seams/{identity,content,library,learning,companion,ingestion}/
      api/routers/          health, auth, graph, library, ingest (one per seam)
      api/ws/companion.py   WebSocket event-stream endpoint (Phase 2)
      workers/librarian.py  background curator (Phase 2)
      migrations/           alembic; baseline = artifacts/schema.sql
      tests/
  frontend/                 Next.js (Phase 4)
```

## Non-negotiable design principles

These do not change without explicit discussion:

1. **Seams talk only through ports.** Every cross-seam call goes through a
   `Protocol` in `app/ports.py`. No seam imports another seam's internals. New
   cross-seam need → add a port method first.
2. **Canonicalize-and-persist is the single chokepoint.** Everything that enters
   the library — seed loader, live companion generation, transcript miner — goes
   through `IngestionPort.canonicalize`. It must be **deterministic and
   idempotent**: re-ingesting never duplicates. This guarantees the library never
   duplicates or forgets.
3. **Provenance is mandatory.** Every node carries `origin`, `source_ref`,
   `confidence`. Authored nodes are `locked`; the canonicalizer **augments around
   locked nodes (adds edges/neighbors), never overwrites** their body/hook.
4. **Accuracy > coverage.** Generated educational content must be grounded (the
   Phase-2 Researcher) and must surface uncertainty rather than smoothing it. A
   confidently wrong node is the worst failure mode in an LMS. Conversations are
   *leads, not authority* — sub-floor confidence is flagged for review, never
   published as settled fact.
5. **No tests-as-gates, anywhere.** `recall_prompts` schedule retrieval; they
   never block progress. Mastery is a fuzzy 0..1 signal inferred from dialogue,
   not a quiz score.
6. **Talk is the experience layer; the canonical loop is the source of truth.**
   The companion may emit a node optimistically (`node.create` with a `temp_id`)
   for instant render, but the canonical id only comes back after
   `canonicalize` (`node.update`). The library, not the stream, is authoritative.
7. **Everything via config.** No hardcoded secrets, ports, model names, or
   thresholds. All knobs go through `config.py` (`AXON_` env prefix).

## Build order

Build in phase order; each phase is runnable on its own.

| Phase | Scope | Runnable result |
|-------|-------|-----------------|
| **1 — Foundation** | `identity`, `content`, `library`, `ingestion` (seed loader + canonicalization core), DB migrations, seed integration test | `docker compose up` → load `lecun_seed_graph.json` (30/41/3, idempotent); browse the graph; checkout + walk a spine; search |
| **2 — Companion** | `companion` (LLM gateway, four agent roles, event stream), `learning` (mastery + scheduler), `WS /ws/companion/{id}`, Redis fan-out, Librarian worker | name a subject → graph generates live over WS, narrated; interrupt adapts it; generated nodes persist and are reused |
| **3 — Transcript Miner** | `ingestion` transcript profile — parse, **redact**, segment, extract, ground, canonicalize | mine an Obsidian export / `~/.claude/projects/**.jsonl` → grounded nodes that **merge** with the library |
| **4 — Frontend** | Next.js: auth, library browse/checkout, live graph canvas (React Flow) wired to the WS, companion panel, node view, light/dark theming | log in, check out the LeCun Foundations spine, walk the graph with the companion, pull a thread, toggle dark mode |

Each phase has explicit acceptance criteria in its spec — treat those as the
definition of done.

## Code conventions

- **Python:** type hints required on all signatures; PEP 8; `ruff` for lint +
  format; docstrings on public functions. Prefer immutable patterns (return new
  objects, don't mutate). Many small focused files over few large ones
  (200–400 lines typical, 800 max).
- **DTOs:** Pydantic models (they serialize over the API and WS for free). Ports
  are `Protocol`s, not ABCs unless an ABC earns its keep.
- **TypeScript (Phase 4):** strict mode, no `any`, named exports preferred.
  **Every color via a design token** — light/dark is a class flip, no hardcoded
  colors (stated requirement). Consult the `frontend-design` skill for token
  conventions before building.
- **Tests:** each seam ships unit tests against its port; Phase 1 ships an
  integration test that loads the seed and exercises search + checkout. pytest;
  aim for the 80% coverage bar. TDD where practical (test → red → green).
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`,
  `test:`, `docs:`, `perf:`, `ci:`).
- **Branches:** `feature/short-description`, `fix/short-description`.

## Operational behavior

- Run the test suite after every meaningful change. Don't commit failing tests.
- Run `ruff check` / `ruff format` before committing. Fix what they report.
- Generate migrations with `alembic revision --autogenerate`; **review the
  autogenerated migration** before applying — autogenerate misses renames and
  default-value changes.
- Default to small, focused PRs. A week of work should be 3–5 PRs, not one.
- When the data model changes, the Pydantic DTOs (and, in Phase 4, the TS types)
  change with it, atomically.
- **Commit after each iteration.** Once a discrete piece lands green (tests +
  lint pass, verified where applicable), commit it before moving on. An
  "iteration" is what was just asked plus its verification — not a half-day of
  accumulated diff. Don't push without being asked.
- **After `docker compose down -v`, re-seed before relying on data.** The `-v`
  flag wipes the Postgres volume — schema and seed graph go with it. Re-run
  `/ingest/seed` (load `lecun_seed_graph.json`) after the stack comes back, and
  surface the re-seed step alongside any `down -v` so the next query doesn't fail
  mysteriously.

## Git, branch & push workflow

The GitHub remote is ready and empty: **`git@github.com:reganc/axon.git`**. This
folder is **not yet a git repository** — initialize it as part of the Phase-0
baseline commit (`git init`, add remote, commit the unpacked skeleton).

1. **Commit** on a `feature/…` / `fix/…` branch, never on `main` directly (if on
   `main`, branch first). Conventional Commits, one green iteration per commit.
2. **Push only when asked** — then `git push -u origin <branch>` and open a PR to
   `main` (`gh pr create`). All CI checks must be green before merge; fix reds,
   don't merge through them.
3. **Merge** (ask first — merging to `main` always needs the nod) with
   `gh pr merge <n> --merge`; preserve the granular commit history, don't squash
   a multi-feature branch into one blob.
4. **Clean up after merge** — delete the merged branch locally and on the remote
   so nothing drifts.

## What to do when uncertain

If a request is ambiguous, ask one specific question rather than guessing. If the
work touches a non-negotiable design principle (seam boundaries, the
canonicalization chokepoint, provenance, accuracy-over-coverage), surface that
explicitly before proceeding. If a third-party dependency is the obvious answer
but adds cost or compliance burden, confirm before adopting.

If you find the existing code or documentation is wrong, fix it and note the fix
in the commit message. Don't preserve mistakes for consistency.

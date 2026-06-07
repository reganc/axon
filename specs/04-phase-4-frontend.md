# Phase 4 — Frontend: graph canvas, the companion, library, theming

**Goal:** the learner-facing app. A live knowledge-graph canvas where nodes materialize as
the companion speaks, a companion panel (chat now, voice staged), a library to browse and
check out spines, and full light/dark theming. This is where the spine/web/companion model
becomes something a person actually uses.

> Before building, the implementer should consult the **frontend-design** skill for the
> environment's design-token and styling conventions, and reuse comet's existing component
> conventions where they exist.

**Runnable result:** log in, browse the library, check out the LeCun "Foundations" spine,
walk the graph with the companion narrating, pull a thread to spawn a rabbit hole, toggle
dark mode.

---

## Scope

**In:** Next.js (App Router) app — auth, library browse/checkout, graph canvas wired to the
Phase-2 WebSocket, companion chat panel, node view (`hook → body → recall`), theming.
Voice tier 1 (text streaming) required; tier 2 (TTS) optional this phase.
**Out:** authoring tools for nodes/spines (separate later phase); full-duplex voice (tier 3).

## Stack

- Next.js (App Router), TypeScript, Tailwind.
- Graph rendering: **React Flow** (or Cytoscape/Sigma if perf demands) — must support live
  node/edge insertion driven by the event stream.
- Theming: CSS variables + `next-themes` (or equivalent). **Every color via token**, so
  light/dark is a class flip. No hardcoded colors. (This is the user's stated requirement.)
- Auth: JWT from the `identity` seam; store per comet conventions; attach on WS connect.

## Key surfaces

1. **Library** — browse subjects/spines (`/library`). Each spine shows its arc and a
   **Check out** action → creates a checkout, routes to the learning canvas.
2. **Learning canvas** (`/learn/[checkoutId]`) — the core screen:
   - **Graph canvas** (center): the spine highlighted as a path; lateral web nodes faded.
     Nodes/edges **stream in live** from `WS /ws/companion/{checkoutId}` — render
     `node.create` optimistically by `temp_id`, reconcile on `node.update`.
   - **Companion panel** (side/bottom): renders `say` as chat bubbles / voice; `ask` events
     render as an inline prompt (with `options` as quick-reply chips when present); a text
     input sends `answer` / `interrupt`.
   - **Node view**: open a node → `hook` first (the curiosity gap), then `body`, then a
     **"pull this thread"** affordance → emits `pull_thread{node_id}`. `recall_prompts` surface
     conversationally via the companion, never as a quiz wall.
3. **Theme toggle** — light/dark, persisted.

## Event-stream client

A typed WS client (`useCompanionStream(checkoutId)`) that:
- connects with JWT, auto-reconnects, and **resubscribes** (server replays from Redis or
  resends overlay state on reconnect);
- dispatches events to a graph store (nodes/edges) and a transcript store (say/ask);
- exposes `answer()`, `interrupt()`, `pullThread()`.

Mirror the exact event contract from `specs/02-phase-2-companion.md` (`say`, `ask`,
`node.create`, `node.update`, `edge.create`, `status`, `done`).

## Voice staging (don't oversell)

- **Tier 1 (this phase):** text streaming — `say` rendered as streamed text. Ships now.
- **Tier 2 (optional):** TTS on `say` output (Web Speech API or a TTS service).
- **Tier 3 (later):** full duplex — streaming STT + voice-activity detection + clean barge-in
  mapped to `interrupt`. Hard; build last. Local models cover the latency-sensitive turns.

---

## Acceptance criteria

- [ ] Auth flow works against the `identity` seam; protected routes redirect when unauthenticated.
- [ ] `/library` lists the 3 seeded LeCun spines; **Check out** lands on `/learn/[id]`.
- [ ] On the canvas, the Foundations spine renders with its path highlighted and lateral nodes faded.
- [ ] Sending a subject streams `node.create`/`edge.create` that appear live; `node.update`
      reconciles temp ids without flicker.
- [ ] An `ask` event pauses the flow and renders quick-reply chips; answering resumes it.
- [ ] Opening a node shows `hook` before `body`; **pull this thread** spawns a rabbit-hole branch.
- [ ] Light/dark toggle flips the whole UI via tokens with no hardcoded-color leaks; persists across reloads.
- [ ] Reconnecting the WS restores canvas + transcript state.

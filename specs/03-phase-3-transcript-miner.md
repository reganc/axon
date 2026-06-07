# Phase 3 — The Transcript Miner: turn your own learning history into library content

**Goal:** ingest months of Claude Code / Claude conversations into the same canonical graph,
so the library is seeded not just with authored courses but with what the user actually
explored. Same canonicalize-and-persist loop as Phase 1/2 — a different *ingestion profile*
for noisy, exploratory input.

**Runnable result:** point the miner at an Obsidian export (or `~/.claude/projects/**.jsonl`),
and it produces grounded concept nodes that **merge with the existing library** (so a topic
learned in a course and later explored in Claude Code becomes one enriched node, not two).

---

## Context (verified facts)

- Claude Code writes a full JSONL transcript per session to
  `~/.claude/projects/<url-encoded-project-path>/<session-id>.jsonl`. Each line is a JSON
  object: user message, assistant message (content blocks: text / tool_use / thinking),
  tool_result, or metadata. Records chain via `parentUuid`.
- **Default retention is 30 days** (`cleanupPeriodDays`); raw history evaporates unless
  mirrored. The user's comet-observer daemon + Obsidian vault already mirror these — treat
  the **Obsidian markdown as the primary input** (already de-noised) and keep the JSONL path
  as `source.uri` for provenance.
- `/export` and `sessions-index.json` (summaries, timestamps, git branch per session) are
  useful adjuncts.

## Scope

**In:** `ingestion` transcript profile — parser, segmenter, concept extractor, redactor,
grounding hand-off to the Researcher, batch CLI/worker.
**Out:** real-time ingestion (batch is fine); UI for browsing provenance (Phase 4).

## Source kinds

Add to `sources.kind`: `claude_code_transcript` (JSONL), `obsidian_note` (md).

## Pipeline (`IngestionPort.mine_transcripts`)

```python
class IngestionPort(Protocol):
    # ...Phase 1 methods...
    async def mine(self, source_kind: str, path: str) -> IngestReport: ...
```

1. **Parse.** JSONL: rebuild the thread via `parentUuid`; keep `user` + `assistant` *text*
   blocks; **drop tool_use/tool_result bodies** (file dumps, bash output) — keep only that a
   tool was used (signal, not payload). Obsidian: parse markdown; headings/links are structure.
2. **Redact (mandatory, before anything is persisted).** Transcripts contain tool inputs and
   env — scrub secrets: API keys, tokens, `.env` values, private paths, anything matching
   common secret patterns. A leaked key canonized into the library is a real incident. Redaction
   runs *before* embedding or storage; log a redaction count per source.
3. **Segment.** Split a session into topic spans (a sustained back-and-forth about one thing).
   Use `sessions-index.json` summaries + embedding-based change-point detection. Discard
   debugging churn and dead-ends (low-coherence spans).
4. **Extract candidates.** For each topic span → `LLMPort.complete(tier=reason)` → a
   `CandidateNode` (title, hook, body, recall_prompts). Mark `origin='ai_generated'`,
   `source_ref` = `session-id#span`.
5. **Ground (Researcher).** Same grounding gate as Phase 2 — verify against sources, set
   `confidence`. **Conversations are not authority**: a thing the user and an AI discussed is
   a *lead*, not a fact. Below the confidence floor → store as a low-confidence node flagged
   for review, never as settled content.
6. **Canonicalize & persist.** Through the Phase-1 routine. This is where the merge magic
   happens: a Claude Code exploration of "pgvector indexing" merges into / enriches any
   existing library node on the topic instead of duplicating.
7. **Edges.** Within-session topic adjacency → `rabbit_hole`/`elaborates` edges; reconstruct
   "this led to that" from the thread order.

## Privacy & ownership

This is the user's personal library of their own data — no third-party concern. Still: keep
mined nodes attributable (`source_ref`), make redaction non-optional, and support a
per-source purge (delete a session's derived nodes/edges by `source_ref`).

---

## Acceptance criteria

- [ ] `mine('obsidian_note', <vault-path>)` produces grounded `CandidateNode`s → canonical nodes.
- [ ] Redaction removes seeded fake secrets (test with a planted API-key string) **before** persist;
      redaction count is reported.
- [ ] Tool_use/tool_result payloads are excluded from node bodies.
- [ ] A mined concept that overlaps a seeded LeCun node (e.g. a JEPA discussion) **merges**
      (`action=merged`) rather than creating a duplicate.
- [ ] Low-coherence/debugging spans are dropped (verify on a known-noisy session).
- [ ] Mined nodes carry `confidence` and `source_ref`; sub-floor nodes are flagged, not published as fact.
- [ ] Purge-by-source removes a session's derived nodes/edges and leaves authored nodes untouched.

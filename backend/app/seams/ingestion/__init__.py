"""ingestion seam — the canonicalize-and-persist chokepoint + the seed loader.

Phase 1. `canonicalize` is the single most important routine in the system: it is
deterministic and idempotent so re-ingesting the same idea never duplicates the
library. Both the seed loader (P1) and live companion generation (P2) funnel
through it. The transcript miner (`mine`) is Phase 3.

Decision (similarity s = 1 - cosine_distance to the nearest neighbor):
  - exact canonical-key match, or s >= merge_threshold  -> MERGE
      * neighbor locked   -> never modify it; return it (attach lateral context
        edge if a context node is supplied), action="merged"
      * neighbor unlocked -> version += 1, origin="ai_extended", action="merged"
  - related_threshold <= s < merge_threshold  -> CREATE + 'elaborates' edge to neighbor
  - s < related_threshold (or empty library) -> CREATE standalone
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

from ...config import Settings, get_settings
from ...embeddings import Embedder
from ...ports import CandidateNode, CanonResult, IngestReport, LLMPort, Msg, NodeIn
from ..content import Content
from . import miner

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_SOURCE_KINDS = {"claude_code_transcript", "obsidian_note"}


def normalize_key(text: str) -> str:
    """Deterministic slug used as the dedup key."""
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")


class Ingestion:
    def __init__(
        self,
        content: Content,
        embedder: Embedder,
        settings: Settings | None = None,
        llm: LLMPort | None = None,
    ) -> None:
        self._content = content
        self._embed = embedder
        self._s = settings or get_settings()
        self._llm = llm  # required for mine(); optional for canonicalize/seed

    # -- canonicalize ---------------------------------------------------------

    async def canonicalize(
        self, candidate: CandidateNode, *, context_node: UUID | None = None
    ) -> CanonResult:
        key = normalize_key(candidate.title)
        emb = await self._embed.embed(
            f"{candidate.hook or ''}\n\n{candidate.body or ''}".strip()
        )

        exact = await self._content.get_node_by_key(key)
        neighbor = await self._content.nearest(emb, exclude_key=key)
        neighbor_sim = (1.0 - neighbor[1]) if neighbor else 0.0

        merge_target = None
        if exact is not None:
            merge_target = exact
        elif neighbor is not None and neighbor_sim >= self._s.canon_merge_threshold:
            merge_target = neighbor[0]

        if merge_target is not None:
            if merge_target.locked:
                # Authored anchor: augment around it, never overwrite. Attach a
                # lateral edge only when we have a context node to attach from.
                if context_node is not None:
                    await self._content.add_edge(
                        context_node,
                        merge_target.id,
                        "elaborates",
                        origin="ai_generated",
                    )
                return CanonResult(
                    node=merge_target, action="merged", neighbor_id=merge_target.id
                )
            updated = await self._content.bump_version(
                merge_target.canonical_key, origin="ai_extended", embedding=emb
            )
            return CanonResult(
                node=updated, action="merged", neighbor_id=merge_target.id
            )

        # CREATE path
        node_in = NodeIn(
            canonical_key=key,
            title=candidate.title,
            kind=candidate.kind,
            hook=candidate.hook,
            body=candidate.body,
            recall_prompts=candidate.recall_prompts,
            origin=candidate.origin,
            source_ref=candidate.source_ref,
            confidence=candidate.confidence,
        )
        created = await self._content.upsert_node(node_in, embedding=emb)

        relate_id: UUID | None = None
        if neighbor is not None and neighbor_sim >= self._s.canon_related_threshold:
            await self._content.add_edge(
                created.id, neighbor[0].id, "elaborates", origin="ai_generated"
            )
            relate_id = neighbor[0].id
        if context_node is not None:
            await self._content.add_edge(
                context_node, created.id, "rabbit_hole", origin="ai_generated"
            )
        return CanonResult(node=created, action="created", neighbor_id=relate_id)

    # -- seed loader ----------------------------------------------------------

    async def ingest_seed(self, path: str) -> IngestReport:
        """Load lecun_seed_graph.json verbatim (authored, locked) with computed
        embeddings. Idempotent: explicit ids + ON CONFLICT DO NOTHING, and we skip
        embedding work for nodes already present."""
        data = json.loads(_resolve(path).read_text())
        report = IngestReport()

        for src in data.get("sources", []):
            if await self._content.seed_source(src):
                pass  # sources aren't counted in the report's headline numbers

        nodes = data.get("nodes", [])
        present = await self._content.existing_node_ids([UUID(n["id"]) for n in nodes])
        for n in nodes:
            if UUID(n["id"]) in present:
                continue
            emb = await self._embed.embed(
                f"{n.get('hook') or ''}\n\n{n.get('body') or ''}".strip() or n["title"]
            )
            if await self._content.seed_node(n, emb):
                report.nodes += 1

        for e in data.get("edges", []):
            if await self._content.seed_edge(e):
                report.edges += 1

        for sp in data.get("spines", []):
            if await self._content.seed_spine(sp):
                report.spines += 1

        return report

    # -- transcript miner (Phase 3) -------------------------------------------

    async def mine(self, source_kind: str, path: str) -> IngestReport:
        """Mine a Claude Code transcript or Obsidian note into the canonical graph.

        parse -> redact (before any embed/persist) -> segment -> drop churn ->
        extract -> ground -> canonicalize -> within-source adjacency edges.
        Returns an IngestReport: nodes created, merged, edges, and the redaction
        count (secrets scrubbed before persistence).
        """
        if source_kind not in _SOURCE_KINDS:
            raise ValueError(
                f"unknown source kind: {source_kind!r} (expected {_SOURCE_KINDS})"
            )
        if self._llm is None:
            raise RuntimeError("mine() requires an LLM gateway; none was wired")

        p = Path(path)
        raw = p.read_text() if p.is_file() else path  # accept inline content in tests
        tag = p.stem if p.is_file() else "inline"
        report = IngestReport()

        # parse -> redact (mandatory, before embeddings or storage)
        if source_kind == "claude_code_transcript":
            turns = miner.parse_claude_jsonl(raw)
            for t in turns:
                t.text, n = miner.redact(t.text)
                report.redacted += n
            spans = await miner.segment_turns(turns, self._embed, self._s)
        else:  # obsidian_note
            spans = []
            for section in miner.parse_obsidian(raw):
                clean, n = miner.redact(section.text)
                report.redacted += n
                spans.append(clean)

        await self._content.seed_source(
            {"id": None, "kind": source_kind, "title": tag, "uri": str(p)}
        )

        extractor = miner.TranscriptExtractor(self._llm)
        prev_id: UUID | None = None
        kept = 0
        for i, span_text in enumerate(spans):
            if kept >= self._s.miner_max_spans:
                break
            if not miner.keep_span(span_text, self._s):
                continue
            candidate = await extractor.extract(span_text, source_ref=f"{tag}#span{i}")
            candidate = await self._ground(candidate)
            result = await self.canonicalize(candidate)
            if result.action == "created":
                report.nodes += 1
            else:
                report.merged += 1
            if prev_id is not None and prev_id != result.node.id:
                await self._content.add_edge(
                    prev_id, result.node.id, "rabbit_hole", origin="ai_generated"
                )
                report.edges += 1
            prev_id = result.node.id
            kept += 1

        return report

    async def _ground(self, candidate: CandidateNode) -> CandidateNode:
        """Grounding gate (Researcher-equivalent, ingestion-local so this seam stays
        independent of companion). A conversation is a lead, not authority."""
        msgs = [
            Msg(
                role="system",
                content="You judge how well-grounded a mined explanation is; assign a calibrated confidence in [0,1].",
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: ground\nTitle: {candidate.title}\nBody: {candidate.body}\n"
                    'Return JSON only: {"confidence": 0.0-1.0, "source_ref": "..."}'
                ),
            ),
        ]
        from ...jsonutil import parse_json

        data = parse_json(await self._llm.complete(msgs, "reason"))
        data = data if isinstance(data, dict) else {}
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return candidate.model_copy(update={"confidence": confidence})

    async def purge_by_source(self, source_tag: str) -> int:
        """Delete mined nodes (and their cascading edges) derived from a source,
        identified by their `source_ref` prefix `"{tag}#"`. Authored/locked nodes
        are never touched."""
        return await self._content.delete_unlocked_by_source_prefix(f"{source_tag}#")


def _resolve(path: str) -> Path:
    """Resolve a seed path against the cwd and the repo's artifacts dir.

    Containers run from /app (backend), so 'artifacts/...' lives one level up.
    Try the path as-given first, then a couple of sensible bases.
    """
    p = Path(path)
    if p.is_file():
        return p
    here = Path(__file__).resolve()
    # backend/app/seams/ingestion/__init__.py -> repo root is parents[4]
    for base in (here.parents[4], here.parents[3].parent):
        cand = base / path
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"seed file not found: {path}")


# Back-compat alias for deps.py during the stub→real swap.
StubIngestion = Ingestion

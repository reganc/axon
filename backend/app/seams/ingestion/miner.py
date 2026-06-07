"""Transcript miner — Phase 3 ingestion profile for noisy, exploratory input.

Turns Claude Code JSONL transcripts and Obsidian notes into grounded concept
candidates that flow through the same Phase-1 canonicalizer. The pipeline:

  parse -> redact (mandatory, before anything is embedded or stored)
        -> segment into topic spans -> drop low-coherence churn
        -> extract a CandidateNode per span -> (caller grounds + canonicalizes)

Redaction is non-optional: a transcript carries tool inputs and env, and a key
canonized into the library is a real incident. tool_use / tool_result payloads
(file dumps, bash output) are dropped at parse time — we keep that a tool was
used as signal, never the payload.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

from ...config import Settings
from ...embeddings import Embedder
from ...jsonutil import parse_json
from ...ports import CandidateNode, LLMPort, Msg

log = logging.getLogger("axon.miner")

# ---------------------------------------------------------------------------
# Redaction — scrub secrets before anything is embedded or persisted.
# ---------------------------------------------------------------------------
_REDACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "«redacted:openai-key»"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"), "«redacted:anthropic-key»"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "«redacted:aws-key»"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "«redacted:github-token»"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "«redacted:github-pat»"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "«redacted:google-key»"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "«redacted:slack-token»"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "«redacted:jwt»",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}"), "Bearer «redacted:token»"),
    # KEY=VALUE / KEY: VALUE for secret-ish names (.env lines, configs)
    (
        re.compile(
            r"(?im)\b([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|API)[A-Z0-9_]*)\s*[:=]\s*['\"]?([^\s'\"]+)"
        ),
        r"\1=«redacted:secret»",
    ),
    # private home paths
    (re.compile(r"/(?:home|Users)/[^/\s]+"), "/home/«user»"),
]


def redact(text: str) -> tuple[str, int]:
    """Scrub secrets. Returns (clean_text, redaction_count)."""
    count = 0
    out = text
    for pattern, repl in _REDACTIONS:
        out, n = pattern.subn(repl, out)
        count += n
    return out, count


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    role: str
    text: str


def _blocks_to_text(content) -> str:
    """Join text blocks; drop tool_use / tool_result / thinking payloads."""
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def parse_claude_jsonl(raw: str) -> list[Turn]:
    """One Turn per user/assistant *text* message. Records chain by parentUuid in
    file order (Claude Code writes chronologically); meta/sidechain records and
    tool payloads are dropped."""
    turns: list[Turn] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _blocks_to_text(message.get("content"))
        if text:
            turns.append(Turn(role=role, text=text))
    return turns


@dataclass
class Section:
    heading: str
    text: str


def parse_obsidian(raw: str) -> list[Section]:
    """Split a note into sections by markdown headings (its natural topic spans)."""
    sections: list[Section] = []
    heading = ""
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(heading=heading, text=body))

    for line in raw.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            flush()
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections or [Section(heading="", text=raw.strip())]


# ---------------------------------------------------------------------------
# Segmentation (embedding change-point) + coherence filter
# ---------------------------------------------------------------------------
def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0
    )


async def segment_turns(
    turns: list[Turn], embedder: Embedder, settings: Settings
) -> list[str]:
    """Group consecutive turns into topic spans by embedding change-point: a new
    span starts when a turn's similarity to the previous drops below threshold."""
    texts = [t.text for t in turns]
    if len(texts) <= 1:
        return ["\n\n".join(texts)] if texts else []
    embeds = [await embedder.embed(t) for t in texts]
    groups: list[list[int]] = [[0]]
    for i in range(1, len(texts)):
        if _cosine(embeds[i], embeds[i - 1]) < settings.miner_segment_threshold:
            groups.append([])
        groups[-1].append(i)
    return ["\n\n".join(texts[i] for i in g) for g in groups]


def keep_span(text: str, settings: Settings) -> bool:
    """Drop debugging churn / dead-ends: spans below the minimum length."""
    return len(text.strip()) >= settings.miner_min_span_chars


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
class TranscriptExtractor:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def extract(self, span_text: str, source_ref: str) -> CandidateNode:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's miner. Distil a span of exploratory conversation "
                    "into one reusable concept node: a curiosity hook, a tight "
                    "explanation, and recall prompts. A conversation is a lead, not "
                    "authority — stay faithful to what was actually established."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: extract\nSpan:\n{span_text[:4000]}\n"
                    'Return JSON only: {"title": "...", "hook": "...", "body": "...", '
                    '"recall_prompts": ["..."]}'
                ),
            ),
        ]
        data = parse_json(await self._llm.complete(msgs, "reason"))
        data = data if isinstance(data, dict) else {}
        rp = data.get("recall_prompts") or []
        return CandidateNode(
            title=(data.get("title") or "Untitled mined concept").strip(),
            hook=(data.get("hook") or None),
            body=(data.get("body") or None),
            recall_prompts=[str(p) for p in rp][:5],
            origin="ai_generated",
            source_ref=source_ref,
        )

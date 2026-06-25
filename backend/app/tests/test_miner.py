"""transcript miner — Phase 3 (parse/redact/segment/extract/ground/canonicalize)."""

from __future__ import annotations

import json
from uuid import uuid4

from app.config import Settings
from app.ports import Msg
from app.seams.ingestion import miner

from .conftest import make_miner, requires_db, scalar

# ---------------------------------------------------------------------------
# Unit: redaction + parsing + coherence (no DB, no model)
# ---------------------------------------------------------------------------

SECRETS_BLOB = (
    "here is my openai key sk-AAAABBBBCCCCDDDDEEEE1234 and an aws key "
    "AKIAIOSFODNN7EXAMPLE plus a github token ghp_0123456789abcdefghijABCDEFGHIJ012345 "
    "and OPENAI_API_KEY=supersecretvalue living in /home/regan/.env"
)


def test_redact_scrubs_known_secret_shapes():
    clean, count = miner.redact(SECRETS_BLOB)
    assert count >= 4
    for leak in (
        "sk-AAAA",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_0123",
        "supersecretvalue",
        "/home/regan",
    ):
        assert leak not in clean
    assert "redacted" in clean


def test_parse_jsonl_keeps_text_drops_tool_payloads():
    lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "How does pgvector indexing work?"},
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "It uses IVFFlat lists."},
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "cat /etc/passwd"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "root:x:0:0:SECRET_DUMP"}
                ],
            },
        },
    ]
    raw = "\n".join(json.dumps(x) for x in lines)
    turns = miner.parse_claude_jsonl(raw)
    texts = " ".join(t.text for t in turns)
    assert "pgvector" in texts
    assert "IVFFlat" in texts
    assert "SECRET_DUMP" not in texts  # tool_result payload dropped
    assert "/etc/passwd" not in texts  # tool_use input dropped


def test_parse_obsidian_splits_by_headings():
    md = "# Title\nintro\n\n## A\nbody a\n\n## B\nbody b"
    sections = miner.parse_obsidian(md)
    headings = [s.heading for s in sections]
    assert "A" in headings and "B" in headings


def test_keep_span_drops_short_churn():
    s = Settings(miner_min_span_chars=140)
    assert miner.keep_span("x" * 200, s) is True
    assert miner.keep_span("it crashed. try again. still broken.", s) is False


# ---------------------------------------------------------------------------
# Integration: mine -> ground -> canonicalize -> persist (DB + scripted LLM)
# ---------------------------------------------------------------------------


def _extract_ground_handler(title_for, confidence=0.8, low_conf_keywords=()):
    """Scripted LLM for the miner: extract a span -> node, ground -> confidence."""

    def handler(msgs):
        user = next((m.content for m in msgs if m.role == "user"), "")
        if "TASK: ground" in user:
            conf = (
                0.3
                if any(k.lower() in user.lower() for k in low_conf_keywords)
                else confidence
            )
            return json.dumps({"confidence": conf, "source_ref": "test://mined"})
        if "TASK: extract" in user:
            title = title_for(user)
            return json.dumps(
                {
                    "title": title,
                    "hook": f"Why does {title} matter?",
                    "body": f"A mined explanation of {title}.",
                    "recall_prompts": [f"What is {title}?"],
                }
            )
        return "OK"

    return handler


@requires_db
async def test_mine_obsidian_creates_grounded_nodes(seeded, seams, tmp_path):
    note = tmp_path / "session-notes.md"
    note.write_text(
        "## Vector search internals\n"
        "We dug into how approximate nearest neighbour search works with IVFFlat "
        "lists and how recall trades off against probe count in a vector index.\n"
    )
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Vector index recall tradeoffs")
    )

    report = await ing.mine("obsidian_note", str(note))
    assert report.nodes >= 1
    node = await seams.content.get_node_by_key("vector-index-recall-tradeoffs")
    assert node is not None
    assert node.origin in ("ai_generated", "ai_extended")
    assert node.source_ref and node.source_ref.startswith("session-notes#")
    assert abs(node.confidence - 0.8) < 0.02


@requires_db
async def test_redaction_runs_before_persist(seeded, seams, tmp_path):
    note = tmp_path / "leaky.md"
    note.write_text(
        "## Deploy notes\n"
        "I set OPENAI_API_KEY=sk-LEAKED9999999999999999 in the shell while debugging "
        "the deployment pipeline and the vector store connection settings.\n"
    )
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Deployment secret handling")
    )

    report = await ing.mine("obsidian_note", str(note))
    assert report.redacted >= 1
    # the secret never reaches a stored body
    leaked = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE body LIKE '%sk-LEAKED%' OR hook LIKE '%sk-LEAKED%'"
    )
    assert leaked == 0


@requires_db
async def test_tool_payloads_never_reach_node_bodies(seeded, seams, tmp_path):
    lines = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Walk me through how the canonicalizer decides to merge versus create a node.",
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "It embeds the candidate and compares cosine similarity to the nearest neighbour, "
                        "merging above a threshold and creating a related node otherwise.",
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "echo TOOLDUMP_MARKER_XYZ"},
                    },
                ],
            },
        },
    ]
    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in lines))
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Canonicalizer merge decision")
    )

    await ing.mine("claude_code_transcript", str(transcript))
    dumped = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE body LIKE '%TOOLDUMP_MARKER_XYZ%'"
    )
    assert dumped == 0


@requires_db
async def test_mined_concept_merges_with_seeded_locked_node(seeded, seams, tmp_path):
    note = tmp_path / "jepa-thoughts.md"
    note.write_text(
        "## JEPA\n"
        "Spent the evening reading about JEPA — joint embedding predictive architectures — "
        "and how they predict in representation space rather than pixel space, which is the "
        "core of LeCun's world-model programme.\n"
    )
    # extractor returns the exact concept name -> normalizes to the seeded key 'jepa'
    ing = make_miner(seams, _extract_ground_handler(lambda _u: "JEPA"))

    before = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE canonical_key = 'jepa'"
    )
    report = await ing.mine("obsidian_note", str(note))
    after = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE canonical_key = 'jepa'"
    )

    assert report.merged >= 1
    assert before == 1 and after == 1  # merged into the locked anchor, not duplicated
    jepa = await seams.content.get_node_by_key("jepa")
    assert jepa.locked is True and jepa.version == 1  # locked anchor untouched


@requires_db
async def test_low_coherence_churn_is_dropped(seeded, seams, tmp_path):
    lines = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Explain how spaced repetition scheduling decides the next review interval from a "
                "mastery estimate, and why intervals expand as mastery grows over time.",
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": "Higher mastery maps to a longer interval; an SM-2-style curve expands the gap each "
                "successful recall while a lapse shortens it again, so review effort tracks forgetting.",
            },
        },
        {"type": "user", "message": {"role": "user", "content": "it crashed"}},
        {"type": "user", "message": {"role": "user", "content": "try again"}},
        {"type": "user", "message": {"role": "user", "content": "still broken ugh"}},
    ]
    transcript = tmp_path / "noisy-session.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in lines))
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Spaced repetition intervals")
    )

    report = await ing.mine("claude_code_transcript", str(transcript))
    # the substantive span is mined; the short debugging churn is dropped
    assert report.nodes + report.merged <= 2
    assert report.nodes + report.merged >= 1


@requires_db
async def test_subfloor_confidence_is_flagged(seeded, seams, tmp_path):
    note = tmp_path / "speculation.md"
    note.write_text(
        "## Speculative tangent\n"
        "A half-formed speculative idea about consciousness in transformers that we never "
        "actually verified or grounded in any source during the conversation.\n"
    )
    ing = make_miner(
        seams,
        _extract_ground_handler(
            lambda _u: "Speculative transformer consciousness",
            low_conf_keywords=["speculative"],
        ),
    )
    await ing.mine("obsidian_note", str(note))
    node = await seams.content.get_node_by_key("speculative-transformer-consciousness")
    assert node is not None
    assert (
        node.confidence < Settings().companion_confidence_floor
    )  # flagged, not settled fact


@requires_db
async def test_mine_turns_distils_a_live_dialogue(seeded, seams):
    """The companion's live-mining entry point: a learner/tutor transcript runs the
    same extract -> ground -> canonicalize pipeline and accretes a grounded node."""
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Attention in transformers")
    )
    tag = f"session-{uuid4()}"
    turns = [
        Msg(
            role="user",
            content="Why does self-attention model long-range dependencies that an "
            "RNN struggles to carry across many time steps?",
        ),
        Msg(
            role="assistant",
            content="Every token attends directly to every other token in a single "
            "step, so a dependency between distant positions is one hop rather than "
            "a signal carried through many recurrent steps where it can vanish.",
        ),
    ]

    report = await ing.mine_turns(turns, tag)

    assert report.nodes + report.merged >= 1
    node = await seams.content.get_node_by_key("attention-in-transformers")
    assert node is not None
    assert node.origin in ("ai_generated", "ai_extended")
    assert node.source_ref and node.source_ref.startswith(f"{tag}#")


@requires_db
async def test_mine_turns_redacts_before_persist(seeded, seams):
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Session secret handling")
    )
    turns = [
        Msg(
            role="user",
            content="I pasted OPENAI_API_KEY=sk-LEAKEDsession9999999999 into the chat "
            "while we debugged the deployment and the vector store wiring.",
        ),
        Msg(
            role="assistant",
            content="Never paste a live key into a prompt — rotate it immediately and "
            "load it from the environment so secrets stay out of any stored transcript.",
        ),
    ]

    report = await ing.mine_turns(turns, "session-leak")
    assert report.redacted >= 1
    leaked = await scalar(
        "SELECT count(*) FROM canonical_nodes "
        "WHERE body LIKE '%sk-LEAKEDsession%' OR hook LIKE '%sk-LEAKEDsession%'"
    )
    assert leaked == 0


@requires_db
async def test_purge_by_source_removes_derived_leaves_authored(seeded, seams, tmp_path):
    note = tmp_path / "purge-me.md"
    note.write_text(
        "## Disposable note\n"
        "A throwaway exploration about queue backpressure and how bounded channels shed load "
        "under sustained overload, written only to be purged in this test.\n"
    )
    ing = make_miner(
        seams, _extract_ground_handler(lambda _u: "Queue backpressure under overload")
    )
    await ing.mine("obsidian_note", str(note))

    assert (
        await seams.content.get_node_by_key("queue-backpressure-under-overload")
        is not None
    )
    authored_before = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE origin = 'authored'"
    )

    deleted = await ing.purge_by_source("purge-me")
    assert deleted >= 1
    assert (
        await seams.content.get_node_by_key("queue-backpressure-under-overload") is None
    )
    authored_after = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE origin = 'authored'"
    )
    assert authored_after == authored_before  # authored anchors untouched

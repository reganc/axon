"""Evidence-based grounding: deterministic verdict scoring + the Researcher's
use of it. The model only reports per-claim verdicts (judged against the
search-injected lane's evidence); confidence is computed here, never
self-reported — a model grading its own homework is the failure mode this
replaces."""

from __future__ import annotations

import json

import pytest

from app.grounding import score_verdicts
from app.ports import CandidateNode, Msg
from app.seams.companion.agents import Researcher


def _claims(*verdicts: str, source: str = "") -> list[dict]:
    return [
        {"claim": f"c{i}", "verdict": v, "source": source}
        for i, v in enumerate(verdicts)
    ]


# ---------------------------------------------------------------------------
# score_verdicts — pure scoring rules
# ---------------------------------------------------------------------------


def test_all_supported_is_full_confidence():
    conf, _ = score_verdicts(_claims("supported", "supported", "supported"))
    assert conf == 1.0


def test_any_contradiction_caps_below_publish_floor():
    conf, _ = score_verdicts(_claims("supported", "supported", "contradicted"))
    assert conf <= 0.3  # flagged for review, never published as settled fact


def test_unverifiable_dilutes_toward_half():
    conf, _ = score_verdicts(_claims("supported", "unverifiable"))
    assert conf == pytest.approx(0.75)
    conf, _ = score_verdicts(_claims("unverifiable", "unverifiable"))
    assert conf == pytest.approx(0.5)


def test_supported_sources_are_collected_deduped_and_http_only():
    claims = [
        {"claim": "a", "verdict": "supported", "source": "https://example.org/x"},
        {"claim": "b", "verdict": "supported", "source": "https://example.org/x"},
        {"claim": "c", "verdict": "contradicted", "source": "https://bad.example"},
        {"claim": "d", "verdict": "supported", "source": "not-a-url"},
    ]
    _, sources = score_verdicts(claims)
    assert sources == ["https://example.org/x"]


def test_malformed_input_falls_back():
    assert score_verdicts(None) == (0.5, [])
    assert score_verdicts("nope") == (0.5, [])
    assert score_verdicts([{"verdict": "maybe"}, 42]) == (0.5, [])
    assert score_verdicts([], fallback=0.4) == (0.4, [])


# ---------------------------------------------------------------------------
# Researcher.ground — uses the search lane, scores deterministically
# ---------------------------------------------------------------------------


class _StubLLM:
    """Records the tier so the test can prove grounding stays on the fast
    (search-injected) lane, and replies with a scripted body."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.tiers: list[str] = []

    async def complete(self, msgs: list[Msg], tier: str, **kwargs) -> str:
        self.tiers.append(tier)
        return self.reply


def _candidate() -> CandidateNode:
    return CandidateNode(
        title="Backpropagation",
        body="Gradients flow backwards through the chain rule.",
        origin="ai_generated",
        source_ref="companion/deep learning",
    )


@pytest.mark.asyncio
async def test_ground_scores_verdicts_and_adopts_supporting_source():
    llm = _StubLLM(
        json.dumps(
            {
                "claims": [
                    {
                        "claim": "chain rule",
                        "verdict": "supported",
                        "source": "https://en.wikipedia.org/wiki/Backpropagation",
                    },
                    {"claim": "flows backwards", "verdict": "supported", "source": ""},
                ]
            }
        )
    )
    out = await Researcher(llm).ground(_candidate())
    assert llm.tiers == ["fast"]  # the search-injected lane, never the blind one
    assert out.confidence == 1.0
    assert out.source_ref == "https://en.wikipedia.org/wiki/Backpropagation"


@pytest.mark.asyncio
async def test_ground_contradiction_flags_the_node():
    llm = _StubLLM(
        json.dumps(
            {
                "claims": [
                    {"claim": "x", "verdict": "supported", "source": ""},
                    {"claim": "y", "verdict": "contradicted", "source": ""},
                ]
            }
        )
    )
    out = await Researcher(llm).ground(_candidate())
    assert out.confidence <= 0.3
    assert out.source_ref == "companion/deep learning"  # nothing better found


@pytest.mark.asyncio
async def test_ground_tolerates_legacy_self_reported_shape():
    llm = _StubLLM(json.dumps({"confidence": 0.8, "source_ref": "test://grounded"}))
    out = await Researcher(llm).ground(_candidate())
    assert out.confidence == 0.8
    assert out.source_ref == "test://grounded"


@pytest.mark.asyncio
async def test_ground_garbage_reply_degrades_to_half():
    out = await Researcher(_StubLLM("not json at all")).ground(_candidate())
    assert out.confidence == 0.5

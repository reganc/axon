"""Delivery-level conditioning (no DB, no network).

These pin the integrity-critical contract: the level reaches the *talk* agents'
system prompt but the canonical-write agents never see it. The talk agents are
exercised with a capturing stub LLM so we can assert exactly what was prompted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

from app.ports import Msg
from app.seams.companion.agents import Conversationalist, Elaborator, NodeGenerator
from app.seams.companion.levels import VALID_LEVELS, level_clause


class _CapturingLLM:
    """Records the messages of the most recent call to stream/complete."""

    def __init__(self) -> None:
        self.last_msgs: list[Msg] | None = None

    def stream(self, msgs: list[Msg], tier: str) -> AsyncIterator[str]:
        self.last_msgs = msgs

        async def _gen() -> AsyncIterator[str]:
            yield "ok."

        return _gen()

    async def complete(self, msgs: list[Msg], tier: str, **kw) -> str:
        self.last_msgs = msgs
        return "{}"

    async def embed(self, text: str) -> list[float]:
        return [0.0]


_NODE = SimpleNamespace(
    title="Backpropagation", hook="how nets learn", body="chain rule over layers"
)


def _sys(llm: _CapturingLLM) -> str:
    assert llm.last_msgs is not None
    return llm.last_msgs[0].content


def test_level_clause_maps_each_tier_and_degrades_unknown():
    assert "ten-year-old" in level_clause("kid")
    assert "high-school" in level_clause("high_school")
    assert "undergraduate" in level_clause("undergrad")
    assert "expert practitioner" in level_clause("expert")
    # the accuracy invariant rides along on every leveled clause
    for lvl in VALID_LEVELS:
        assert "identically accurate" in level_clause(lvl)
    # none / unknown -> no conditioning at all
    assert level_clause(None) == ""
    assert level_clause("") == ""
    assert level_clause("phd-in-basket-weaving") == ""


def test_explain_injects_level_into_talk_prompt():
    llm = _CapturingLLM()
    el = Elaborator(llm)

    el.explain(_NODE, level="kid")
    assert "ten-year-old" in _sys(llm)
    assert "identically accurate" in _sys(llm)

    el.explain(_NODE)  # default: no level -> baseline prompt, no clause
    assert "ten-year-old" not in _sys(llm)
    assert "identically accurate" not in _sys(llm)


def test_reply_injects_level_into_talk_prompt():
    llm = _CapturingLLM()
    cv = Conversationalist(llm)

    cv.reply(_NODE, [], "why does it work?", level="expert")
    assert "expert practitioner" in _sys(llm)

    cv.reply(_NODE, [], "why does it work?")  # default None
    assert "expert practitioner" not in _sys(llm)


async def test_extract_concept_is_never_leveled():
    """The canonical-write trigger must stay level-neutral: extract_concept takes
    no level and its prompt carries no delivery clause, so a dumbed-down chat can
    never dumb down what gets persisted."""
    llm = _CapturingLLM()
    cv = Conversationalist(llm)
    await cv.extract_concept(_NODE, "huh?", "a simple answer for a kid")
    for lvl in VALID_LEVELS:
        assert level_clause(lvl).strip() not in _sys(llm)


async def test_node_generator_is_never_leveled():
    """The generator that produces canonical bodies takes no level parameter."""
    llm = _CapturingLLM()
    gen = NodeGenerator(llm)
    await gen.generate("Backpropagation", "neural networks")
    for lvl in VALID_LEVELS:
        assert level_clause(lvl).strip() not in _sys(llm)

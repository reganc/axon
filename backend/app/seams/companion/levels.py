"""levels.py — delivery-level conditioning for the companion's *talk* layer.

A learner can pick how an explanation is pitched (kid → expert). This shapes
ONLY the ephemeral spoken/streamed talk — deep-dive explanations and discussion
replies — by appending a clause to those agents' system prompt. The
canonical-write agents (generate / ground / materials / extract_concept) never
receive it, so the shared corpus is byte-for-byte identical for every learner
regardless of the level they read it at. See specs/00 principle #6: talk is the
experience layer; the canonical loop is the source of truth.

The level is a transient, per-session presentation hint carried over the WS — not
a persisted attribute and not a validated boundary input. Unknown values degrade
to no conditioning rather than failing a turn.
"""

from __future__ import annotations

from typing import Literal

DeliveryLevel = Literal["kid", "high_school", "undergrad", "expert"]

# How to pitch the delivery. Each clause shifts vocabulary, assumed background,
# and examples — never the facts.
_LEVELS: dict[str, str] = {
    "kid": (
        "Pitch this for a curious ten-year-old: short sentences, everyday words, "
        "and vivid concrete examples. Avoid jargon; if a technical term is "
        "unavoidable, define it in plain language right away."
    ),
    "high_school": (
        "Pitch this for a high-school student: accessible language, define jargon "
        "on first use, and lean on relatable analogies. Assume basic math and "
        "science but no specialization."
    ),
    "undergrad": (
        "Pitch this for a university undergraduate in the field: use standard "
        "terminology, assume the usual foundational background, and include some "
        "formalism where it sharpens the idea."
    ),
    "expert": (
        "Pitch this for an expert practitioner: be dense and precise, use "
        "field-standard terminology without defining the basics, and focus on "
        "nuance, edge cases, and connections to advanced ideas."
    ),
}

VALID_LEVELS = frozenset(_LEVELS)

# Stated on every leveled prompt so simplifying never licenses being wrong.
_INVARIANT = (
    " Adjust only the vocabulary, depth, and examples for this audience — never "
    "the facts. The content is identically accurate at every level."
)


def level_clause(level: str | None) -> str:
    """Return the system-prompt clause for a delivery level, or '' for none/unknown."""
    clause = _LEVELS.get(level or "")
    return f" {clause}{_INVARIANT}" if clause else ""

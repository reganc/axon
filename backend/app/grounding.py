"""Evidence-based grounding: deterministic confidence from claim verdicts.

The fast lane (the llm-app gateway) injects live web-search results into every
request, so a grounding call routed there sees actual evidence. The model's job
is only to report per-claim verdicts against that evidence; the *confidence* is
computed here, deterministically — never self-reported by the model. A model
grading its own homework is vibes, and a confidently wrong node is the worst
failure mode (accuracy > coverage).

Shared pure helpers (like `jsonutil`) — both the companion's Researcher and the
ingestion miner ground through this, so the two gates can't drift apart.
"""

from __future__ import annotations

# Verdict weights: supported counts fully, unverifiable counts half (absence of
# evidence is not evidence of absence), contradicted counts zero — and any
# contradiction caps the result below the publish floor so the node is flagged
# for review rather than published as settled fact.
_UNVERIFIABLE_WEIGHT = 0.5
_CONTRADICTION_CAP = 0.3
_VERDICTS = ("supported", "contradicted", "unverifiable")

GROUND_SYSTEM = (
    "You are AXON's Researcher. Web search results relevant to this explanation "
    "are included in your context. Verify the explanation's most load-bearing "
    "factual claims against that evidence — not against your own memory. Be "
    "strict: a claim is 'supported' only when the evidence actually backs it, "
    "'contradicted' when the evidence disagrees with it, and 'unverifiable' "
    "when the evidence is silent."
)


def ground_user_prompt(title: str, body: str | None) -> str:
    """The TASK: ground user message — verdicts requested, confidence not."""
    return (
        f"TASK: ground\nTitle: {title}\nBody: {body or ''}\n"
        "Check up to 6 key claims. Return JSON only: "
        '{"claims": [{"claim": "...", '
        '"verdict": "supported|contradicted|unverifiable", '
        '"source": "url or empty"}]}'
    )


def score_verdicts(claims: object, *, fallback: float = 0.5) -> tuple[float, list[str]]:
    """(confidence, supporting source URLs) from a model's claim-verdict list.

    Tolerant of malformed data: anything that isn't a dict with a recognizable
    verdict contributes nothing; no usable verdicts at all -> `fallback`.
    """
    if not isinstance(claims, list):
        return fallback, []
    counts = dict.fromkeys(_VERDICTS, 0)
    sources: list[str] = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in counts:
            continue
        counts[verdict] += 1
        src = str(item.get("source") or "").strip()
        if verdict == "supported" and src.startswith("http") and src not in sources:
            sources.append(src)
    total = sum(counts.values())
    if total == 0:
        return fallback, []
    confidence = (
        counts["supported"] + _UNVERIFIABLE_WEIGHT * counts["unverifiable"]
    ) / total
    if counts["contradicted"]:
        confidence = min(confidence, _CONTRADICTION_CAP)
    return max(0.0, min(1.0, confidence)), sources[:3]

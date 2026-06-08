"""Media grounding — accuracy-over-coverage gate for companion-surfaced visuals.

The fast gateway (with injected web search) proposes videos/links/images for a
concept, and the Diagrammer authors a Mermaid graph. A 14B with web context will
still hallucinate the occasional URL or emit malformed diagram syntax. These
validators resolve every candidate before it reaches the learner — a dead or
fabricated reference is *dropped*, never rendered. Network checks share a short
timeout and fail closed (drop on any error) so enrichment never hangs a turn.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import httpx

log = logging.getLogger("axon.media")

_TIMEOUT = 4.0
_YOUTUBE_OEMBED = "https://www.youtube.com/oembed"
# Many sites (Wikipedia among them) return 403 to clients with no/blocked
# User-Agent, which would wrongly drop a perfectly good reference. Identify
# ourselves with a conventional, bot-disclosing UA so real links resolve.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AxonLearningBot/1.0)"}
# Mermaid diagrams open with one of these declarations; anything else won't render.
_MERMAID_HEADS = (
    "graph",
    "flowchart",
    "sequencediagram",
    "classdiagram",
    "statediagram",
    "erdiagram",
    "journey",
    "gantt",
    "pie",
    "mindmap",
    "timeline",
)
_YOUTUBE_HOST = re.compile(r"(?:^|\.)(youtube\.com|youtu\.be)$", re.IGNORECASE)


def is_youtube(url: str) -> bool:
    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, TypeError):
        return False
    return bool(host and _YOUTUBE_HOST.search(host))


async def validate_youtube(url: str, *, client: httpx.AsyncClient | None = None) -> bool:
    """True only if the video resolves via YouTube's oEmbed endpoint (no API key).
    A fabricated video id returns 404 there, so this catches hallucinated links."""
    if not is_youtube(url):
        return False
    target = f"{_YOUTUBE_OEMBED}?url={quote(url, safe='')}&format=json"
    return await _ok(target, client=client)


async def validate_link(url: str, *, client: httpx.AsyncClient | None = None) -> bool:
    """True if the URL resolves (status < 400). Tries HEAD, falls back to a ranged
    GET for hosts that reject HEAD."""
    if not _http_url(url):
        return False
    return await _resolves(url, client=client)


async def validate_image(url: str, *, client: httpx.AsyncClient | None = None) -> bool:
    """True if the URL resolves and serves an image content-type."""
    if not _http_url(url):
        return False
    return await _resolves(url, want_prefix="image/", client=client)


def validate_mermaid(text: str | None) -> bool:
    """Cheap syntactic gate: a non-empty body that opens with a known Mermaid
    diagram declaration. Keeps a malformed diagram from rendering as an error box."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    head = stripped.split(None, 1)[0].lower()
    return any(head.startswith(h) for h in _MERMAID_HEADS)


# -- internals --------------------------------------------------------------


def _http_url(url: str) -> bool:
    try:
        return httpx.URL(url).scheme in ("http", "https")
    except (httpx.InvalidURL, TypeError):
        return False


async def _ok(url: str, *, client: httpx.AsyncClient | None = None) -> bool:
    async def run(c: httpx.AsyncClient) -> bool:
        try:
            resp = await c.get(url)
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            log.debug("media validate GET failed for %s: %s", url, exc)
            return False

    return await _with_client(run, client)


async def _resolves(
    url: str, *, want_prefix: str | None = None, client: httpx.AsyncClient | None = None
) -> bool:
    async def run(c: httpx.AsyncClient) -> bool:
        try:
            resp = await c.head(url)
            # Some hosts reject HEAD (405) or block it (403) but serve GET fine.
            if resp.status_code in (403, 405):
                resp = await c.get(url, headers={"Range": "bytes=0-0"})
            if resp.status_code >= 400:
                return False
            if want_prefix:
                ctype = resp.headers.get("content-type", "")
                return ctype.lower().startswith(want_prefix)
            return True
        except httpx.HTTPError as exc:
            log.debug("media validate failed for %s: %s", url, exc)
            return False

    return await _with_client(run, client)


async def _with_client(run, client: httpx.AsyncClient | None):
    if client is not None:
        return await run(client)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS
    ) as owned:
        return await run(owned)

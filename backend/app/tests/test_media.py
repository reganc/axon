"""media_validation — the accuracy gate for companion-surfaced visuals.

Pure + MockTransport unit tests (no live network, no DB), so they run anywhere.
"""

from __future__ import annotations

import httpx
import pytest

from app.seams.companion import media_validation as mv


def test_validate_mermaid_accepts_known_declarations():
    assert mv.validate_mermaid("graph TD; A-->B")
    assert mv.validate_mermaid("  flowchart LR\n A --> B ")
    assert mv.validate_mermaid("sequenceDiagram\n A->>B: hi")


def test_validate_mermaid_rejects_junk():
    assert not mv.validate_mermaid("")
    assert not mv.validate_mermaid("   ")
    assert not mv.validate_mermaid(None)
    assert not mv.validate_mermaid("OK")  # the FakeLLM fallback must not render
    assert not mv.validate_mermaid("Here is a diagram: graph TD")  # prose first


def test_is_youtube():
    assert mv.is_youtube("https://www.youtube.com/watch?v=abc")
    assert mv.is_youtube("https://youtu.be/abc")
    assert not mv.is_youtube("https://vimeo.com/123")
    assert not mv.is_youtube("not a url")
    # don't be fooled by a lookalike host
    assert not mv.is_youtube("https://notyoutube.com.evil.test/watch?v=x")


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oembed" in url:
            return httpx.Response(200 if "GOOD" in url else 404)
        if "/404" in url:
            return httpx.Response(404)
        if "pic.png" in url:
            return httpx.Response(200, headers={"content-type": "image/png"})
        if "nohead" in url and request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200, headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_link_and_image_validation_with_mock_transport():
    async with httpx.AsyncClient(transport=_transport()) as c:
        assert await mv.validate_link("https://good.example/ref", client=c) is True
        assert await mv.validate_link("https://bad.example/404", client=c) is False
        # an image url must actually serve an image content-type
        assert await mv.validate_image("https://good.example/pic.png", client=c) is True
        assert await mv.validate_image("https://good.example/ref", client=c) is False
        # a host that rejects HEAD still resolves via the GET fallback
        assert await mv.validate_link("https://x.example/nohead", client=c) is True
        # non-http schemes never resolve
        assert await mv.validate_link("ftp://x/y", client=c) is False


@pytest.mark.asyncio
async def test_youtube_validation_with_mock_transport():
    async with httpx.AsyncClient(transport=_transport()) as c:
        good = "https://www.youtube.com/watch?v=GOODvid"
        bad = "https://www.youtube.com/watch?v=missing"
        assert await mv.validate_youtube(good, client=c) is True
        assert await mv.validate_youtube(bad, client=c) is False
        # a non-YouTube url is rejected before any network call
        assert await mv.validate_youtube("https://vimeo.com/1", client=c) is False

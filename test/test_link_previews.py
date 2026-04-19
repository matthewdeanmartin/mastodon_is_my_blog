import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from mastodon_is_my_blog.link_previews import (
    CardRequest,
    _clean,
    _ensure_public_destination,
    fetch_card_from_network,
)


def test_clean_collapses_whitespace_and_empty_strings() -> None:
    assert _clean("  Hello \n   world \t ") == "Hello world"
    assert _clean("   ") is None
    assert _clean(None) is None


def test_card_request_rejects_non_http_urls() -> None:
    with pytest.raises(ValidationError):
        CardRequest(url="ftp://example.com/file.txt")


@pytest.mark.asyncio
async def test_ensure_public_destination_rejects_private_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_host(host: str) -> list[str]:
        assert host == "example.com"
        return ["127.0.0.1", "93.184.216.34"]

    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews._resolve_host", fake_resolve_host
    )

    with pytest.raises(HTTPException) as exc_info:
        await _ensure_public_destination("https://example.com/post")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Disallowed destination."


@pytest.mark.asyncio
async def test_fetch_card_from_network_parses_metadata_and_normalizes_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = b"""
    <html>
      <head>
        <meta property="og:title" content="  Example title  " />
        <meta name="description" content=" Example description " />
        <meta property="og:site_name" content="Example Site" />
        <meta property="og:image" content="/images/card.png" />
        <link rel="shortcut icon" href="/static/favicon.png" />
        <title>Fallback title</title>
      </head>
      <body></body>
    </html>
    """

    class DummyResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "text/html; charset=utf-8"}
            self.content = html
            self.url = "https://example.com/final"

    class DummySharedClient:
        async def get(self, url: str) -> DummyResponse:
            assert url == "https://example.com/start"
            return DummyResponse()

    async def allow_public_destination(raw_url: str) -> None:
        assert raw_url == "https://example.com/start"

    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews._ensure_public_destination",
        allow_public_destination,
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews.get_http_client",
        lambda: DummySharedClient(),
    )

    card = await fetch_card_from_network("https://example.com/start")

    assert card.url == "https://example.com/final"
    assert card.title == "Example title"
    assert card.description == "Example description"
    assert card.site_name == "Example Site"
    assert card.image == "https://example.com/images/card.png"
    assert card.favicon == "https://example.com/static/favicon.png"


@pytest.mark.asyncio
async def test_fetch_card_from_network_rejects_non_html_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "application/json"}
            self.content = b'{"ok": true}'
            self.url = "https://example.com/api"

    class DummySharedClient:
        async def get(self, url: str) -> DummyResponse:
            assert url == "https://example.com/api"
            return DummyResponse()

    async def allow_public_destination(raw_url: str) -> None:
        assert raw_url == "https://example.com/api"

    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews._ensure_public_destination",
        allow_public_destination,
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews.get_http_client",
        lambda: DummySharedClient(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await fetch_card_from_network("https://example.com/api")

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == "Unsupported content-type: application/json"


@pytest.mark.asyncio
async def test_fetch_card_from_network_wraps_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummySharedClient:
        async def get(self, url: str):
            raise httpx.ConnectError("boom")

    async def allow_public_destination(raw_url: str) -> None:
        assert raw_url == "https://example.com"

    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews._ensure_public_destination",
        allow_public_destination,
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.link_previews.get_http_client",
        lambda: DummySharedClient(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await fetch_card_from_network("https://example.com")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Upstream fetch failed."

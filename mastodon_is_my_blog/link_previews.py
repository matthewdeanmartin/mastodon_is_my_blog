from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional, cast
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from pydantic import AnyHttpUrl, BaseModel, field_validator

from mastodon_is_my_blog.store import CachedLinkPreview, async_session
from mastodon_is_my_blog.utils.perf import (
    record_card_timing,
    record_preview_error,
    record_preview_hit,
    record_preview_miss,
    record_preview_stale,
)

app = FastAPI()

MAX_BYTES = 512_000  # hard cap on HTML bytes read (512KB)
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0
REDIRECTS = 5

# TTL constants
TTL_OK_FRESH = timedelta(days=7)
TTL_OK_STALE = timedelta(days=30)
TTL_ERROR = timedelta(minutes=30)
TTL_BLOCKED = timedelta(hours=24)

# Shared httpx client — created once at lifespan, closed on shutdown.
# Callers must call init_http_client() / close_http_client() from the FastAPI lifespan.
_shared_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    if _shared_client is None:
        raise RuntimeError("HTTP client not initialized. Call init_http_client() first.")
    return _shared_client


def init_http_client() -> None:
    global _shared_client
    _shared_client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=READ_TIMEOUT,
            pool=READ_TIMEOUT,
        ),
        headers={
            "User-Agent": "LinkPreviewBot/1.0 (+https://example.com)",
            "Accept": "text/html,application/xhtml+xml",
        },
        max_redirects=REDIRECTS,
    )


async def close_http_client() -> None:
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None


# In-process coalescing: url_key → asyncio.Future so concurrent callers share one fetch.
_inflight: dict[str, asyncio.Future] = {}

# ---- Models ----


class CardResponse(BaseModel):
    url: str  # final URL after redirects
    title: Optional[str] = None
    description: Optional[str] = None
    site_name: Optional[str] = None
    image: Optional[str] = None
    favicon: Optional[str] = None


class CardRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def require_http_https(cls, v: AnyHttpUrl):
        if v.scheme not in ("http", "https"):
            raise ValueError("Only http/https URLs are allowed.")
        return v


# ---- URL canonicalization ----

STRIP_PARAMS = frozenset(
    [
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    ]
)


def canonicalize_url(raw_url: str) -> str:
    """
    Lowercase host, strip fragment, drop known tracking params.
    Used as the cache primary key.
    """
    p = urlparse(raw_url)
    from urllib.parse import parse_qsl, urlencode

    qs = [(k, v) for k, v in parse_qsl(p.query) if k not in STRIP_PARAMS]
    clean = p._replace(
        netloc=p.netloc.lower(),
        fragment="",
        query=urlencode(qs),
    )
    return clean.geturl()


# ---- SSRF defenses (baseline) ----

PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local v6
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in PRIVATE_NETS)
    except ValueError:
        return True  # if it's not a valid IP, treat as unsafe here


async def _resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list({sockaddr[0] for _, _, _, _, sockaddr in infos})


async def _ensure_public_destination(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    host = parsed.hostname
    if not host:
        raise HTTPException(400, "Invalid URL host.")

    if host in ("localhost",):
        raise HTTPException(400, "Disallowed host.")

    ips = await _resolve_host(host)
    if not ips:
        raise HTTPException(400, "Host did not resolve.")

    for ip in ips:
        if _is_private_ip(ip):
            raise HTTPException(400, "Disallowed destination.")


# ---- HTML parsing helpers ----


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _meta(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> Optional[str]:
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return cast(str, tag["content"])
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return cast(str, tag["content"])
    return None


def _abs_url(base: str, maybe: Optional[str]) -> Optional[str]:
    if not maybe:
        return None
    return urljoin(base, maybe)


def _favicon(base: str, soup: BeautifulSoup) -> Optional[str]:
    for rel in ("icon", "shortcut icon", "apple-touch-icon"):
        tag = soup.find("link", rel=lambda v, r=rel: isinstance(v, str) and r in v.lower())
        if tag and tag.get("href"):
            return urljoin(base, cast(str, tag["href"]))
    return urljoin(base, "/favicon.ico")


# ---- Core network fetch (no cache) ----


async def fetch_card_from_network(url: str) -> CardResponse:
    """Fetches and parses a link preview from the network. SSRF-safe."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http/https URLs are allowed.")

    await _ensure_public_destination(url)

    client = get_http_client()
    try:
        r = await client.get(url)
    except httpx.TooManyRedirects as exc:
        raise HTTPException(400, "Too many redirects.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Upstream fetch failed.") from exc

    ctype = (r.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        raise HTTPException(415, f"Unsupported content-type: {ctype or 'unknown'}")

    content = r.content[:MAX_BYTES]
    soup = BeautifulSoup(content, "html.parser")
    final_url = str(r.url)

    title = _clean(_meta(soup, prop="og:title") or _meta(soup, name="twitter:title"))
    if not title:
        title = _clean(soup.title.string if soup.title and soup.title.string else None)

    description = _clean(_meta(soup, prop="og:description") or _meta(soup, name="twitter:description") or _meta(soup, name="description"))

    site_name = _clean(_meta(soup, prop="og:site_name"))
    image = _abs_url(final_url, _meta(soup, prop="og:image") or _meta(soup, name="twitter:image"))
    favicon = _favicon(final_url, soup)

    return CardResponse(
        url=final_url,
        title=title,
        description=description,
        site_name=site_name,
        image=image,
        favicon=favicon,
    )


# ---- Persistent-cache fetch with coalescing ----


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def fetch_card(
    url: str = Query(..., min_length=8, max_length=2048),
) -> CardResponse:
    """
    Cached entry point:
    1. Canonicalize URL → look up DB row.
    2. Fresh hit  → return immediately (cache hit).
    3. Stale hit  → return immediately, schedule background revalidation.
    4. Miss/expired → coalesce concurrent callers, do one upstream fetch, persist result.

    All SSRF defenses remain intact.
    """
    import time as _time

    url_key = canonicalize_url(url)
    start = _time.perf_counter()

    async with async_session() as session:
        row = await session.get(CachedLinkPreview, url_key)

    now = _now_utc()

    if row is not None:
        stale_until_dt = (row.fetched_at + TTL_OK_STALE) if row.fetched_at else None

        if row.status == "ok" and row.expires_at and now < row.expires_at:
            # Fresh hit
            record_preview_hit()
            record_card_timing(url_key, _time.perf_counter() - start, "hit")
            return CardResponse(
                url=row.final_url or url,
                title=row.title,
                description=row.description,
                site_name=row.site_name,
                image=row.image,
                favicon=row.favicon,
            )

        if row.status == "ok" and stale_until_dt and now < stale_until_dt:
            # Stale hit — return stale data immediately, revalidate in background
            record_preview_stale()
            record_card_timing(url_key, _time.perf_counter() - start, "stale")
            stale_result = CardResponse(
                url=row.final_url or url,
                title=row.title,
                description=row.description,
                site_name=row.site_name,
                image=row.image,
                favicon=row.favicon,
            )
            asyncio.create_task(_revalidate(url, url_key))
            return stale_result

        if row.status in ("error", "blocked") and row.expires_at and now < row.expires_at:
            # Negative cache still valid
            record_preview_error()
            record_card_timing(url_key, _time.perf_counter() - start, "error")
            raise HTTPException(502, f"Cached fetch failure: {row.error_reason or 'unknown'}")

    # Miss or expired — coalesce concurrent fetches for the same url_key
    return await _coalesced_fetch(url, url_key, start)


async def _coalesced_fetch(url: str, url_key: str, start: float) -> CardResponse:
    import time as _time

    if url_key in _inflight:
        # Another coroutine is already fetching — wait for it
        result = await asyncio.shield(_inflight[url_key])
        elapsed = _time.perf_counter() - start
        record_preview_hit()
        record_card_timing(url_key, elapsed, "hit")
        return result

    loop = asyncio.get_running_loop()
    future: asyncio.Future[CardResponse] = loop.create_future()
    _inflight[url_key] = future

    try:
        card = await fetch_card_from_network(url)
        elapsed = _time.perf_counter() - start
        record_preview_miss()
        record_card_timing(url_key, elapsed, "miss")
        await _persist_ok(url_key, card)
        future.set_result(card)
        return card
    except HTTPException as exc:
        elapsed = _time.perf_counter() - start
        record_preview_error()
        record_card_timing(url_key, elapsed, "error")
        status = "blocked" if exc.status_code == 400 else "error"
        await _persist_error(url_key, status, str(exc.detail))
        future.set_exception(exc)
        raise
    except Exception as exc:
        elapsed = _time.perf_counter() - start
        record_preview_error()
        record_card_timing(url_key, elapsed, "error")
        await _persist_error(url_key, "error", str(exc))
        http_exc = HTTPException(502, "Upstream fetch failed.")
        future.set_exception(http_exc)
        raise http_exc from exc
    finally:
        _inflight.pop(url_key, None)


async def _revalidate(url: str, url_key: str) -> None:
    """Background revalidation for stale-while-revalidate."""
    try:
        card = await fetch_card_from_network(url)
        await _persist_ok(url_key, card)
    except Exception:
        pass  # Keep serving stale; next request will retry


async def _persist_ok(url_key: str, card: CardResponse) -> None:
    now = _now_utc()
    async with async_session() as session:
        row = await session.get(CachedLinkPreview, url_key)
        if row is None:
            row = CachedLinkPreview(url_key=url_key)
            session.add(row)
        row.final_url = card.url
        row.title = card.title
        row.description = card.description
        row.site_name = card.site_name
        row.image = card.image
        row.favicon = card.favicon
        row.status = "ok"
        row.fetched_at = now
        row.expires_at = now + TTL_OK_FRESH
        row.error_reason = None
        await session.commit()


async def _persist_error(url_key: str, status: str, reason: str) -> None:
    now = _now_utc()
    ttl = TTL_BLOCKED if status == "blocked" else TTL_ERROR
    async with async_session() as session:
        row = await session.get(CachedLinkPreview, url_key)
        if row is None:
            row = CachedLinkPreview(url_key=url_key)
            session.add(row)
        row.status = status
        row.fetched_at = now
        row.expires_at = now + ttl
        row.error_reason = reason
        await session.commit()

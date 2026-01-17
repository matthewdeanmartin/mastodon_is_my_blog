from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from pydantic import AnyHttpUrl, BaseModel, field_validator

app = FastAPI()

MAX_BYTES = 512_000  # hard cap on HTML bytes read (512KB)
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0
REDIRECTS = 5

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
    # Resolve A and AAAA; mitigate trivial SSRF. (DNS rebinding needs more if high-stakes.)
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    ips = []
    for _, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        ips.append(ip)
    return list(set(ips))


async def _ensure_public_destination(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    host = parsed.hostname
    if not host:
        raise HTTPException(400, "Invalid URL host.")

    # Block obvious local hostnames
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


def _meta(
    soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None
) -> Optional[str]:
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"]
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"]
    return None


def _abs_url(base: str, maybe: Optional[str]) -> Optional[str]:
    if not maybe:
        return None
    return urljoin(base, maybe)


def _favicon(base: str, soup: BeautifulSoup) -> Optional[str]:
    for rel in ("icon", "shortcut icon", "apple-touch-icon"):
        tag = soup.find("link", rel=lambda v: isinstance(v, str) and rel in v.lower())
        if tag and tag.get("href"):
            return urljoin(base, tag["href"])
    return urljoin(base, "/favicon.ico")


async def fetch_card(url: str = Query(..., min_length=8, max_length=2048)):
    # Validate scheme quickly
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Only http/https URLs are allowed.")

    # SSRF checks
    await _ensure_public_destination(url)

    headers = {
        "User-Agent": "LinkPreviewBot/1.0 (+https://example.com)",
        "Accept": "text/html,application/xhtml+xml",
    }

    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=READ_TIMEOUT,
        pool=READ_TIMEOUT,
    )

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=headers, max_redirects=REDIRECTS
    ) as client:
        try:
            r = await client.get(url)
        except httpx.TooManyRedirects:
            raise HTTPException(400, "Too many redirects.")
        except httpx.RequestError:
            raise HTTPException(502, "Upstream fetch failed.")

    ctype = (r.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        raise HTTPException(415, f"Unsupported content-type: {ctype or 'unknown'}")

    # Enforce max bytes (don’t parse multi-megabyte pages)
    content = r.content[:MAX_BYTES]
    if len(r.content) > MAX_BYTES:
        # Truncation is acceptable for metadata extraction; just don’t pretend it’s complete.
        pass

    soup = BeautifulSoup(content, "html.parser")
    final_url = str(r.url)

    title = _clean(_meta(soup, prop="og:title") or _meta(soup, name="twitter:title"))
    if not title:
        title = _clean(soup.title.string if soup.title and soup.title.string else None)

    description = _clean(
        _meta(soup, prop="og:description")
        or _meta(soup, name="twitter:description")
        or _meta(soup, name="description")
    )

    site_name = _clean(_meta(soup, prop="og:site_name"))
    image = _abs_url(
        final_url, _meta(soup, prop="og:image") or _meta(soup, name="twitter:image")
    )
    favicon = _favicon(final_url, soup)

    return CardResponse(
        url=final_url,
        title=title,
        description=description,
        site_name=site_name,
        image=image,
        favicon=favicon,
    )

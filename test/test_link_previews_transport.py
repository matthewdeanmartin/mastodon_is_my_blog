"""Exercise the shared HTTPX2 client against an actual local HTTP server."""

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi import HTTPException

from mastodon_is_my_blog import link_previews


@pytest.fixture
def preview_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/page")
                self.end_headers()
                return
            body = b"<html><head><title>Local preview</title></head></html>"
            content_type = "text/html; charset=utf-8"
            if self.path == "/json":
                body = b"{}"
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/redirect", "/json"])
async def test_shared_client_transport(preview_server: str, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_test_server(url: str) -> None:
        # Override only the SSRF gate for the explicit test server.
        assert url.startswith(preview_server + "/")

    monkeypatch.setattr(link_previews, "_ensure_public_destination", allow_test_server)
    link_previews.init_http_client()
    try:
        if path == "/json":
            with pytest.raises(HTTPException) as error:
                await link_previews.fetch_card_from_network(preview_server + path)
            assert error.value.status_code == 415
        else:
            card = await link_previews.fetch_card_from_network(preview_server + path)
            assert card.title == "Local preview"
            assert card.url == preview_server + "/page"
    finally:
        await link_previews.close_http_client()
    with pytest.raises(RuntimeError, match="not initialized"):
        link_previews.get_http_client()

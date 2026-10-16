"""The real clients, httpx and curl_cffi, against a server on 127.0.0.1: no outside network."""

import asyncio
import gzip
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from recon import settings
from recon.clients import make_client

BOMB = gzip.compress(b"0" * 2_000_000)  # 2 MB of zeros in about 2 KB
COOKIES_SEEN: list[str | None] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        COOKIES_SEEN.append(self.headers.get("Cookie"))
        if self.path == "/bomb":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(BOMB)))
            self.end_headers()
            self.wfile.write(BOMB)
            return
        body = b"<html><title>Home</title>hello</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "sid=1; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # quiet
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.parametrize("kind", ["httpx-h1", "curl-chrome"])
def test_an_answer_its_cookie_set_none_sent_back(server: str, kind: str) -> None:
    async def twice() -> list:
        client = make_client(kind)
        try:
            return [await client.fetch(f"{server}/"), await client.fetch(f"{server}/")]
        finally:
            await client.aclose()

    COOKIES_SEEN.clear()
    first, _ = asyncio.run(twice())
    assert (first.status, first.error, b"hello" in first.body) == (200, None, True)
    assert "sid" in first.cookies
    assert COOKIES_SEEN == [None, None], "the cookie set is never sent back"


@pytest.mark.parametrize("kind", ["httpx-h1", "curl-chrome"])
def test_a_compression_bomb_is_cut_at_body_kept(server: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BODY_KEPT", 50_000)

    async def once():
        client = make_client(kind)
        try:
            return await client.fetch(f"{server}/bomb")
        finally:
            await client.aclose()

    answer = asyncio.run(once())
    if kind.startswith("httpx"):
        assert (answer.status, answer.cut, len(answer.body)) == (200, True, 50_000)
    else:  # curl stops the transfer: an error, not 2 MB in memory
        assert answer.error == "BodyTooLarge: over 50,000 bytes"


@pytest.mark.parametrize("kind", ["httpx-h1", "curl-chrome"])
def test_an_odd_address_is_an_answer_not_an_exception(kind: str) -> None:
    async def once():
        client = make_client(kind)
        try:
            return await client.fetch("http://exa mple.invalid/\x0b")
        finally:
            await client.aclose()

    answer = asyncio.run(once())
    assert answer.status is None and answer.error

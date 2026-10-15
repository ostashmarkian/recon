"""The HTTP clients recon tries, behind one interface: fetch() gives an Answer,
never an exception."""

import ssl
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any, Protocol

import httpx

from . import settings


@dataclass
class Answer:
    """One request's outcome: the answer, or why there was none (`error`)."""

    url: str
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)  # lowercased name: value
    cookies: tuple[str, ...] = ()  # the names it sets
    body: bytes = b""
    seconds: float = 0.0
    error: str | None = None  # no answer: why
    http: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def head(self) -> str:
        return self.body[: settings.HEAD].decode("utf-8", "replace")

    @property
    def location(self) -> str:
        return self.headers.get("location", "")


class Client(Protocol):
    """What recon asks of a client: fetch() never raises, it answers an Answer."""

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None, data: bytes | None = None
    ) -> Answer: ...  # pragma: no cover

    async def aclose(self) -> None: ...  # pragma: no cover


def cookie_names(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(line.split("=", 1)[0].strip() for line in lines if "=" in line)


class HttpxClient:
    """httpx with a browser's headers; no cookie kept unless `cookies`."""

    def __init__(self, kind: str, ua: str | None, cookies: bool) -> None:
        context = ssl.create_default_context()
        if kind.endswith("-pha"):
            context.post_handshake_auth = True
        self.client = httpx.AsyncClient(
            http2="-h2" in kind,
            verify=context,
            headers={
                "User-Agent": settings.CHROME_UA if ua is None else ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            # a jar refusing every cookie, passed as it is: wrapped in
            # httpx.Cookies it would be copied into one that keeps them all
            cookies=None if cookies else CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
            timeout=settings.TIMEOUT,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=settings.H1_MOST),
        )

    async def fetch(self, url: str, headers: dict[str, str] | None = None, data: bytes | None = None) -> Answer:
        """A GET, or a POST of `data`."""
        began = time.monotonic()
        try:
            if data is None:
                r = await self.client.get(url, headers=headers)
            else:
                r = await self.client.post(url, headers=headers, content=data)
        except httpx.HTTPError as e:
            return Answer(url, error=f"{type(e).__name__}: {e}"[:300], seconds=time.monotonic() - began)
        return Answer(
            url,
            r.status_code,
            {k.lower(): v for k, v in r.headers.items()},
            cookie_names(r.headers.get_list("set-cookie")),
            r.content[: settings.BODY_KEPT],
            time.monotonic() - began,
            http="h2" if r.http_version == "HTTP/2" else "h1",
        )

    async def aclose(self) -> None:
        await self.client.aclose()


class CurlClient:
    """curl_cffi as a browser (curl-chrome: impersonate="chrome"); its own
    User-Agent unless `ua`; no cookie kept unless `cookies`."""

    def __init__(self, kind: str, ua: str | None, cookies: bool) -> None:
        from curl_cffi.requests import AsyncSession
        from curl_cffi.requests.exceptions import RequestException

        self.failure, self.ua = RequestException, ua
        self.session: Any = AsyncSession(impersonate=kind.split("-", 1)[1], discard_cookies=not cookies, max_clients=16)

    async def fetch(self, url: str, headers: dict[str, str] | None = None, data: bytes | None = None) -> Answer:
        """A GET, or a POST of `data`."""
        sent: dict[str, str] = {} if self.ua is None else {"User-Agent": self.ua}
        sent.update(headers or {})
        began = time.monotonic()
        try:
            r = await self.session.request(
                "GET" if data is None else "POST",
                url,
                headers=sent,
                data=data,
                allow_redirects=False,
                timeout=settings.TIMEOUT,
            )
        except self.failure as e:
            return Answer(url, error=f"{type(e).__name__}: {e}"[:300], seconds=time.monotonic() - began)
        return Answer(
            url,
            r.status_code,
            {k.lower(): v for k, v in r.headers.items() if v is not None},
            cookie_names(r.headers.get_list("set-cookie")),
            r.content[: settings.BODY_KEPT],
            time.monotonic() - began,
            # curl's CURL_HTTP_VERSION_*: 3-5 are HTTP/2, 30-31 HTTP/3
            http={3: "h2", 4: "h2", 5: "h2", 30: "h3", 31: "h3"}.get(int(r.http_version), "h1"),
        )

    async def aclose(self) -> None:
        await self.session.close()


def make_client(kind: str, ua: str | None = None, cookies: bool = False) -> Client:
    return (CurlClient if kind.startswith("curl-") else HttpxClient)(kind, ua, cookies)

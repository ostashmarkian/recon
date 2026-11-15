"""watch_in_browser itself, against a stand-in for patchright: a page whose network never goes quiet, and one
that never finishes loading. No Chrome is started; patchright need not be installed."""

import asyncio
import sys
import types
from typing import Any

import pytest
from fakes import BASE, LISTED

from recon import settings
from recon.browser import watch_in_browser

LISTING = f"{BASE}/category/"


class Request:
    def __init__(self, url: str, kind: str) -> None:
        self.url, self.resource_type, self.method, self.post_data = url, kind, "GET", None
        self.headers = {"accept": "*/*"}

    async def all_headers(self) -> dict[str, str]:
        return dict(self.headers)


class Response:
    def __init__(self, url: str, kind: str = "fetch", frame: Any = None, body: bytes = LISTED) -> None:
        self.url, self.status, self.frame, self.request = url, 200, frame, Request(url, kind)
        self.headers = {"content-type": "application/json" if kind == "fetch" else "text/html"}
        self._body = body

    async def body(self) -> bytes:
        return self._body


class Locator:
    def __init__(self, page: "Page", there: bool) -> None:
        self.page, self.there = page, there

    @property
    def first(self) -> "Locator":
        return self

    async def count(self) -> int:
        return int(self.there)

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def get_attribute(self, name: str) -> str:
        return "/category/?page=2"

    async def click(self, timeout: float | None = None) -> None:
        self.page.clicks += 1
        self.page.url = f"{LISTING}?page=2"
        self.page.emit(Response(f"{BASE}/api/catalog/page?page=2"))


class Page:
    """A page that answers its document and one fetch; `busy`: its network never goes quiet; `stuck`: its load
    never ends, after its document came."""

    def __init__(self, busy: bool = False, stuck: bool = False) -> None:
        self.busy, self.stuck = busy, stuck
        self.handlers: list[Any] = []
        self.main_frame = object()
        self.url, self.clicks, self.scrolls = "", 0, 0
        self.mouse = types.SimpleNamespace(wheel=self.wheel)

    def on(self, event: str, handler: Any) -> None:
        self.handlers.append(handler)

    def remove_listener(self, event: str, handler: Any) -> None:
        self.handlers.remove(handler)

    def emit(self, answer: Response) -> None:
        for handler in list(self.handlers):
            handler(answer)

    async def evaluate(self, js: str) -> str:
        return "Mozilla/5.0 HeadlessChrome/142.0.0.0 Safari/537.36"

    async def goto(self, url: str, wait_until: str, timeout: float) -> Response:
        self.url = url
        document = Response(url, "document", self.main_frame, b"<html><title>Shop</title></html>")
        self.emit(document)
        self.emit(Response(f"{BASE}/api/catalog/products?limit=24"))
        if self.stuck or (self.busy and wait_until == "networkidle"):
            raise TimeoutError(f"Timeout {timeout:g}ms exceeded")
        return document

    async def wait_for_load_state(self, state: str, timeout: float) -> None:
        if self.busy:
            raise TimeoutError(f"Timeout {timeout:g}ms exceeded")

    async def wheel(self, x: int, y: int) -> None:
        self.scrolls += 1

    async def title(self) -> str:
        return "Shop"

    def locator(self, css: str) -> Locator:
        return Locator(self, css == "a[rel~='next']")

    def get_by_role(self, role: str, name: str, exact: bool) -> Locator:
        return Locator(self, False)


def patchright(monkeypatch: pytest.MonkeyPatch, page: Page) -> None:
    """patchright.async_api.async_playwright, giving `page` in each browser and context it opens."""

    class Opened:
        def __init__(self) -> None:
            self.pages = [page]

        async def new_page(self) -> Page:
            return page

        async def close(self) -> None:
            pass

    async def opened(*args: Any, **kw: Any) -> Opened:
        return Opened()

    class Playwright:
        chromium = types.SimpleNamespace(launch=opened, launch_persistent_context=opened)

        async def __aenter__(self) -> "Playwright":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    api = types.ModuleType("patchright.async_api")
    api.async_playwright = Playwright  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    monkeypatch.setitem(sys.modules, "patchright.async_api", api)
    monkeypatch.setattr(settings, "WATCH_SETTLE", 0)


def test_a_page_never_quiet_is_still_scrolled_and_clicked(monkeypatch):
    page = Page(busy=True)
    patchright(monkeypatch, page)
    seen = asyncio.run(watch_in_browser([LISTING], wait=0.05, click=LISTING))
    [got] = seen["pages"]
    assert (got["status"], got["title"], "error" in got) == (200, "Shop", False)
    assert got["busy"] >= 0 and page.scrolls == 1
    assert got["clicked"]["control"] == "a[rel~='next']" and page.clicks == 1
    after = [c["url"] for c in got["calls"] if c.get("after_click")]
    assert after == [f"{BASE}/api/catalog/page?page=2"]
    assert [c["url"] for c in got["calls"] if not c.get("after_click")] == [f"{BASE}/api/catalog/products?limit=24"]


def test_a_page_that_never_loads_keeps_its_status_and_says_the_click_was_not_tried(monkeypatch):
    page = Page(stuck=True)
    patchright(monkeypatch, page)
    seen = asyncio.run(watch_in_browser([LISTING], wait=0.05, click=LISTING))
    [got] = seen["pages"]
    assert (got["status"], got["error"]) == (200, "TimeoutError"), "the document had come: its status is known"
    assert got["clicked"] == {"control": None, "untried": True} and page.clicks == 0
    assert [c["url"] for c in got["calls"]] == [f"{BASE}/api/catalog/products?limit=24"]


def test_the_report_says_how_the_pages_were_read():
    from recon.report import watch_line

    pages = [
        {"url": f"{BASE}/", "status": 200, "title": "Shop", "busy": 30.0, "calls": [{"kind": "data"}]},
        {"url": LISTING, "status": 200, "title": "", "error": "TimeoutError", "calls": [{"kind": "data"}]},
    ]
    pages[1]["clicked"] = {"control": None, "untried": True}
    said = watch_line({"pages": pages})
    assert "the listing broke before its next page was looked for" in said
    assert "never quiet, read as they stood: /" in said and "broke in Chrome: /category/ (TimeoutError)" in said

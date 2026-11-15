"""Google Chrome through patchright: what a real browser meets on a page."""

import asyncio
import contextlib
import re
import tempfile
import time
from typing import Any

from . import settings
from .pages import SKIPPED_PATHS


async def open_in_browser(url: str, wait: float = settings.BROWSER_WAIT) -> dict[str, Any]:
    """What Google Chrome meets on `url`: patchright, headless, HeadlessChrome
    taken out of its User-Agent (as is, it is challenged for good)."""
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        try:
            page = await browser.new_page()
            ua = (await page.evaluate("navigator.userAgent")).replace("HeadlessChrome/", "Chrome/")
        finally:
            await browser.close()
        with tempfile.TemporaryDirectory(prefix="recon-chrome-", ignore_cleanup_errors=True) as profile:
            context = await p.chromium.launch_persistent_context(
                profile, channel="chrome", headless=True, no_viewport=True, user_agent=ua
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                began = time.monotonic()
                r = await page.goto(url, wait_until="domcontentloaded", timeout=wait * 1000)
                shown: float | None = None  # when the real page first showed
                title, cookies = "", {}
                while time.monotonic() - began < wait:
                    try:
                        title = await page.title()
                    except Exception:
                        title = ""
                    cookies = {c["name"]: c["value"] for c in await context.cookies(url)}
                    if title and not is_challenge_title(title):
                        shown = shown or time.monotonic()
                        if "cf_clearance" in cookies or time.monotonic() - shown > settings.BROWSER_SETTLE:
                            break
                    await asyncio.sleep(0.5)
                return {
                    "ua": ua,
                    "status": r.status if r else None,
                    "challenged": bool(r and (r.headers.get("cf-mitigated") == "challenge" or r.status in (403, 503))),
                    "title": title[:80],
                    "passed": bool(title) and not is_challenge_title(title),
                    "cookies": sorted(cookies),
                    "cf_clearance": cookies.get("cf_clearance"),
                    "seconds": round(time.monotonic() - began, 1),
                }
            finally:
                await context.close()


class BrowserMissing(RuntimeError):
    """patchright or Google Chrome is not on this machine: the step is skipped, and the report says which."""


def chrome_missing(e: Exception) -> bool:
    """Whether patchright failed to start Chrome because it is not installed."""
    said = str(e).lower()
    missing = ("is not found", "doesn't exist", "not installed", "no such file")
    return "chrome" in said and any(k in said for k in missing)


async def watch_in_browser(
    urls: list[str], wait: float = settings.WATCH_WAIT, click: str | None = None
) -> dict[str, Any]:
    """What the pages ask for once Chrome draws them: every XHR and fetch each of `urls` makes, with its answer's
    first WATCH_BODY bytes. Each page loads until the network is quiet, then is scrolled once for what loads
    lazily. On the page `click` (a listing), its next-page control is clicked once (click_next()), and the calls
    after it are marked: a list paged by a script shows only then. Trackers are left out (TRACKERS). A page is
    given a bounded time, and an answer that does not end (a stream, a long poll) WATCH_BODY_WAIT s, so a page
    that never lets go cannot hold the run. BrowserMissing when patchright or Chrome is not there."""
    try:
        from patchright.async_api import async_playwright
    except ImportError as e:
        raise BrowserMissing('patchright is not installed (pip install "site-recon[browser]")') from e

    began = time.monotonic()
    seen: list[dict[str, Any]] = []
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
        except Exception as e:
            if chrome_missing(e):
                raise BrowserMissing("Google Chrome is not installed") from e
            raise
        try:
            page = await browser.new_page()
            ua = (await page.evaluate("navigator.userAgent")).replace("HeadlessChrome/", "Chrome/")
        finally:
            await browser.close()
        with tempfile.TemporaryDirectory(prefix="recon-chrome-", ignore_cleanup_errors=True) as profile:
            context = await p.chromium.launch_persistent_context(
                profile, channel="chrome", headless=True, no_viewport=True, user_agent=ua
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                for url in urls:
                    answers: list[Any] = []

                    def on_answer(answer: Any, answers: list[Any] = answers) -> None:
                        answers.append(answer)  # a function of its own: patchright marks its handlers

                    page.on("response", on_answer)
                    state: dict[str, Any] = {
                        "status": None,
                        "title": "",
                        "mark": None,
                    }  # mark: answers before the click

                    async def visit(
                        url: str = url, state: dict[str, Any] = state, answers: list[Any] = answers
                    ) -> None:
                        r = await page.goto(url, wait_until="networkidle", timeout=wait * 1000)
                        state["status"] = r.status if r else None
                        await page.mouse.wheel(0, 20_000)
                        await asyncio.sleep(settings.WATCH_SETTLE)
                        state["title"] = await page.title()
                        if url == click:
                            state["mark"] = len(answers)
                            state["clicked"] = {"control": await click_next(page)}
                            if state["clicked"]["control"]:
                                with contextlib.suppress(Exception):  # a page that never goes quiet again
                                    await page.wait_for_load_state("networkidle", timeout=wait * 1000)
                                await asyncio.sleep(settings.WATCH_SETTLE)
                                state["clicked"]["url"] = page.url

                    try:  # a page that never goes quiet, or a call into Chrome that never returns: what it asked so far
                        await asyncio.wait_for(visit(), 2 * wait + 2 * settings.WATCH_SETTLE + settings.WATCH_BODY_WAIT)
                    except Exception as e:
                        state["title"] = state["title"] or f"{type(e).__name__}"
                    page.remove_listener("response", on_answer)
                    calls: list[dict[str, Any]] = []
                    until = time.monotonic() + settings.WATCH_BODIES_WAIT
                    for i, a in enumerate(answers):
                        request = a.request
                        if request.resource_type not in ("xhr", "fetch") or TRACKERS.search(a.url):
                            continue
                        if len(calls) >= settings.WATCH_CALLS:
                            break
                        # an answer that never ends (a stream, a long poll) is not waited for past WATCH_BODY_WAIT
                        left = min(settings.WATCH_BODY_WAIT, until - time.monotonic())
                        unfinished = False
                        try:
                            body = (await asyncio.wait_for(a.body(), max(left, 0.1)))[: settings.WATCH_BODY]
                        except TimeoutError:
                            body, unfinished = b"", True
                        except Exception:  # a redirect or an answer gone with the page
                            body = b""
                        try:  # what the page sent, cookies and tokens with it: their names are reported, not values
                            sent_headers = await asyncio.wait_for(request.all_headers(), settings.WATCH_BODY_WAIT)
                        except Exception:
                            sent_headers = dict(request.headers)
                        calls.append(
                            {
                                "method": request.method,
                                "url": a.url,
                                "status": a.status,
                                "type": a.headers.get("content-type", ""),
                                "sent": (request.post_data or "")[: settings.WATCH_SENT],
                                "headers": sent_headers,
                                "body": body,
                                **({"unfinished": True} if unfinished else {}),
                                **({"after_click": True} if state["mark"] is not None and i >= state["mark"] else {}),
                            }
                        )
                    seen.append(
                        {
                            "url": url,
                            "status": state["status"],
                            "title": state["title"][:80],
                            "calls": calls,
                            **({"clicked": state.get("clicked") or {"control": None}} if url == click else {}),
                        }
                    )
            finally:
                await context.close()
    return {"ua": ua, "pages": seen, "seconds": round(time.monotonic() - began, 1)}


# analytics, ads and consent calls: what a page sends about its visitors, not what it reads
TRACKERS = re.compile(
    r"google-analytics|googletagmanager|doubleclick|googlesyndication|facebook\.|hotjar|clarity\.ms|bing\.com"
    r"|yandex|tiktok|criteo|segment\.(io|com)|sentry|newrelic|nr-data|datadoghq|cookiebot|onetrust|usercentrics"
    r"|/collect\b|/analytics|/track|consent"
    # Alibaba Cloud's real-user monitoring (an "endpoint" in an inline script), Sensors Data, Baidu, CNZZ, GrowingIO
    r"|log\.aliyuncs\.com|/rum/|arms-retcode|sensorsdata|hm\.baidu\.com|cnzz\.com|growingio",
    re.I,
)


def is_challenge_title(title: str) -> bool:
    low = title.lower()
    return any(
        k in low for k in ("just a moment", "attention required", "access denied", "captcha", "security check", "verif")
    )


# a listing's control for its next page: by its markup first, then by its words as a link or a button
NEXT_CSS = (
    "a[rel~='next']",
    "[aria-label='Next page' i]",
    "[aria-label='Next' i]",
    "[aria-label*='next page' i]",
    ".ant-pagination-next:not(.ant-pagination-disabled)",
    ".el-pagination .btn-next:not([disabled])",
    ".pagination .next a",
    "li.next a",
    "a.next",
    "button.next",
    ".page-next",
    ".next-page",
)
NEXT_WORDS = (
    "下一页",
    "下一頁",
    "Next",
    "Next page",
    "›",
    "»",
    "Далі",
    "Наступна",
    "Далее",
    "Weiter",
    "Suivant",
    "Siguiente",
    "Następna",
    "Další",
    "次へ",
    "다음",
)


async def click_next(page: Any) -> str | None:
    """Clicks a listing's next-page control once: the first of NEXT_CSS, then of NEXT_WORDS, that is shown and
    enabled and leads nowhere a look-over must not go (a cart, an account). What was clicked, or None."""
    found = [(css, page.locator(css)) for css in NEXT_CSS]
    found += [
        (f'{role} "{word}"', page.get_by_role(role, name=word, exact=True))
        for word in NEXT_WORDS
        for role in ("link", "button")
    ]
    for name, locator in found:
        try:
            target = locator.first
            if not await locator.count() or not await target.is_visible() or not await target.is_enabled():
                continue
            href = await target.get_attribute("href") or ""
            if SKIPPED_PATHS.search(href):
                continue
            await target.click(timeout=5_000)
            return name
        except Exception:  # gone, covered, or not clickable: the next one
            continue
    return None

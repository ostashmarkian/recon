"""Google Chrome through patchright: what a real browser meets on a page."""

import asyncio
import re
import tempfile
import time
from typing import Any

from . import settings


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


async def watch_in_browser(urls: list[str], wait: float = settings.WATCH_WAIT) -> dict[str, Any]:
    """What the pages ask for once Chrome draws them: every XHR and fetch each of `urls` makes, with its answer's
    first WATCH_BODY bytes. Each page loads until the network is quiet, then is scrolled once for what loads
    lazily. Trackers are left out (TRACKERS)."""
    from patchright.async_api import async_playwright

    began = time.monotonic()
    seen: list[dict[str, Any]] = []
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
                for url in urls:
                    answers: list[Any] = []

                    def on_answer(answer: Any, answers: list[Any] = answers) -> None:
                        answers.append(answer)  # a function of its own: patchright marks its handlers

                    page.on("response", on_answer)
                    status, title = None, ""
                    try:
                        r = await page.goto(url, wait_until="networkidle", timeout=wait * 1000)
                        status = r.status if r else None
                        await page.mouse.wheel(0, 20_000)
                        await asyncio.sleep(settings.WATCH_SETTLE)
                        title = await page.title()
                    except Exception as e:  # a page that never goes quiet: what it asked for so far
                        title = f"{type(e).__name__}"
                    page.remove_listener("response", on_answer)
                    calls = []
                    for a in answers:
                        request = a.request
                        if request.resource_type not in ("xhr", "fetch") or TRACKERS.search(a.url):
                            continue
                        try:
                            body = (await a.body())[: settings.WATCH_BODY]
                        except Exception:  # a redirect or an answer gone with the page
                            body = b""
                        calls.append(
                            {
                                "method": request.method,
                                "url": a.url,
                                "status": a.status,
                                "type": a.headers.get("content-type", ""),
                                "sent": (request.post_data or "")[:500],
                                "body": body,
                            }
                        )
                    seen.append(
                        {"url": url, "status": status, "title": title[:80], "calls": calls[: settings.WATCH_CALLS]}
                    )
            finally:
                await context.close()
    return {"ua": ua, "pages": seen, "seconds": round(time.monotonic() - began, 1)}


# analytics, ads and consent calls: what a page sends about its visitors, not what it reads
TRACKERS = re.compile(
    r"google-analytics|googletagmanager|doubleclick|googlesyndication|facebook\.|hotjar|clarity\.ms|bing\.com"
    r"|yandex|tiktok|criteo|segment\.(io|com)|sentry|newrelic|nr-data|datadoghq|cookiebot|onetrust|usercentrics"
    r"|/collect\b|/analytics|/track|consent",
    re.I,
)


def is_challenge_title(title: str) -> bool:
    low = title.lower()
    return any(
        k in low for k in ("just a moment", "attention required", "access denied", "captcha", "security check", "verif")
    )

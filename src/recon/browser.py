"""Google Chrome through patchright: what a real browser meets on a page."""

import asyncio
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


def is_challenge_title(title: str) -> bool:
    low = title.lower()
    return any(
        k in low for k in ("just a moment", "attention required", "access denied", "captcha", "security check", "verif")
    )

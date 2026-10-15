"""recon - look a website over before you scrape it.

    recon https://www.example.com [--page URL] [--products N] [--browser] [--no-burst]
                                  [--notes DIR] [--compare FILE] [--pause S] [--out DIR]

What stands between a scraper and a site, in one report: its protection and
the way in, its platform and open API, what its product pages carry and how
clean that is, how it answers for pages that are not there, where its
catalogue can be read from, how fresh its pages are, and the pace it allows.
The report goes to recon-reports/<host>-<when>.md and .json and to stdout;
the newest earlier .json of the same host there, or --compare FILE, is set
against it: what changed since.

1. The home page (its redirects followed), robots.txt, the sitemaps it names
   or else the first of SITEMAP_PATHS that answers (SITEMAP_FILES at most),
   and one deeper page: --page, or a product the sitemap or the home page's
   links point to, picked at random so one dead corner of a sitemap is not
   all it sees.
2. Who is let in: CLIENTS with a browser User-Agent - httpx over HTTP/2 and
   HTTP/1.1, each also with post_handshake_auth (Python's other ClientHello,
   which some Cloudflare rules let through), curl_cffi as Chrome, Safari and
   Firefox - on those three pages. Then every User-Agent of UAS on the home
   page, through the first client let in.
3. Google Chrome through patchright, headless and with HeadlessChrome taken
   out of its User-Agent (as is, it is challenged for good), when a client
   was challenged or with --browser: is it challenged itself, does it get
   cf_clearance, and does that cookie with its User-Agent let the challenged
   clients in.
4. The platform from the markers its pages show, and its open API, one
   request: WooCommerce's Store API, Shopify's products.json, Magento's
   GraphQL, BigCommerce's storefront GraphQL with the token its pages carry,
   OpenCart's empty search - its count, and a product's SKU and MPN.
5. A product page: schema.org Product in JSON-LD and microdata, the product
   meta tags, and the words it shows for a part number, a maker, VAT and
   stock. The deeper page, or up to PRODUCT_TRIES more product links when it
   shows none. Then a sample of --products pages (SAMPLE_PRODUCTS): how many
   carry each field, and the traps a scraper falls into - an MPN that is the
   shop's SKU, a GTIN or Excel's 4.84E+11, a placeholder, one MPN on several
   products; the same stock on every page; a price ladder; the currency and
   whether VAT is in.
6. Not-found pages: a made-up product shaped like the real one, a made-up
   path, and page FAR_PAGE of a listing beside its real page. A 200 for what
   is not there (an empty section, a listing that wraps to its first page) is
   a soft 404 a scraper must catch by content.
7. Catalogue sources cheaper than HTML, from the pages already read: search
   services (Algolia, Searchanise, Boost, ...), page-data blobs
   (__NEXT_DATA__, ...) and the API paths the pages call; and whether a page
   is drawn by JavaScript, so its HTML holds no data.
8. Freshness: cache statuses, Age and Last-Modified on the pages read. Pages
   served from a cache days old show stock and prices days old.
9. A session lock: SESSION_PAGES pages SESSION_AT_ONCE at a time with one
   cookie jar, and as many others with none. Some servers (ASP.NET, PHP
   sessions) serve one session's requests one at a time: 0.8 pages/s with a
   jar against 11 without was seen.
10. A burst, only when nothing above found protection - no anti-bot service
   in front, no client with a browser User-Agent turned away - and robots.txt
   asks for no Crawl-delay. A filter of User-Agents by name (GPTBot,
   Python-urllib, ...) is reported but does not stop it: the burst sends a
   browser's. STEPS of 1, 2, 4, 8 and 16 at a time, 350 requests at most over
   distinct pages robots.txt allows; 16 only over HTTP/2, since over HTTP/1.1
   each request in flight is a connection, and a firewall counting them shut
   an IP out for 29 min at 16. It stops at the first refusal, at the
   LOST_MAX-th connection lost, when answers slow to SLOW_FACTOR times the
   first step's, or when a tenth of a step fails; after a stop it asks once
   more RECOVER s later, to say whether the site has let go.

Everything else goes one request at a time, PAUSE apart, or robots.txt's
Crawl-delay apart when it asks for more (then no session test either).
Rate-limit headers seen on any answer are reported, and with --notes, the
notes in a folder of Markdown (an Obsidian vault, say) that name the domain
or the platform. A cell of the report reads "403 challenge (Cloudflare),
h2 0.21s".
"""

import asyncio
import itertools
import logging
import random
import time
import zlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from . import settings
from .browser import open_in_browser
from .classify import LOST, REFUSALS, judge, passes, title_of, vendors_of
from .clients import Answer, Client, make_client
from .findings import (
    Findings,
    burst_blockers,
    counts,
    not_found_findings,
    percentile,
    protection,
    summary,
    ua_filter,
    way_in,
)
from .notes import notes_on, read_notes
from .pages import (
    ASSET,
    HREF,
    PRODUCT_HINT,
    SKIPPED_PATHS,
    drawn,
    freshness,
    listing_page,
    made_up,
    product_data,
    rate_headers,
    read_sitemap,
    sources_of,
)
from .platforms import api_request, api_says, platforms_of
from .sample import page_record, sample_findings

log = logging.getLogger(__name__)


class Recon:
    """One look at one shop; run() gives the findings, report() the markdown."""

    def __init__(
        self,
        url: str,
        page: str | None = None,
        make: Callable[..., Client] = make_client,
        browse: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        browser: bool = False,
        burst: bool = True,
        pause: float | None = None,
        notes: str | Path | Sequence[tuple[Path, str]] | None = None,
        products: int = settings.SAMPLE_PRODUCTS,
    ) -> None:
        if "://" not in url:
            url = "https://" + url
        if not urlsplit(url).path:
            url += "/"
        self.start, self.page, self.make = url, page, make
        self.browse = browse or open_in_browser
        self.force_browser, self.burst_allowed = browser, burst
        # a pause given is kept; else PAUSE, or robots.txt's Crawl-delay when it asks for more
        self.pause_given = pause is not None
        self.pause: float = settings.PAUSE if pause is None else pause
        self.crawl_delay: float | None = None
        self.notes = read_notes(notes) if isinstance(notes, (str, Path)) else list(notes or [])
        self.sample_size = products
        self.requests = 0
        self.f: Findings = {"url": url, "began": datetime.now().astimezone().isoformat(timespec="seconds")}

    async def get(
        self,
        client: Client,
        url: str,
        headers: dict[str, str] | None = None,
        pause: bool = True,
        data: bytes | None = None,
    ) -> Answer:
        if pause and self.requests:
            await asyncio.sleep(self.pause)
        self.requests += 1
        a = await client.fetch(url, headers=headers, data=data)
        verdict, why = judge(a)
        log.info("%s %s %s%s", url, a.status or "-", verdict, f" ({why})" if why else "")
        return a

    def same_site(self, url: str) -> str | None:
        """The address on the home page's host, or None: elsewhere, an asset,
        a cart or account page, or one robots.txt keeps from everyone."""
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if parts.scheme not in ("http", "https") or host.removeprefix("www.") != self.host.removeprefix("www."):
            return None
        url = parts._replace(scheme=self.scheme, netloc=self.host, fragment="").geturl()
        if ASSET.search(parts.path) or SKIPPED_PATHS.search(parts.path) or not self.robots.can_fetch("*", url):
            return None
        return url

    async def run(self) -> Findings:
        began = time.monotonic()
        f = self.f
        scout = self.make("curl-chrome")
        try:
            await self.look_around(scout)
        finally:
            await scout.aclose()
        await self.clients()
        await self.user_agents()
        await self.real_browser()
        await self.platform()
        await self.product()
        await self.not_found()
        await self.product_sample()
        f["sources"] = sources_of([a for a in (self.home_answer, self.product_answer) if a])
        f["rendering"] = {
            name: drawn(a)
            for name, a in (("home", self.home_answer), ("product", self.product_answer))
            if a and judge(a)[0] == "ok"
        }
        f["freshness"] = freshness([self.home_answer, *self.sample_answers])
        await self.session_lock()
        f["vendors"] = vendors_of(self.seen)
        f["ua_filter"] = ua_filter(f)
        await self.burst()
        f["protection"] = protection(f)
        f["way_in"] = way_in(f)
        f["rate_headers"] = rate_headers(self.seen)
        f["notes"] = notes_on(self.host, self.notes)
        f["requests"] = self.requests
        f["seconds"] = round(time.monotonic() - began, 1)
        return f

    async def look_around(self, scout: Client) -> None:
        """The home page, its redirects followed; robots.txt; the sitemaps;
        the deeper page; the pool of pages for the session test and the burst."""
        f, url = self.f, self.start
        self.seen: list[Answer] = []
        self.deep_answer: Answer | None = None
        self.product_answer: Answer | None = None
        self.sample_answers: list[Answer] = []
        for _ in range(settings.REDIRECTS + 1):
            home = await self.get(scout, url)
            self.seen.append(home)
            if home.status and 300 <= home.status < 400 and home.location:
                url = urljoin(url, home.location)
                continue
            break
        self.home, self.home_answer = url, home
        parts = urlsplit(url)
        self.scheme, self.host = parts.scheme, parts.netloc.lower()
        self.origin = f"{self.scheme}://{self.host}"
        f["home"] = url
        f["home_answer"] = summary(home)

        robots = await self.get(scout, self.origin + "/robots.txt")
        self.seen.append(robots)
        self.robots = RobotFileParser()
        self.robots_text = robots.text if robots.status == 200 else ""
        lines = self.robots_text.splitlines()
        self.robots.parse(lines)
        sitemaps = [line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:")]
        f["robots"] = {
            "status": robots.status,
            "verdict": judge(robots)[0],
            "disallow": sum(line.lower().startswith("disallow:") and line[9:].strip() != "" for line in lines),
            "crawl_delay": next(
                (line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("crawl-delay:")), None
            ),
            "sitemaps": sitemaps,
        }
        try:
            self.crawl_delay = float(f["robots"]["crawl_delay"] or 0) or None
        except ValueError:
            self.crawl_delay = None
        if self.crawl_delay and self.crawl_delay > self.pause and not self.pause_given:
            self.pause = self.crawl_delay
            log.info(
                "robots.txt asks Crawl-delay %g s: one request every %g s from here (--pause to choose)",
                self.crawl_delay,
                self.pause,
            )
        f["pause"] = self.pause

        await self.sitemaps(
            scout, sitemaps or [self.origin + path for path in settings.SITEMAP_PATHS], guessed=not sitemaps
        )
        links = [u for u in (self.same_site(urljoin(url, h)) for h in HREF.findall(home.text)) if u]
        listed = [u for u in (self.same_site(u) for u in self.listed) if u]
        pool = list(dict.fromkeys(listed + links))
        pool = [u for u in pool if u.rstrip("/") != url.rstrip("/")]
        products = [u for u in pool if PRODUCT_HINT.search(urlsplit(u).path) or PRODUCT_HINT.search(urlsplit(u).query)]
        # products from all over the sitemap: its first ones can all be one dead corner of the catalogue
        random.Random(0).shuffle(products)
        self.links, self.products = links, products
        self.deep: str | None = self.page or next(iter(products or pool), None)
        random.Random(0).shuffle(pool)  # pages from all over the sitemap, not one corner of it
        self.pool = pool
        f["page"] = self.deep
        f["page_from"] = "--page" if self.page else ("a product link" if products else "the first link")
        f["pool"] = len(pool)

    async def sitemaps(self, scout: Client, queue: list[str], guessed: bool = False) -> None:
        """Every sitemap file robots.txt names, and those its indexes list,
        SITEMAP_FILES at most: how many addresses, and a sample of them. With
        none named, SITEMAP_PATHS in turn until one answers."""
        read = listed = 0
        found: list[str] = []
        lastmods: list[str] = []
        files: list[dict[str, Any]] = []
        queue, seen = list(queue), set()
        while queue and read < settings.SITEMAP_FILES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            a = await self.get(scout, url)
            read += 1
            if a.status != 200:
                files.append({"url": url, "status": a.status, "verdict": judge(a)[0]})
                continue
            if guessed:  # the first guess that answers is the sitemap: the others are not asked
                queue, guessed = [], False
            try:
                kind, locs, mods = read_sitemap(a.body)
            except (OSError, EOFError, zlib.error) as e:
                files.append({"url": url, "status": a.status, "verdict": f"unreadable: {e}"})
                continue
            files.append({"url": url, "status": a.status, "kind": kind, "addresses": len(locs)})
            if kind == "index":
                queue.extend(locs)
            else:
                listed += len(locs)
                found.extend(locs[: max(0, settings.SAMPLE_URLS - len(found))])
                lastmods.extend(mods)
        self.listed = found
        self.f["sitemap"] = {
            "files_read": read,
            "files_left": len([u for u in queue if u not in seen]),
            "addresses": listed,
            "lastmod": [min(lastmods), max(lastmods)] if lastmods else None,
            "files": files[:40],
        }

    def pages(self) -> list[str]:
        return [p for p in (self.home, self.deep, self.origin + "/robots.txt") if p]

    async def clients(self) -> None:
        """Every client of CLIENTS with a browser User-Agent on the three pages."""
        rows = []
        for kind in settings.CLIENTS:
            client = self.make(kind)
            try:
                for url in self.pages():
                    a = await self.get(client, url)
                    self.seen.append(a)
                    rows.append({"client": kind, "page": url, **summary(a)})
                    # the platform is read from a home page let in, not from a challenge
                    if url == self.home and judge(a)[0] == "ok" and judge(self.home_answer)[0] != "ok":
                        self.home_answer = a
                    if url == self.deep and self.deep_answer is None and judge(a)[0] == "ok":
                        self.deep_answer = a
            finally:
                await client.aclose()
        self.f["clients"] = rows
        main_pages = self.pages()[:2]
        let_in = [
            k
            for k in settings.CLIENTS
            if all(passes(r["verdict"]) for r in rows if r["client"] == k and r["page"] in main_pages)
        ]
        self.best = let_in[0] if let_in else None
        self.f["let_in"] = let_in

    def ua_for(self, kind: str) -> str | None:
        return None if kind.startswith("curl-") else settings.CHROME_UA

    async def user_agents(self) -> None:
        rows = []
        if self.best:
            for name, ua in settings.UAS.items():
                client = self.make(self.best, ua=ua)
                try:
                    a = await self.get(client, self.home)
                finally:
                    await client.aclose()
                self.seen.append(a)
                rows.append({"ua": name, **summary(a)})
        self.f["uas"] = rows
        self.f["uas_through"] = self.best

    async def real_browser(self) -> None:
        """Chrome on the deeper page when a client was challenged there or on the home page."""
        challenged = [r for r in self.f["clients"] if r["verdict"] == "challenge"]
        if not (challenged or self.force_browser):
            self.f["browser"] = None
            return
        url = challenged[0]["page"] if challenged else (self.deep or self.home)
        try:
            seen = await self.browse(url)
        except Exception as e:
            self.f["browser"] = {"url": url, "error": f"{type(e).__name__}: {e}"[:300]}
            return
        self.requests += 1
        seen["url"] = url
        carried = []
        clearance = seen.pop("cf_clearance", None)
        if clearance:
            for kind in dict.fromkeys(r["client"] for r in challenged if r["page"] == url):
                client = self.make(kind, ua=seen["ua"])
                try:
                    a = await self.get(client, url, headers={"Cookie": f"cf_clearance={clearance}"})
                finally:
                    await client.aclose()
                carried.append({"client": kind, **summary(a)})
        seen["clearance_carried"] = carried
        self.f["browser"] = seen

    async def platform(self) -> None:
        platforms, stacks, generator = platforms_of(self.home_answer, self.robots_text, self.notes)
        self.f["platforms"] = [{"name": n, "evidence": e, "note": note} for n, e, note in platforms]
        self.f["stacks"] = [{"name": n, "evidence": e} for n, e in stacks]
        self.f["generator"] = generator
        apis = []
        client = self.make(self.best or "curl-chrome", ua=self.ua_for(self.best or "curl-chrome"))
        try:
            for name, _, _ in platforms:
                asked = api_request(name, self.origin, self.home_answer.text)
                if asked is None:
                    if name == "BigCommerce":
                        apis.append(
                            {
                                "platform": name,
                                "url": None,
                                "says": "no storefront GraphQL token in the page: the categories' pages, then",
                            }
                        )
                    continue
                method, url, headers, body = asked
                a = await self.get(client, url, headers=headers, data=body)
                self.seen.append(a)
                apis.append({"platform": name, "url": url, "method": method, **summary(a), "says": api_says(name, a)})
        finally:
            await client.aclose()
        self.f["apis"] = apis

    async def product(self) -> None:
        """What a product page carries: the deeper page, or up to PRODUCT_TRIES
        more product links when it carries nothing."""
        tried, client, partial = [], None, None
        candidates = [self.deep, *[u for u in self.products if u != self.deep][: settings.PRODUCT_TRIES]]
        try:
            for url in filter(None, candidates):
                a = self.deep_answer if url == self.deep else None
                if a is None:
                    if not self.best:
                        break
                    client = client or self.make(self.best, ua=self.ua_for(self.best))
                    a = await self.get(client, url)
                    self.seen.append(a)
                tried.append(url)
                if judge(a)[0] != "ok":
                    continue
                data = product_data(a)
                if data["found"]:
                    self.product_answer = a
                    self.f["product"] = {"url": url, "tried": tried, **data}
                    return
                if partial is None and data["labels"]:
                    partial = {"url": url, "labels": data["labels"]}
        finally:
            if client:
                await client.aclose()
        self.f["product"] = {"url": None, "tried": tried, "found": False, "partial": partial}

    async def not_found(self) -> None:
        """Pages that are not there: a made-up product shaped like the real
        one, a made-up path, and page FAR_PAGE of a listing beside its real
        page - the home page's or the product page's paging link, else one
        found on the first other link of the home page."""
        f = self.f
        if not self.best:
            f["not_found"] = {"skipped": "no client let in"}
            return
        product = (f.get("product") or {}).get("url") or self.deep
        probes = [("a made-up product", made_up(product))] if product else []
        probes.append(("a made-up path", f"{self.origin}/{settings.NONCE}-no-such-page/"))
        client = self.make(self.best, ua=self.ua_for(self.best))
        rows = []
        try:
            near = list(self.links)
            if self.product_answer:
                near += [
                    u
                    for u in (
                        self.same_site(urljoin(self.product_answer.url, h))
                        for h in HREF.findall(self.product_answer.text)
                    )
                    if u
                ]
            listing = listing_page(near)
            if not listing:
                category = next((u for u in self.links if u not in self.products), None)
                if category:
                    a = await self.get(client, category)
                    self.seen.append(a)
                    listing = listing_page(
                        [u for u in (self.same_site(urljoin(category, h)) for h in HREF.findall(a.text)) if u]
                    )
            if listing:
                probes += [("a listing page", listing[0]), (f"its page {settings.FAR_PAGE}", listing[1])]
            for name, url in probes:
                a = await self.get(client, url)
                self.seen.append(a)
                rows.append(
                    {
                        "probe": name,
                        "url": url,
                        **summary(a),
                        "title": title_of(a),
                        "bytes": len(a.body),
                        "location": a.location,
                    }
                )
        finally:
            await client.aclose()
        f["not_found"] = {"rows": rows, "findings": not_found_findings(rows)}

    async def at_once(
        self, client: Client, urls: list[str], limit: int, lost_max: int | None = None
    ) -> tuple[list[Answer], float]:
        """The answers to `urls`, `limit` at a time, in the order they came.
        Nothing more is sent after a refusal, or once `lost_max` are lost."""
        gate = asyncio.Semaphore(limit)
        answers: list[Answer] = []
        lost: list[Answer] = []
        stopped: list[Answer] = []

        async def one(url: str) -> None:
            async with gate:
                if stopped:
                    return
                self.requests += 1
                a = await client.fetch(url)
                answers.append(a)
                verdict = judge(a)[0]
                if verdict in LOST:
                    lost.append(a)
                if verdict in REFUSALS or (lost_max and len(lost) >= lost_max):
                    stopped.append(a)

        began = time.monotonic()
        await asyncio.gather(*(one(u) for u in urls))
        return answers, time.monotonic() - began

    async def product_sample(self) -> None:
        """The product page found and more product links, up to --products in
        all: what share carries each field, and the traps in them."""
        f = self.f
        first = (f.get("product") or {}).get("url")
        urls = list(dict.fromkeys(([first] if first else []) + self.products))[: self.sample_size]
        if not self.best or not urls or self.sample_size <= 0:
            f["sample"] = {
                "skipped": "no client let in" if not self.best else "no product links" if not urls else "--products 0"
            }
            return
        records, client = [], self.make(self.best, ua=self.ua_for(self.best))
        try:
            for url in urls:
                a = self.product_answer if url == first and self.product_answer else None
                if a is None:
                    a = await self.get(client, url)
                    self.seen.append(a)
                self.sample_answers.append(a)
                if judge(a)[0] == "ok":
                    records.append(page_record(a))
        finally:
            await client.aclose()
        f["sample"] = {"asked": len(urls), **sample_findings(records)}

    async def session_lock(self) -> None:
        """SESSION_PAGES pages with one cookie jar, then as many others with
        none; other pages, so the second set is not served from a cache the
        first one warmed."""
        f = self.f
        if self.crawl_delay:  # several at a time is what the delay asks not to do
            f["session"] = {"skipped": f"robots.txt asks Crawl-delay {self.crawl_delay:g}"}
            return
        cookies = {c for a in self.seen if not a.error for c in a.cookies}
        if not self.best or not cookies or len(self.pool) < 2 * settings.SESSION_AT_ONCE:
            f["session"] = {
                "skipped": "no client let in" if not self.best else "no cookie set" if not cookies else "too few pages"
            }
            return
        half = min(settings.SESSION_PAGES, len(self.pool) // 2)
        sets = {"with one jar": self.pool[:half], "with no cookies": self.pool[half : 2 * half]}
        result: dict[str, Any] = {"cookies_set": sorted(cookies), "pages": half}
        for mode, urls in sets.items():
            client = self.make(self.best, ua=self.ua_for(self.best), cookies=mode == "with one jar")
            try:
                if mode == "with one jar":
                    self.seen.append(await self.get(client, self.home))  # the session's cookie
                answers, wall = await self.at_once(client, urls, settings.SESSION_AT_ONCE)
            finally:
                await client.aclose()
            self.seen.extend(answers)
            took = [a.seconds for a in answers if not a.error]
            result[mode] = {
                "per_s": round(len(answers) / wall, 2),
                "p50": percentile(took, 0.5),
                "answers": counts(answers),
            }
            if any(judge(a)[0] in REFUSALS for a in answers):
                result["refused"] = mode
                break
        if "refused" not in result:
            jar, none = result["with one jar"]["per_s"], result["with no cookies"]["per_s"]
            result["lock"] = jar < settings.LOCK_SHARE * none
        f["session"] = result

    async def burst(self) -> None:
        f = self.f
        why = burst_blockers(f)
        if why:  # the site's own reason first: it says more than --no-burst
            f["burst"] = {"skipped": why}
            return
        if not self.burst_allowed:
            f["burst"] = {"skipped": ["--no-burst"]}
            return
        if not self.pool or self.best is None:
            f["burst"] = {"skipped": ["no pages to ask for" if self.best else "no client let in"]}
            return
        client = self.make(self.best, ua=self.ua_for(self.best))
        steps: list[dict[str, Any]] = []
        stop: str | None = None
        first_p50: float | None = None
        http: str | None = None
        urls = itertools.cycle(self.pool)
        try:
            for limit, n in settings.STEPS:
                if limit > settings.H1_MOST and http != "h2":
                    break
                answers, wall = await self.at_once(
                    client, [next(urls) for _ in range(n)], limit, lost_max=settings.LOST_MAX
                )
                self.seen.extend(answers)
                log.info("burst: %d at a time, %d answered in %.1fs: %s", limit, len(answers), wall, counts(answers))
                http = http or next((a.http for a in answers if a.http), None)
                took = [a.seconds for a in answers if not a.error]
                p50 = percentile(took, 0.5)
                step = {
                    "at_once": limit,
                    "asked": n,
                    "answered": len(answers),
                    "per_s": round(len(answers) / wall, 2),
                    "p50": p50,
                    "p95": percentile(took, 0.95),
                    "answers": counts(answers),
                }
                steps.append(step)
                refused = [a for a in answers if judge(a)[0] in REFUSALS]
                lost = [a for a in answers if judge(a)[0] in LOST]
                failed = [a for a in answers if judge(a)[0] == "server-error"]
                if refused:
                    a = refused[0]
                    verdict, said = judge(a)
                    stop = f"{a.status} {verdict}{f' ({said})' if said else ''} at {limit} at a time"
                elif len(lost) >= settings.LOST_MAX:
                    stop = f"{len(lost)} connections lost at {limit} at a time ({judge(lost[0])[1]})"
                elif len(failed) > settings.FAILED_SHARE * len(answers):
                    stop = f"{len(failed)} of {len(answers)} answers were server errors at {limit} at a time"
                elif (
                    first_p50 is not None
                    and p50 is not None
                    and p50 > max(settings.SLOW_FACTOR * first_p50, settings.SLOW_FLOOR)
                ):
                    stop = f"answers slowed to {p50:.2f}s against {first_p50:.2f}s at {limit} at a time"
                if stop:
                    break
                first_p50 = p50 if first_p50 is None else first_p50
            asked = sum(s["answered"] for s in steps)
            result: dict[str, Any] = {
                "client": self.best,
                "http": http,
                "steps": steps,
                "stop": stop,
                "asked": asked,
                "distinct": min(asked, len(self.pool)),
            }
            if stop:
                await asyncio.sleep(settings.RECOVER)
                a = await self.get(client, self.home, pause=False)
                self.seen.append(a)
                result["after"] = {"seconds": settings.RECOVER, **summary(a)}
        finally:
            await client.aclose()
        f["burst"] = result

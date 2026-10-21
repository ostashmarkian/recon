"""recon - look a website over before you scrape it.

    recon https://www.example.com [--page URL] [--products N] [--browser] [--no-burst] [--no-watch]
                                  [--long [MIN]] [--notes DIR] [--compare FILE] [--pause S] [--out DIR]

What stands between a scraper and a site, in one report: its protection and
the way in, its platform and open API, what its product pages carry and how
clean that is, how it answers for pages that are not there, where its
catalogue can be read from, how fresh its pages are, and the pace it allows.
The report goes to recon-reports/<host>-<when>.md and .json and to stdout;
the newest earlier .json of the same host there, or --compare FILE, is set
against it: what changed since.

1. The home page (its redirects on the site followed: one to another site
   stops the run, which names the address to run on), robots.txt, the sitemaps it names
   or else the first of SITEMAP_PATHS that answers (SITEMAP_FILES at most,
   redirects on the site followed and named), and one deeper page: --page,
   or a product the sitemap or the home page's links point to, picked at
   random so one dead corner of a sitemap is not all it sees. Links with a
   product's own word (/products/, /p/, /item/) come before those with only
   a long number, and those under a listing's word (/category/) come last.
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
   stock, and the product its state holds (Nuxt's __NUXT_DATA__, Next.js's
   __NEXT_DATA__). The deeper page, or up to PRODUCT_TRIES more product links
   when it shows none. A page that lists products (a JSON-LD ItemList, several
   Products, a product list in its state with its counts, a page number) is a
   listing, not a product: it is tried as none and left out of the sample.
   Then a sample of --products pages (SAMPLE_PRODUCTS): how many
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
   The site's own API, on every run and without a browser: the API bases the
   pages' runtime config names (window.__NUXT__.config, __NEXT_DATA__, an
   apiHost in a script), each host looked up in DNS - one with no public DNS
   is internal and never asked - and a public one asked once, its robots.txt,
   for who stands in front of it; the routes the pages' own JS bundles name
   (BUNDLES_MOST files, on the site's domain or the CDN its config names, a
   host not public never asked), and a helper that adds parameters to them;
   the product lists the pages' state holds, with their counts; and list or
   search routes asked with the plain client let in, on the site's own API
   base first, once more with a part number when the answer says it lacks a
   search word. The API's own refusals (a 401 for a key) are not the site's.
   Then, where patchright and Chrome are there (--no-watch to skip it), the
   home page, the product page and a listing (one found to list products) in
   Chrome: the XHR and fetch calls they make, each product list asked once
   more without the browser.
8. Freshness: cache statuses, Age and Last-Modified on the pages read. Pages
   served from a cache days old show stock and prices days old.
9. A session lock: SESSION_PAGES pages SESSION_AT_ONCE at a time with one
   cookie jar, and as many others with none. Some servers (ASP.NET, PHP
   sessions) serve one session's requests one at a time: 0.8 pages/s with a
   jar against 11 without was seen. With --long, then one session over
   --long minutes, a request every 5 to 10 s: a service that scores clients
   over a session (a bot manager) lets a short run in and turns a long one
   away. It runs behind protection too, being slower than the rest. An answer
   lost there is checked against NEUTRAL_HOSTS: when they fail too, the local
   link failed, the site is not judged, and the session waits and goes on.
10. A burst, only when nothing above found protection - no anti-bot service
   in front, no client with a browser User-Agent turned away - and robots.txt
   asks for no Crawl-delay. A filter of User-Agents by name (GPTBot,
   Python-urllib, ...) is reported but does not stop it: the burst sends a
   browser's. STEPS of 1, 2, 4, 8 and 16 at a time, 350 requests at most over
   distinct pages robots.txt allows; 16 only over HTTP/2, since over HTTP/1.1
   each request in flight is a connection, and a firewall counting them shut
   an IP out for 29 min at 16. It stops at the first refusal, at the
   LOST_MAX-th connection lost, when answers slow to SLOW_FACTOR times the
   first step's, when a tenth of a step fails, or when 200s shrink: SHRUNK_MAX
   under SHRUNK_SHARE of the first step's smallest page, and one of them as
   much bigger read alone (a 644-byte PHP warning in place of product pages
   was seen, the shop's database connections spent). After a stop it asks
   once more RECOVER s later, to say whether the site has let go.

Everything else goes one request at a time, PAUSE apart, or robots.txt's
Crawl-delay apart when it asks for more (then no session test either).
Rate-limit headers seen on any answer are reported, and with --notes, the
notes in a folder of Markdown (an Obsidian vault, say) that name the domain
or the platform. A cell of the report reads "403 challenge (Cloudflare),
h2 0.21s".
"""

import asyncio
import html as entities
import itertools
import logging
import random
import time
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from . import settings
from .api import (
    all_private,
    api_bases,
    builds_of,
    bundle_refs,
    chunk_refs,
    failed,
    fill_for,
    helpers_in,
    internal_name,
    lists_to_ask,
    message_of,
    names_api,
    resolve,
    route_kind,
    routes_in,
    same_domain,
    scripts_of,
    wanted,
)
from .browser import BrowserMissing, open_in_browser, watch_in_browser
from .calls import as_json, call_record, rank, replay_headers, shape
from .classify import LOST, REFUSALS, cname_vendor, judge, title_of, vendors_of
from .clients import Answer, Client, make_client
from .findings import (
    Findings,
    burst_blockers,
    counts,
    not_found_findings,
    percentile,
    protection,
    protection_level,
    summary,
    ua_filter,
    way_in,
)
from .notes import notes_on, read_notes
from .pages import (
    ASSET,
    HREF,
    LISTING_PATH,
    PRODUCT_HINT,
    PRODUCT_PATH,
    SITEMAP_HINT,
    SKIPPED_PATHS,
    by_family,
    drawn,
    family,
    freshness,
    listing_of,
    listing_page,
    made_up,
    product_data,
    rate_headers,
    read_sitemap,
    sources_of,
    spread,
)
from .platforms import api_request, api_says, platforms_of
from .robots import Robots
from .robots import parse as parse_robots
from .sample import page_record, sample_findings
from .state import read_state, short

log = logging.getLogger(__name__)


def looks_like_sitemap(body: bytes) -> bool:
    """A sitemap file: gzip, or XML with <urlset> or <sitemapindex> near its start."""
    start = body[:4000].lower()
    return body[:2] == b"\x1f\x8b" or b"<urlset" in start or b"<sitemapindex" in start


def join(base: str, href: str) -> str | None:
    """`href` read against `base`, entities decoded; None for an address Python cannot parse."""
    try:
        return urljoin(base, entities.unescape(href).strip())
    except ValueError:
        return None


def same_host(a: str, b: str) -> bool:
    """Two addresses on one site: the same host, "www." or not."""
    try:
        return (urlsplit(a).hostname or "").removeprefix("www.") == (urlsplit(b).hostname or "").removeprefix("www.")
    except ValueError:
        return False


async def fetch_within(
    client: Client, url: str, headers: dict[str, str] | None = None, data: bytes | None = None
) -> Answer:
    """client.fetch(), given REQUEST_MOST seconds in all."""
    try:
        return await asyncio.wait_for(client.fetch(url, headers=headers, data=data), settings.REQUEST_MOST)
    except TimeoutError:
        return Answer(
            url, error=f"TimeoutError: no answer within {settings.REQUEST_MOST} s", seconds=settings.REQUEST_MOST
        )


# Steps whose refusals keep the burst off; the User-Agent test is left out: refusing bots by name is not a limit
WATCHED_STEPS = ("sitemaps", "platform", "product", "not_found", "sample", "api")


def replayed(record: dict[str, Any], a: Answer, got: dict[str, Any], client: str | None) -> dict[str, Any]:
    """What a call the pages made got when asked again without the browser: does it work, as long a list?"""
    works = judge(a)[0] == "ok" and got["kind"] == record["kind"]
    if works and record["kind"] == "products":  # as many items: no shorter list for a stranger
        works = got.get("items", 0) * 2 >= record.get("items", 0)
    return {
        "client": client,
        "status": a.status,
        "verdict": judge(a)[0],
        "kind": got["kind"],
        "items": got.get("items"),
        "works": works,
    }


def said_of(data: Any) -> str | None:
    """What a JSON answer says of itself: its code and message, "code 0, msg success"."""
    if not isinstance(data, dict):
        return None
    said = [
        f"{k} {short(v, 40)}"
        for k, v in data.items()
        if str(k).lower() in ("code", "status", "msg", "message", "error", "errmsg", "error_msg")
        and isinstance(v, (str, int, float))
        and not isinstance(v, bool)
    ]
    return ", ".join(said[:3]) or None


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
        long: float | None = None,
        watch: bool = True,
        watcher: Callable[[list[str]], Awaitable[dict[str, Any]]] | None = None,
        resolve: Callable[[str], Awaitable[dict[str, Any]]] = resolve,
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
        self.long_minutes = long  # --long: minutes of one slow session, or None for none
        self.watch_allowed, self.watcher = watch, watcher or watch_in_browser  # what the pages fetch, in Chrome
        self.resolve = resolve  # a host's DNS: its addresses and canonical name
        self.requests = 0
        self.step: str | None = None  # the step under way, for refusals seen in it
        self.refused: dict[str, dict[str, int]] = {s: {} for s in WATCHED_STEPS}
        self.stopped: str | None = None  # why the run stopped early
        parts = urlsplit(url)
        self.scheme, self.host = parts.scheme, (parts.hostname or "").lower()
        self.origin = f"{self.scheme}://{parts.netloc}"
        self.home, self.home_answer = url, Answer(url, error="not asked")
        self.robots, self.robots_text = Robots(), ""
        self.seen: list[Answer] = []
        self.deep: str | None = None
        self.deep_answer: Answer | None = None
        self.product_answer: Answer | None = None
        self.sample_answers: list[Answer] = []
        self.links: list[str] = []
        self.products: list[str] = []
        self.others: list[str] = []  # the sitemap's pages that do not look like products
        self.pool: list[str] = []
        self.listed: list[str] = []
        self.listings: dict[str, Answer] = {}  # pages found to be listings, LISTINGS_KEPT of them with their answer
        self.host_robots: dict[str, Robots] = {}  # the robots.txt of each API host asked
        self.dns_seen: dict[str, dict[str, Any]] = {}  # each other host looked up: its DNS, public or internal
        self.internal_hosts: set[str] = set()  # hosts no public DNS holds, or private ones: never asked
        self.api_answers: dict[tuple[str, str], tuple[Answer, dict[str, Any]]] = {}  # (method, url): answer, shape
        self.api_hosts: dict[str, dict[str, Any]] = {}  # what each API host is: its DNS, what answered its robots.txt
        self.best: str | None = None
        self.f: Findings = {"url": url, "began": datetime.now().astimezone().isoformat(timespec="seconds")}

    async def get(
        self,
        client: Client,
        url: str,
        headers: dict[str, str] | None = None,
        pause: bool = True,
        data: bytes | None = None,
        own: bool = True,
    ) -> Answer:
        """One request, PAUSE after the one before. A refusal in a watched step keeps the burst off; with `own`
        False it is not the site's: an API route's answer (a 401 is its key, not a guard) or another host's."""
        if pause and self.requests:
            await asyncio.sleep(self.pause)
        self.requests += 1
        a = await fetch_within(client, url, headers, data)
        verdict, why = judge(a)
        if verdict in REFUSALS and self.step in WATCHED_STEPS and own:
            self.refused[self.step][verdict] = self.refused[self.step].get(verdict, 0) + 1
        log.info("%s %s %s%s", url, a.status or "-", verdict, f" ({why})" if why else "")
        return a

    def keep(self, *answers: Answer) -> None:
        """Answers for the findings that read only headers, cookies and the first HEAD bytes: kept that light,
        so a run of 450 answers on 1 MB pages does not hold half a gigabyte."""
        self.seen.extend(replace(a, body=a.body[: settings.HEAD]) for a in answers)

    def same_site(self, url: str | None) -> str | None:
        """The address on the home page's host, or None: elsewhere, an asset,
        a cart or account page, one robots.txt keeps from everyone, or not an address."""
        if not url:
            return None
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        host = parts.netloc.lower()
        if parts.scheme not in ("http", "https") or host.removeprefix("www.") != self.host.removeprefix("www."):
            return None
        url = parts._replace(scheme=self.scheme, netloc=self.host, fragment="").geturl()
        if ASSET.search(parts.path) or SKIPPED_PATHS.search(f"{parts.path}?{parts.query}"):
            return None
        return url if self.robots.allows(url) else None

    async def run(self) -> Findings:
        began = time.monotonic()
        f = self.f
        try:
            scout = self.make("curl-chrome")
            try:
                await self.isolated("look_around", lambda: self.look_around(scout))
            finally:
                await scout.aclose()
            if self.stopped:
                return self.stop_early(began)
            for name, do in (
                ("clients", self.clients),
                ("user_agents", self.user_agents),
                ("browser", self.real_browser),
                ("platform", self.platform),
                ("product", self.product),
                ("not_found", self.not_found),
                ("sample", self.product_sample),
                ("api", self.api),
                ("watch", self.watch),
            ):
                await self.isolated(name, do)
            f["refused_elsewhere"] = {step: got for step, got in self.refused.items() if got}
            self.computed(
                "sources",
                lambda: sources_of([a for a in (self.home_answer, self.product_answer, *self.listings.values()) if a]),
            )
            self.computed(
                "rendering",
                lambda: {
                    name: drawn(a)
                    for name, a in (("home", self.home_answer), ("product", self.product_answer))
                    if a and judge(a)[0] == "ok"
                },
            )
            self.computed("freshness", lambda: freshness([self.home_answer, *self.sample_answers]))
            await self.isolated("session_lock", self.session_lock)
            if self.long_minutes:
                await self.isolated("long", self.long_session)
            self.computed("vendors", lambda: vendors_of(self.seen))
            self.computed("ua_filter", lambda: ua_filter(f))
            await self.isolated("burst", self.burst)
        finally:  # whatever broke, the findings close with what the report needs
            if not self.stopped:  # a run stopped early judged nothing: no level, no way in
                self.computed("protection", lambda: protection(f), [])
                self.computed("level", lambda: protection_level(f))
                self.computed("way_in", lambda: way_in(f), "unknown: the run broke before it was found")
            self.computed("rate_headers", lambda: rate_headers(self.seen))
            self.computed("notes", lambda: notes_on(self.host, self.notes))
            f["requests"] = self.requests
            f["seconds"] = round(time.monotonic() - began, 1)
        return f

    async def isolated(self, name: str, do: Callable[[], Awaitable[None]]) -> None:
        """One step; its failure is written down in the findings, and the run goes on."""
        self.step = name if name in WATCHED_STEPS else None
        try:
            await do()
        except Exception as e:
            log.exception("%s failed", name)
            self.f.setdefault("errors", []).append({"step": name, "error": f"{type(e).__name__}: {e}"[:300]})
        finally:
            self.step = None

    def computed(self, key: str, make: Callable[[], Any], fallback: Any = None) -> None:
        """f[key] = make(); its failure is written down, and f[key] is `fallback`."""
        try:
            self.f[key] = make()
        except Exception as e:
            log.exception("%s failed", key)
            self.f.setdefault("errors", []).append({"step": key, "error": f"{type(e).__name__}: {e}"[:300]})
            self.f[key] = fallback

    def stop_early(self, began: float) -> Findings:
        """The findings of a run that stopped after robots.txt: what it saw, and why it stopped."""
        f = self.f
        f.update(stopped=self.stopped, protection=[], way_in="not looked at", vendors=vendors_of(self.seen))
        f["requests"] = self.requests
        f["seconds"] = round(time.monotonic() - began, 1)
        return f

    async def read_robots(self, scout: Client) -> tuple[Robots, str, Answer, str]:
        """robots.txt, its redirects followed (RFC 9309 asks for five at least, across hosts too):
        (its rules, "read" | "not there" | "unreadable", the last answer, its address)."""
        url = self.origin + "/robots.txt"
        for _ in range(settings.REDIRECTS + 1):
            a = await self.get(scout, url)
            self.keep(a)
            if a.status and 300 <= a.status < 400 and a.location:
                url = urljoin(url, a.location)
                continue
            break
        verdict = judge(a)[0]
        if a.status == 200 and verdict == "ok":
            return parse_robots(a.text), "read", a, url
        if a.status and 400 <= a.status < 500 and verdict not in REFUSALS:
            return Robots(), "not there", a, url  # the RFC: no robots.txt, nothing disallowed
        # a 5xx, a refusal or no answer: the RFC's "unreachable", so everything counts as disallowed
        return Robots(disallow_all=True), "unreadable", a, url

    async def look_around(self, scout: Client) -> None:
        """The home page, its redirects followed; robots.txt; the sitemaps;
        the deeper page; the pool of pages for the session test and the burst."""
        f, url = self.f, self.start
        self.seen = []
        self.deep_answer = None
        self.product_answer = None
        self.sample_answers = []
        for _ in range(settings.REDIRECTS + 1):
            home = await self.get(scout, url)
            self.keep(home)
            if not (home.status and 300 <= home.status < 400 and home.location):
                break
            hop = join(url, home.location)
            if hop is None or judge(home)[0] == "blocked" or not same_host(hop, url):
                why = "a block" if judge(home)[0] == "blocked" else "another site" if hop else "not an address"
                f["home_redirect"] = f"{home.status} to {home.location}: not followed ({why})"
                if why == "another site":  # a site that moved: its report is a run on the new address
                    self.stopped = (
                        f"the home page redirects ({home.status}) to {hop}, another site; recon looks at the site "
                        "it is given only: run it on that address"
                    )
                break
            url = hop
        self.home, self.home_answer = url, home
        parts = urlsplit(url)
        self.scheme, self.host = parts.scheme, parts.netloc.lower()
        self.origin = f"{self.scheme}://{self.host}"
        f["home"] = url
        f["home_answer"] = summary(home)
        if self.stopped:
            return

        self.robots, state, robots, robots_url = await self.read_robots(scout)
        self.robots_text = robots.text if state == "read" else ""
        sitemaps = self.robots.sitemaps
        f["robots"] = {
            "status": robots.status,
            "verdict": judge(robots)[0],
            "state": state,
            "url": robots_url,
            "disallow": self.robots.disallows,
            "crawl_delay": self.robots.crawl_delay_said,
            "sitemaps": sitemaps,
        }
        self.crawl_delay = self.robots.crawl_delay
        if self.crawl_delay and not self.pause_given:
            if self.crawl_delay > settings.CRAWL_DELAY_MOST:
                self.stopped = (
                    f"robots.txt asks Crawl-delay {self.robots.crawl_delay_said} s, more than recon's limit of "
                    f"{settings.CRAWL_DELAY_MOST:g} s; it stops here (--pause S goes on at a pace you choose)"
                )
                log.info(self.stopped)
                return
            if self.crawl_delay > self.pause:
                self.pause = self.crawl_delay
                log.info(
                    "robots.txt asks Crawl-delay %g s: one request every %g s from here (--pause to choose)",
                    self.crawl_delay,
                    self.pause,
                )
        f["pause"] = self.pause

        guesses = [self.origin + path for path in settings.SITEMAP_PATHS]
        self.step = "sitemaps"
        await self.sitemaps(scout, sitemaps or [u for u in guesses if self.robots.allows(u)], guessed=not sitemaps)
        self.step = None
        links = [u for u in (self.same_site(join(url, h)) for h in HREF.findall(home.head)) if u]
        listed = [u for u in (self.same_site(u) for u in self.listed) if u]
        pool = list(dict.fromkeys(listed + links))
        pool = [u for u in pool if u.rstrip("/") != url.rstrip("/")]
        hinted = [u for u in pool if PRODUCT_HINT.search(urlsplit(u).path) or PRODUCT_HINT.search(urlsplit(u).query)]
        # products from all over the sitemap: its first ones can all be one dead corner of the catalogue
        random.Random(0).shuffle(hinted)
        # a product's own word in the address first (/products/, /p/), then a bare long number, then such a number
        # under a listing's word (/category/usb/070403.html); each a family at a time, as "/products/" can be a
        # shop's marketing pages as well as its products
        strong = [u for u in hinted if PRODUCT_PATH.search(urlsplit(u).path)]
        weak = [u for u in hinted if not PRODUCT_PATH.search(urlsplit(u).path)]
        listy = [u for u in weak if LISTING_PATH.search(urlsplit(u).path)]
        listy_set = set(listy)
        products = by_family(strong) + by_family(u for u in weak if u not in listy_set) + by_family(listy)
        self.others = by_family(u for u in listed if u not in set(products))  # the sitemap's other pages
        self.links, self.products = links, products
        self.deep = self.page or next(iter(products or pool), None)
        random.Random(0).shuffle(pool)  # pages from all over the sitemap, not one corner of it
        self.pool = pool
        f["page"] = self.deep
        f["page_from"] = "--page" if self.page else ("a product link" if products else "the first link")
        f["pool"] = len(pool)

    async def sitemaps(self, scout: Client, queue: list[str], guessed: bool = False) -> None:
        """The sitemap files robots.txt names, and those their indexes list, SITEMAP_FILES at most: how many
        addresses, and a sample of them. An index's files are read next, depth first, SITEMAP_CHILDREN of them
        picked from end to end, product files first: indexes of indexes would spend the whole budget on
        indexes otherwise. With none named, SITEMAP_PATHS in turn until one answers. The budget counts every
        address asked, guesses and redirects among them; "files_read" only the files that answered."""
        asked = read = listed = 0
        found: list[str] = []
        lastmods: list[str] = []
        files: list[dict[str, Any]] = []
        queue = spread(list(dict.fromkeys(queue)), len(queue), SITEMAP_HINT)
        seen: set[str] = set()
        named = set() if guessed else set(queue)  # every file robots.txt or a read index names; a guess is none
        fails = 0  # files in a row that did not answer
        while queue and asked < settings.SITEMAP_FILES and fails < settings.SITEMAP_FAILS_MOST:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            a, chain = await self.follow(scout, url)
            asked += len([c for c in chain if "why" not in c]) or 1  # each hop asked; one not followed has a why
            moved = {"chain": chain} if chain else {}
            if a.status != 200:
                files.append({"url": url, "status": a.status, "verdict": judge(a)[0], **moved})
                fails += 0 if guessed else 1
                final = chain[-1]["url"] if chain else url
                if guessed and chain and chain[-1]["status"] and urlsplit(final).path.rsplit("/", 1)[0]:
                    # a guess moved into a folder of its own and is not there: the same name in that folder
                    again = urljoin(final, urlsplit(url).path.rsplit("/", 1)[-1])
                    if again not in seen and again != final and self.robots.allows(again):
                        queue.insert(0, again)
                continue
            fails = 0
            if guessed and not looks_like_sitemap(a.body):  # a soft 404 page: try the next guess
                files.append({"url": url, "status": a.status, "verdict": "not a sitemap", **moved})
                continue
            if guessed:  # the first guess that answers is the sitemap: the others are not asked
                queue, guessed = [], False
                named.add(url)
            read += 1
            try:
                kind, locs, mods = read_sitemap(a.body)
            except (OSError, EOFError, ValueError, zlib.error) as e:
                files.append({"url": url, "status": a.status, "verdict": f"unreadable: {e}"})
                continue
            files.append({"url": url, "status": a.status, "kind": kind, "addresses": len(locs), **moved})
            if kind == "index":
                named.update(locs)
                queue[:0] = [u for u in spread(locs, settings.SITEMAP_CHILDREN, SITEMAP_HINT) if u not in seen]
            else:
                listed += len(locs)
                room = max(0, settings.SAMPLE_URLS - len(found))
                found.extend(spread(locs, min(room, settings.SITEMAP_URLS_PER_FILE)))  # from all over each file
                lastmods.extend(mods)
        self.listed = found
        self.f["sitemap"] = {
            "files_read": read,
            "asked": asked,
            "files_named": len(named),
            "files_left": len(named - seen),
            "addresses": listed,
            "lastmod": [min(lastmods), max(lastmods)] if lastmods else None,
            "files": files[:40],
        }

    async def follow(self, client: Client, url: str) -> tuple[Answer, list[dict[str, Any]]]:
        """`url`, its redirects on the site followed, REDIRECTS at most and each where robots.txt allows: the last
        answer, and the chain [{url, status}] when it moved. A hop to another site, or one robots.txt keeps out,
        is named with why and not asked."""
        a = await self.get(client, url)
        chain: list[dict[str, Any]] = []
        for _ in range(settings.REDIRECTS):
            if not (a.status and 300 <= a.status < 400 and a.location):
                break
            chain.append({"url": url, "status": a.status})
            hop = join(url, a.location)
            if (
                hop is None
                or not same_host(hop, self.home)
                or not self.robots.allows(hop)
                or hop in {c["url"] for c in chain}
            ):
                why = (
                    "not an address"
                    if hop is None
                    else "another site"
                    if not same_host(hop, self.home)
                    else "robots.txt disallows it"
                    if not self.robots.allows(hop)
                    else "a loop"
                )
                chain.append({"url": hop or a.location, "status": None, "why": why})
                return a, chain
            url = hop
            a = await self.get(client, url)
        if chain:
            chain.append({"url": url, "status": a.status})
        return a, chain

    def main_pages(self) -> list[str]:
        """The pages a client must be let in on: the home page, and the deeper page if there is one."""
        return [p for p in (self.home, self.deep) if p]

    def pages(self) -> list[str]:
        return [*self.main_pages(), self.origin + "/robots.txt"]

    async def clients(self) -> None:
        """Every client of CLIENTS with a browser User-Agent on the three pages."""
        rows = []
        for kind in settings.CLIENTS:
            client = self.make(kind)
            try:
                for url in self.pages():
                    a = await self.get(client, url)
                    self.keep(a)
                    rows.append({"client": kind, "page": url, **summary(a)})
                    # the platform is read from a home page let in, not from a challenge
                    if url == self.home and judge(a)[0] == "ok" and judge(self.home_answer)[0] != "ok":
                        self.home_answer = a
                    if url == self.deep and self.deep_answer is None and judge(a)[0] == "ok":
                        self.deep_answer = a
            finally:
                await client.aclose()
        self.f["clients"] = rows
        main_pages = self.main_pages()
        got = {
            k: [r["verdict"] for r in rows if r["client"] == k and r["page"] in main_pages] for k in settings.CLIENTS
        }
        # let in: refused and cut off on none of the main pages, answered on one at least. A 4xx is the page's own
        # and a timeout no refusal, so neither turns a client away; one that only timed out had no answer
        turned = {k for k, verdicts in got.items() if any(v in (*REFUSALS, "dropped") for v in verdicts)}
        let_in = [k for k, verdicts in got.items() if k not in turned and any(v not in LOST for v in verdicts)]
        self.best = let_in[0] if let_in else None
        self.f["let_in"] = let_in
        self.f["no_answer"] = [k for k in got if k not in turned and k not in let_in]

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
                self.keep(a)
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
                asked = api_request(name, self.origin, self.home_answer.head)
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
                if not self.robots.allows(url):
                    apis.append({"platform": name, "url": None, "says": f"robots.txt disallows {urlsplit(url).path}"})
                    continue
                a = await self.get(client, url, headers=headers, data=body)
                self.keep(a)
                apis.append({"platform": name, "url": url, "method": method, **summary(a), "says": api_says(name, a)})
        finally:
            await client.aclose()
        self.f["apis"] = apis

    async def product(self) -> None:
        """What a product page carries: the deeper page, or up to PRODUCT_TRIES more pages when it carries
        nothing: product links first, then the sitemap's other pages, a family of addresses at a time.
        A redirect on the site is followed once: /p/12 can stand for /product/12-name/. A page that lists products
        (an ItemList in its JSON-LD, its state's product list) is a listing, not a product: it is named and passed."""
        tried, client, partial = [], None, None
        listings: list[dict[str, str]] = []
        # products and the sitemap's other pages come a family at a time (by_family), so the tries meet several
        candidates = [u for u in [*self.products, *self.others] if u != self.deep]
        tries = 0
        try:
            for url in filter(None, [self.deep, *candidates]):
                if url != self.deep and family(url) in {family(u) for u in self.listings}:
                    continue  # of a family found to be listings
                if url != self.deep:
                    tries += 1
                    if tries > settings.PRODUCT_TRIES:
                        break
                a = self.deep_answer if url == self.deep else None
                if a is None:
                    if not self.best:
                        break
                    client = client or self.make(self.best, ua=self.ua_for(self.best))
                    a = await self.get(client, url)
                    self.keep(a)
                hop = self.same_site(join(url, a.location)) if judge(a)[0] == "redirect" else None
                if hop and hop != url and self.best:
                    client = client or self.make(self.best, ua=self.ua_for(self.best))
                    url, a = hop, await self.get(client, hop)
                    self.keep(a)
                tried.append(url)
                if judge(a)[0] != "ok":
                    continue
                data = product_data(a)
                if data["kind"] == "listing":  # its JSON-LD's first Product is the first of a list: no product page
                    self.note_listing(url, a)
                    listings.append({"url": url, "why": data["kind_why"]})
                    continue
                if data["found"]:
                    self.product_answer = a
                    self.f["product"] = {"url": url, "tried": tried, "listings": listings, **data}
                    return
                if partial is None and data["labels"]:
                    partial = {"url": url, "labels": data["labels"]}
        finally:
            if client:
                await client.aclose()
        self.f["product"] = {"url": None, "tried": tried, "found": False, "partial": partial, "listings": listings}

    def note_listing(self, url: str, a: Answer) -> None:
        """A page found to list products: kept, LISTINGS_KEPT at most, for its state and the pages it links to."""
        if url not in self.listings and len(self.listings) < settings.LISTINGS_KEPT:
            self.listings[url] = a

    def listing_urls(self) -> list[str]:
        """Pages that may list products, best first: those found to list them, the not-found probes' listing page,
        the product page's category links, the deepest first (its own category lists products; the top of the
        tree, /category/memory.html, only names its branches), the category listing_of() picks, then the home
        page's category links, the deepest first."""
        rows = (self.f.get("not_found") or {}).get("rows") or []
        paged = next((r["url"] for r in rows if r["probe"] == "a listing page"), None)
        product = (self.f.get("product") or {}).get("url") or self.deep
        mine: list[str] = []
        if self.product_answer:  # its breadcrumbs name its categories
            here = self.product_answer.url
            mine = [u for u in (self.same_site(join(here, h)) for h in HREF.findall(self.product_answer.head)) if u]

        def deepest(urls: list[str]) -> list[str]:
            under = [u for u in urls if LISTING_PATH.search(urlsplit(u).path)]
            return sorted(under, key=lambda u: -urlsplit(u).path.strip("/").count("/"))

        picked = listing_of([*self.products, *([product] if product else [])], [*self.links, *mine])
        found = [*self.listings, paged, *deepest(mine), picked, *deepest(self.links)]
        return [u for u in dict.fromkeys(found) if u and u not in (self.home, product)]

    def listing_url(self) -> str | None:
        """A listing page, the best of listing_urls()."""
        return next(iter(self.listing_urls()), None)

    async def not_found(self) -> None:
        """Pages that are not there: a made-up product shaped like the real
        one, a made-up path, and page FAR_PAGE of a listing beside its real
        page - the home page's or the product page's paging link, else one
        found on the first other link of the home page."""
        f = self.f
        if not self.best:
            f["not_found"] = {"skipped": "no client let in"}
            return
        # a made-up product from a product page: one shaped like a category page is a made-up category
        product = (f.get("product") or {}).get("url") or (self.deep if self.deep not in self.listings else None)
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
                        self.same_site(join(self.product_answer.url, h)) for h in HREF.findall(self.product_answer.head)
                    )
                    if u
                ]
            listing = listing_page(near)
            if not listing:
                # a page found to list products, else a link under a listing's word, else the first other link
                category = next(iter(self.listings), None)
                category = category or next((u for u in self.links if LISTING_PATH.search(urlsplit(u).path)), None)
                category = category or next((u for u in self.links if u not in self.products), None)
                if category:
                    a = self.listings.get(category) or await self.get(client, category)
                    self.keep(a)
                    if judge(a)[0] == "ok" and product_data(a)["kind"] == "listing":
                        self.note_listing(category, a)
                    listing = listing_page(
                        [u for u in (self.same_site(join(category, h)) for h in HREF.findall(a.head)) if u]
                    )
            if listing:
                probes += [("a listing page", listing[0]), (f"its page {settings.FAR_PAGE}", listing[1])]
            for name, url in [(n, u) for n, u in probes if self.robots.allows(u)]:
                a = await self.get(client, url)
                self.keep(a)
                if name == "a listing page" and judge(a)[0] == "ok":
                    self.note_listing(url, a)
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
                a = await fetch_within(client, url)
                answers.append(a)
                verdict = judge(a)[0]
                if verdict in LOST:
                    lost.append(a)
                if verdict in REFUSALS or (lost_max and len(lost) >= lost_max):
                    stopped.append(a)

        began = time.monotonic()
        await asyncio.gather(*(one(u) for u in urls))
        return answers, time.monotonic() - began

    def kin_on(self, a: Answer, first: str) -> list[str]:
        """The links on a page read that share the found product page's family: more products."""
        return [
            u
            for u in (self.same_site(join(a.url, h)) for h in HREF.findall(a.head))
            if u and family(u) == family(first) and u != first
        ]

    async def product_sample(self) -> None:
        """The product page found and more product links, up to --products in all: what share carries each field,
        and the traps in them. The found product's family first: the links of its kind from the pages read, then
        those a listing met on the way names. A listing is left out, and so is a page of another family that holds
        no product of its own (a maker's page) once the product page is known: more links are read in their place,
        SAMPLE_SKIPS at most, and the rest of their family is passed."""
        f = self.f
        product = f.get("product") or {}
        first = product.get("url")
        kin = [u for u in [*self.products, *self.others] if first and family(u) == family(first)]
        near = [u for a in [self.product_answer, *self.listings.values()] if a and first for u in self.kin_on(a, first)]
        urls = [u for u in dict.fromkeys([*([first] if first else []), *kin, *near, *self.products])]
        urls = [u for u in urls if u not in self.listings]
        if not self.best or not urls or self.sample_size <= 0:
            f["sample"] = {
                "skipped": "no client let in" if not self.best else "no product links" if not urls else "--products 0"
            }
            return
        records, client = [], self.make(self.best, ua=self.ua_for(self.best))
        listings: list[dict[str, str]] = []  # pages that list products: left out, and as many more read
        others: list[dict[str, str]] = []  # pages of another family with no product of their own
        passed = {family(u) for u in self.listings}  # families whose pages are left out
        queued = set(urls)
        asked = at = 0
        try:
            while at < len(urls):
                url = urls[at]
                at += 1
                left = len(listings) + len(others)
                if asked - left >= self.sample_size or asked >= self.sample_size + settings.SAMPLE_SKIPS:
                    break
                if family(url) in passed:  # its kin were listings or no products: so is it, likely
                    continue
                a = self.product_answer if url == first and self.product_answer else None
                if a is None:
                    a = await self.get(client, url)
                    self.keep(a)
                asked += 1
                self.sample_answers.append(a)
                if judge(a)[0] != "ok":
                    continue
                record = page_record(a)
                if record["kind"] == "listing":
                    self.note_listing(url, a)
                    listings.append({"url": url, "why": record["kind_why"]})
                    passed.add(family(url))
                    more = [u for u in self.kin_on(a, first) if u not in queued] if first else []
                    urls[at:at] = more  # its products, read next
                    queued.update(more)
                    continue
                if (
                    first
                    and product.get("kind") == "product"
                    and record["kind"] != "product"
                    and family(url) != family(first)
                ):
                    others.append({"url": url, "why": "no product of its own, another kind of address"})
                    passed.add(family(url))
                    continue
                records.append(record)
        finally:
            await client.aclose()
        f["sample"] = {"asked": asked, "listings": listings, "not_products": others, **sample_findings(records)}

    async def session_lock(self) -> None:
        """SESSION_PAGES pages with one cookie jar, then as many others with
        none; other pages, so the second set is not served from a cache the
        first one warmed."""
        f = self.f
        if f["robots"].get("crawl_delay"):  # several at a time is what the delay asks not to do
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
                    self.keep(await self.get(client, self.home))  # the session's cookie
                answers, wall = await self.at_once(client, urls, settings.SESSION_AT_ONCE)
            finally:
                await client.aclose()
            self.keep(*answers)
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

    async def api(self) -> None:
        """The site's own API, on every run and without a browser. The API bases the runtime config of the home
        page, the product page and a listing names, each host looked up in DNS: one with no public DNS, or a
        private address, is internal and never asked; a public one is asked once, its robots.txt, which shows
        what stands in front of it and what it allows. The routes the pages' inline scripts and own JS
        bundles name, and a helper that adds parameters to their calls. The product lists and the product the
        pages' state holds. And list or search routes asked with the plain client let in (api_probe)."""
        f = self.f
        pages = await self.api_pages()
        bases: dict[str, dict[str, Any]] = {}
        for _, a in pages:
            for base in api_bases(a.text):
                kept = bases.setdefault(base["url"], base)
                kept["keys"] = list(dict.fromkeys([*kept["keys"], *base["keys"]]))
        states = []
        for name, a in pages:
            state = read_state(a.text)
            if state and (state["lists"] or state["product"]):
                states.append({"page": name, "url": a.url, **state})
        result: dict[str, Any] = {"bases": list(bases.values())[: settings.API_BASES_MOST], "state": states}
        f["api"] = result  # what was found stays, whatever breaks below
        if not self.best:
            result["skipped"] = "no client let in"
            return
        client = self.make(self.best, ua=self.ua_for(self.best))
        try:
            for base in result["bases"]:
                await self.api_host(client, base)
            result.update(await self.bundles(client, pages))
            result["probe"] = await self.api_probe(client, result["bases"], result["routes"])
        finally:
            await client.aclose()

    async def api_pages(self) -> list[tuple[str, Answer]]:
        """The home page, the product page and a listing page as read, those answered. When no step met a page
        that lists products, LISTING_TRIES of listing_urls() are asked here until one does (page_kind); with none
        that does, the first one answered is read as "a category" page, for its scripts and state."""
        a = next(iter(self.listings.values()), None)
        name = "listing"
        if a is None and self.best:
            client = None
            try:
                for url in [u for u in self.listing_urls() if self.robots.allows(u)][: settings.LISTING_TRIES]:
                    client = client or self.make(self.best, ua=self.ua_for(self.best))
                    got = await self.get(client, url)
                    self.keep(got)
                    if judge(got)[0] != "ok":
                        continue
                    if product_data(got)["kind"] == "listing":
                        self.note_listing(url, got)
                        a, name = got, "listing"
                        break
                    if a is None:
                        a, name = got, "category"
            finally:
                if client:
                    await client.aclose()
        pages = [("home", self.home_answer), ("product", self.product_answer), (name, a)]
        return [(n, x) for n, x in pages if x is not None and judge(x)[0] == "ok"]

    async def api_host(self, client: Client, base: dict[str, Any]) -> None:
        """What an API base's host is, into `base`: the site's own; internal, never asked (no public DNS, a
        private address, a name like api.local); or public, asked once for its robots.txt: its server, its
        cookies and what stands in front of it, which can be another service than the site's. Each host once."""
        parts = urlsplit(base["url"])
        host = (parts.hostname or "").lower()
        if same_host(base["url"], self.home):
            base.update(host=host, dns="the site's")
            return
        if host in self.api_hosts:
            base.update(self.api_hosts[host])
            return
        seen = dict(await self.look_up(host))
        self.api_hosts[host] = seen
        if seen["dns"] == "public":
            a, seen["robots"] = await self.robots_of(client, base["url"])
            vendors = vendors_of([a])
            by_name = cname_vendor(seen.get("canonical"))
            if by_name:
                vendors.setdefault(by_name[0], []).append(by_name[1])
            seen["asked"] = {"url": a.url, **summary(a), "cookies": list(a.cookies)}
            seen["vendors"] = vendors
        base.update(seen)

    async def look_up(self, host: str) -> dict[str, Any]:
        """A host other than the site's in DNS, looked up once, before anything is asked of it: {host, dns,
        addresses, canonical}. dns is "internal" for a private address or a name like api.local, "none" for a
        name no public DNS holds, else "public". A host that is not public is never asked."""
        if host in self.dns_seen:
            return self.dns_seen[host]
        seen: dict[str, Any] = {"host": host}
        self.dns_seen[host] = seen
        if internal_name(host):
            seen["dns"] = "internal"
        else:
            try:
                got = await asyncio.wait_for(self.resolve(host), settings.DNS_WAIT)
            except (OSError, TimeoutError, UnicodeError, ValueError):
                got = None
            if not got or not got.get("addresses"):
                seen["dns"] = "none"
            else:
                seen["addresses"] = list(got["addresses"])[:4]
                canonical = str(got.get("canonical") or "").rstrip(".").lower()
                if canonical and canonical != host:
                    seen["canonical"] = canonical
                seen["dns"] = "internal" if all_private(seen["addresses"]) else "public"
        if seen["dns"] != "public":
            self.internal_hosts.add(host)
        return seen

    async def robots_of(self, client: Client, url: str) -> tuple[Answer, str]:
        """Another host's robots.txt, asked once and kept for what is asked of that host after: (the answer,
        "read" | "not there" | "unreadable"). One not read lets nothing more be asked of the host. Its refusal
        is that host's, not the site's."""
        parts = urlsplit(url)
        a = await self.get(client, f"{parts.scheme}://{parts.netloc}/robots.txt", own=False)
        verdict, host = judge(a)[0], (parts.hostname or "").lower()
        if a.status == 200 and verdict == "ok":
            self.host_robots[host], state = parse_robots(a.text), "read"
        elif a.status and 400 <= a.status < 500 and verdict not in REFUSALS:
            self.host_robots[host], state = Robots(), "not there"
        else:
            self.host_robots[host], state = Robots(disallow_all=True), "unreadable"
        return a, state

    async def bundles(self, client: Client, pages: list[tuple[str, Answer]]) -> dict[str, Any]:
        """The API routes the pages' inline scripts and own JS bundles name, with their methods, and the helpers
        that add parameters to their calls. Its own: on the site's host, another host of its domain, or the CDN
        its runtime config names. The bundles the pages load are read a page at a time in turn, then the chunks
        they name: BUNDLES_MOST files and BUNDLES_BYTES at most, where robots.txt allows. Another host is looked
        up in DNS first: an internal or private one is named, and nothing is asked of it."""
        routes: dict[str, dict[str, Any]] = {}
        helpers: dict[str, dict[str, Any]] = {}

        def read(js: str, where: str) -> int:
            found = routes_in(js)
            for r in found:
                if r["route"] not in routes or routes[r["route"]]["method"] == "?":
                    routes[r["route"]] = {**r, "kind": route_kind(r["route"]), "in": where}
            for h in helpers_in(js):
                if not (helpers.get(h["name"]) or {}).get("sets"):
                    helpers[h["name"]] = {**h, "in": where}
            return len(found)

        cdns: set[str] = set()
        for _, a in pages:
            cdns |= builds_of(a.text)[1]

        def ours(url: str) -> bool:
            """The site's own code: a file on its host, on another host of its domain (static.shop.com), or on
            the CDN its runtime config names. Another site's /_nuxt/ is that site's."""
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            return parts.scheme in ("http", "https") and (
                same_host(url, self.home) or same_domain(host, urlsplit(self.home).hostname or "") or host in cdns
            )

        for _, a in pages:
            for _, text in scripts_of(a.text):
                read(text, "an inline script")
        groups = [[u for u in bundle_refs(a.text, a.url) if ours(u)] for _, a in pages]
        queue = [g[i] for i in range(max(map(len, groups), default=0)) for g in groups if i < len(g)]
        seen: set[str] = set()
        files: list[dict[str, Any]] = []
        hosts: dict[str, str] = {}  # another host that serves them: what its robots.txt was
        internal: dict[str, int] = {}  # a host not public (no public DNS, a private address): its files, not asked
        total = disallowed = 0
        while queue and len(files) < settings.BUNDLES_MOST and total < settings.BUNDLES_BYTES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            host = (urlsplit(url).hostname or "").lower()
            site = same_host(url, self.home)
            if not site and (await self.look_up(host))["dns"] != "public":
                internal[host] = internal.get(host, 0) + 1
                continue
            if not site and host not in self.host_robots:
                hosts[host] = (await self.robots_of(client, url))[1]
            if not (self.robots if site else self.host_robots[host]).allows(url):
                disallowed += 1
                continue
            a = await self.get(client, url, own=site)  # a CDN's refusal is the CDN's
            if site:  # another host's answers stay out of what the site has in front
                self.keep(a)
            if judge(a)[0] != "ok":
                files.append({"url": url, "status": a.status, "verdict": judge(a)[0]})
                continue
            js = a.body[: settings.BUNDLE_BYTES].decode("utf-8", "replace")
            total += len(a.body)
            name = urlsplit(url).path.rsplit("/", 1)[-1]
            files.append({"url": url, "status": a.status, "bytes": len(a.body), "routes": read(js, name)})
            queue += [u for u in chunk_refs(js, url) if ours(u) and u not in seen]
        return {
            "bundles": {
                "read": len(files),
                "named": len(seen | set(queue)),
                "bytes": total,
                "disallowed": disallowed,
                "hosts": hosts,
                "internal": internal,
                "files": files[:40],
            },
            "routes": list(routes.values())[: settings.ROUTES_MOST],
            "helpers": list(helpers.values()),
        }

    def probe_bases(self, bases: list[dict[str, Any]]) -> list[str]:
        """The bases a route is asked on, in turn: the public API bases and those on the site's host, those of the
        site's domain first, then those a key names as the API's own (apiHost, API_URL, baseURL), then the rest
        as named (a payment service's paymentApiUrl among them); the site itself last."""
        site = urlsplit(self.home).hostname or ""
        usable = [b for b in bases if b.get("dns") in ("public", "the site's")]
        ordered = sorted(
            usable,
            key=lambda b: (not same_domain(urlsplit(b["url"]).hostname or "", site), not names_api(b["keys"])),
        )
        return list(dict.fromkeys([*(b["url"].rstrip("/") for b in ordered), self.origin]))

    def part_number(self) -> str | None:
        """The product page's part number: its JSON-LD's mpn, else the one its state holds."""
        product = self.f.get("product") or {}
        held = ((product.get("state") or {}).get("product") or {}).get("fields") or {}
        found = (product.get("jsonld") or {}).get("mpn") or held.get("mpn")
        return str(found) if found else None

    async def api_probe(
        self, client: Client, bases: list[dict[str, Any]], routes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """The list and search routes found, best first, each asked by GET with the plain client let in and no
        cookie or token: on the bases of probe_bases() in turn until one answers other than 404, then on that
        one alone. An answer whose message says what it lacks ("Either cate_id or keyword is required") is asked
        once more with a value the run has: the product page's part number as its search word, else a listing's
        category id. API_PROBES requests in all, none more once one gives a product list. Does a plain client get
        JSON from the API, whatever its Content-Type says? The best answer, and the others under "others"."""
        candidates = self.probe_bases(bases)
        asked: list[dict[str, Any]] = []
        skipped: dict[str, Any] | None = None
        filled = False

        def done() -> bool:
            return len(asked) >= settings.API_PROBES or any(x.get("kind") == "products" for x in asked)

        for pick in lists_to_ask(routes):
            if done():
                break
            got: dict[str, Any] | None = None
            for base in list(candidates):
                if done():
                    break
                one = await self.api_ask(client, base + pick["route"], pick["route"])
                if one.get("skipped"):
                    skipped = skipped or one
                    continue
                asked.append(one)
                got = one
                if one["status"] not in (None, 404):  # the API answers here: the other routes are asked here alone
                    candidates = [base]
                    break
            fill = fill_for(got["wants"], self.part_number(), list(self.listings)) if got else None
            if got and fill and not filled and not done():
                filled = True
                url = got["url"] + ("&" if urlsplit(got["url"]).query else "?") + urlencode(fill)
                one = await self.api_ask(client, url, pick["route"])
                if not one.get("skipped"):
                    asked.append({**one, "filled": fill})
        if not asked:
            return skipped or {"skipped": "no list or search route among those found"}
        best = (
            next((x for x in asked if x.get("kind") == "products"), None)
            or next((x for x in asked if x["json"] and not x["error"]), None)
            or next((x for x in asked if x["json"]), asked[0])
        )
        others = [
            {k: x.get(k) for k in ("url", "route", "status", "verdict", "json", "kind", "items", "message", "error")}
            for x in asked
            if x is not best
        ]
        return {**best, "others": others}

    async def api_ask(self, client: Client, url: str, route: str) -> dict[str, Any]:
        """One route of the API asked by GET, where its host's robots.txt allows: what came back, and when it is
        an error message, the parameters it says the call lacks. Its refusal is the API's, not the site's."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        robots = self.robots if same_host(url, self.home) else self.host_robots.get(host)
        if robots is None or host in self.internal_hosts:
            return {"url": url, "skipped": "its host was not looked at"}
        if SKIPPED_PATHS.search(f"{parts.path}?{parts.query}"):
            return {"url": url, "skipped": "it may change the site's state"}
        if not robots.allows(url):
            return {"url": url, "skipped": "robots.txt disallows it"}
        a = await self.get(client, url, headers={"Accept": "application/json, text/plain, */*"}, own=False)
        if same_host(url, self.home):  # another host's answers stay out of what the site has in front
            self.keep(a)
        body = a.body[: settings.WATCH_BODY]
        got = shape(body, a.headers.get("content-type", ""))
        self.api_answers[("GET", url)] = (a, got)
        is_json, data = as_json(body)
        kind = a.headers.get("content-type", "").split(";")[0].strip()
        message = message_of(data) if is_json else None
        error = is_json and got["kind"] not in ("products", "list") and failed(message, a.status)
        return {
            "url": url,
            "route": route,
            "method": "GET",
            "client": self.best,
            **summary(a),
            "type": kind,
            "json": is_json,
            "json_as": kind if is_json and "json" not in kind else None,
            "said": said_of(data) if is_json else None,
            "message": message,
            "error": error,  # a message that says the call failed, not data
            "wants": wanted(message) if error else [],
            **{k: got[k] for k in ("kind", "path", "items", "keys", "paging") if k in got},
        }

    async def watch(self) -> None:
        """The home page, the product page and a listing page in Chrome, on every run where patchright and Chrome
        are there (--no-watch skips it), and what each asks for on its own: the JSON and HTML fragments its scripts
        fetch, where the catalogue's own API shows. Only where a client was let in: recon watches a site that lets
        it in, it is no way past one that does not."""
        f = self.f
        if not self.watch_allowed:
            f["watch"] = {"skipped": "--no-watch"}
            return
        if not self.best:
            f["watch"] = {"skipped": "no client let in"}
            return
        product = (f.get("product") or {}).get("url") or (self.deep if self.deep not in self.listings else None)
        listing = self.listing_url()
        urls = [u for u in dict.fromkeys([self.home, product, listing]) if u and self.robots.allows(u)]
        urls = urls[: settings.WATCH_PAGES]
        if not urls:
            f["watch"] = {"skipped": "robots.txt allows none of the pages"}
            return
        try:
            seen = await self.watcher(urls)
        except BrowserMissing as e:  # not this machine's: said, and the run goes on
            f["watch"] = {"skipped": str(e)}
            return
        except Exception as e:
            f["watch"] = {"error": f"{type(e).__name__}: {e}"[:300]}
            return
        self.requests += len(seen.get("pages") or [])
        pages, found = [], []
        for page in seen.get("pages") or []:
            records = sorted(
                ((call_record(c, self.host), c) for c in page.get("calls") or []), key=lambda r: rank(r[0])
            )
            found += records
            calls = [record for record, _ in records]
            pages.append({"url": page["url"], "status": page.get("status"), "title": page.get("title"), "calls": calls})
        await self.replay(found)
        f["watch"] = {"seconds": seen.get("seconds"), "pages": pages}

    async def replay(self, found: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """The site's own product lists the pages fetched, REPLAY_MOST at most, asked once more with the plain
        client let in and no cookie or token: does the API work without the browser? Each record gets a
        "replay" saying so, or why it was not asked."""
        asked: set[tuple[str, str]] = set()  # each endpoint once, over all the pages
        made = 0  # requests made: a call not asked again does not count
        client = None
        try:
            for record, call in found:
                fragment = record["kind"] == "html" and record.get("product_links", 0) >= 3
                if not record["own"] or not (record["kind"] == "products" or fragment):
                    continue
                parts = urlsplit(call["url"])
                key = (call["method"], parts.path)
                if key in asked or made >= settings.REPLAY_MOST:
                    continue
                asked.add(key)
                done = self.api_answers.get((call["method"], call["url"]))
                if done:  # asked already, as a route the bundles name: not asked twice
                    record["replay"] = replayed(record, *done, self.best)
                    continue
                body = call.get("sent") or ""
                if call["method"] not in ("GET", "POST") or SKIPPED_PATHS.search(f"{parts.path}?{parts.query}"):
                    record["replay"] = {"skipped": "it may change the site's state"}
                    continue
                if "mutation" in body.lower():
                    record["replay"] = {"skipped": "a GraphQL mutation"}
                    continue
                host = (parts.hostname or "").lower()
                if host in self.internal_hosts:
                    record["replay"] = {"skipped": "an internal host"}
                    continue
                # an API host's own robots.txt when it was read
                robots = self.robots if same_host(call["url"], self.home) else self.host_robots.get(host, self.robots)
                if not robots.allows(call["url"]):
                    record["replay"] = {"skipped": "robots.txt disallows it"}
                    continue
                if self.best is None:
                    break
                client = client or self.make(self.best, ua=self.ua_for(self.best))
                made += 1
                data = body.encode() if call["method"] == "POST" else None
                a = await self.get(client, call["url"], headers=replay_headers(call.get("headers") or {}), data=data)
                if same_host(call["url"], self.home):
                    self.keep(a)
                got = shape(a.body[: settings.WATCH_BODY], a.headers.get("content-type", ""))
                self.api_answers[(call["method"], call["url"])] = (a, got)
                record["replay"] = replayed(record, a, got, self.best)
        finally:
            if client:
                await client.aclose()

    async def long_session(self) -> None:
        """One cookie jar, the home page and then pages robots.txt allows, one request every LONG_PAUSE s
        (or the Crawl-delay), for --long minutes or LONG_MOST requests: a service that scores clients over a
        session lets a short run in and turns a long one away. It stops at the first refusal, or at LOST_MAX
        answers lost in a row. An answer lost is checked against NEUTRAL_HOSTS first: when none of them answers
        either, this machine's link failed, not the site, and the session waits LINK_WAIT s at a time until one
        answers, within its minutes, then goes on; the report names the outage."""
        f = self.f
        if not self.best or not self.pool:
            f["long"] = {"skipped": "no client let in" if not self.best else "no pages to ask for"}
            return
        low, high = (max(s, self.crawl_delay or 0) for s in settings.LONG_PAUSE)
        client = self.make(self.best, ua=self.ua_for(self.best), cookies=True)
        urls = itertools.chain([self.home], itertools.cycle(self.pool))
        answers: list[Answer] = []
        refused: dict[str, Any] | None = None
        lost: dict[str, Any] | None = None
        outages: list[dict[str, Any]] = []  # the local link down: the site not judged
        in_a_row = 0
        began = time.monotonic()
        limit = (self.long_minutes or 0) * 60
        try:
            while time.monotonic() - began < limit and len(answers) < settings.LONG_MOST:
                if answers:
                    await asyncio.sleep(random.uniform(low, high))
                a = await self.get(client, next(urls), pause=False)
                self.keep(a)
                answers.append(a)
                verdict = judge(a)[0]
                if verdict in LOST and not await self.link_up():
                    gone = time.monotonic()
                    outage = {
                        "at": len(answers),
                        "minutes": round((gone - began) / 60, 1),
                        "url": a.url,
                        "why": judge(a)[1],
                        "back": False,
                    }
                    outages.append(outage)
                    while time.monotonic() - began < limit:
                        await asyncio.sleep(max(0.0, min(settings.LINK_WAIT, limit - (time.monotonic() - began))))
                        if await self.link_up():
                            outage["back"] = True
                            break
                    outage["waited"] = round((time.monotonic() - gone) / 60, 1)
                    in_a_row = 0
                    if not outage["back"]:  # the session's minutes ran out with the link down: nothing judged
                        break
                    continue
                in_a_row = in_a_row + 1 if verdict in LOST else 0
                if verdict in REFUSALS or in_a_row >= settings.LOST_MAX:
                    seen = {"at": len(answers), "minutes": round((time.monotonic() - began) / 60, 1), "url": a.url}
                    if verdict in REFUSALS:
                        refused = {**seen, **summary(a)}
                    else:
                        lost = {**seen, **summary(a)}
                    break
        finally:
            await client.aclose()
        f["long"] = {
            "client": self.best,
            "pause": [low, high],
            "asked": len(answers),
            "minutes": round((time.monotonic() - began) / 60, 1),
            "answers": counts(answers),
            "refused": refused,
            "lost": lost,
            "link": outages,
            "cut": bool(outages) and not outages[-1]["back"],
        }

    async def link_up(self) -> bool:
        """Whether this machine's own link works: one of NEUTRAL_HOSTS answers at all, whatever its status."""
        kind = self.best or "curl-chrome"
        client = self.make(kind, ua=self.ua_for(kind))
        try:
            for url in settings.NEUTRAL_HOSTS:
                if judge(await self.get(client, url, pause=False))[0] not in LOST:
                    return True
            return False
        finally:
            await client.aclose()

    async def shrank(self, client: Client, answers: list[Answer], floor: int, at_once: int) -> tuple[str | None, int]:
        """Whether 200s came back shrunk under load: SHRUNK_MAX or more under SHRUNK_SHARE of `floor`, and one of
        them, read alone, at least as much bigger. (What was seen, or None; the floor, lowered to the pages read
        alone that are that small anyway, so they are not read again.)"""
        small = [a for a in answers if judge(a)[0] == "ok" and len(a.body) < settings.SHRUNK_SHARE * floor]
        looked: set[str] = set()
        while len(small) >= settings.SHRUNK_MAX and len(looked) < settings.SHRUNK_MAX:
            a = next((b for b in small if b.url not in looked), None)
            if a is None:
                break
            looked.add(a.url)
            alone = await self.get(client, a.url)
            self.keep(alone)
            if judge(alone)[0] != "ok":
                continue
            if len(a.body) < settings.SHRUNK_SHARE * len(alone.body):
                return (
                    f"{len(small)} answers at {at_once} at a time were 200 but under {settings.SHRUNK_SHARE:.0%} "
                    f"of the smallest page read one at a time: {urlsplit(a.url).path} gave {len(a.body):,} bytes, "
                    f"{len(alone.body):,} read alone",
                    floor,
                )
            floor = min(floor, len(alone.body))  # a page that small is the site's own
            small = [b for b in small if len(b.body) < settings.SHRUNK_SHARE * floor]
        return None, floor

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
        stop_kind: str | None = None  # how it stopped, for comparing two reports; stop holds the numbers
        first_p50: float | None = None
        floor: int | None = None  # bytes of the smallest page of the first step, one at a time
        http: str | None = None
        urls = itertools.cycle(self.pool)
        try:
            for limit, n in settings.STEPS:
                if limit > settings.H1_MOST and http != "h2":
                    break
                answers, wall = await self.at_once(
                    client, [next(urls) for _ in range(n)], limit, lost_max=settings.LOST_MAX
                )
                self.keep(*answers)
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
                    stop_kind = f"refused: {verdict}"
                elif len(lost) >= settings.LOST_MAX:
                    stop = f"{len(lost)} connections lost at {limit} at a time ({judge(lost[0])[1]})"
                    stop_kind = "connections lost"
                elif len(failed) > settings.FAILED_SHARE * len(answers):
                    stop = f"{len(failed)} of {len(answers)} answers were server errors at {limit} at a time"
                    stop_kind = "server errors"
                elif (
                    first_p50 is not None
                    and p50 is not None
                    and p50 > max(settings.SLOW_FACTOR * first_p50, settings.SLOW_FLOOR)
                ):
                    stop = f"answers slowed to {p50:.2f}s against {first_p50:.2f}s at {limit} at a time"
                    stop_kind = "slowed"
                elif floor:
                    stop, floor = await self.shrank(client, answers, floor, limit)
                    stop_kind = "answers shrank" if stop else None
                if stop:
                    break
                first_p50 = p50 if first_p50 is None else first_p50
                if floor is None:
                    floor = min((len(a.body) for a in answers if judge(a)[0] == "ok"), default=0)
            asked = sum(s["answered"] for s in steps)
            result: dict[str, Any] = {
                "client": self.best,
                "http": http,
                "steps": steps,
                "stop": stop,
                "stop_kind": stop_kind,
                "asked": asked,
                "distinct": min(asked, len(self.pool)),
            }
            if stop:
                await asyncio.sleep(settings.RECOVER)
                a = await self.get(client, self.home, pause=False)
                self.keep(a)
                result["after"] = {"seconds": settings.RECOVER, **summary(a)}
        finally:
            await client.aclose()
        f["burst"] = result

"""A stand-in shop, its client and a stand-in browser: recon's tests touch no network.

FakeSite answers a home page with links and platform markers, robots.txt, a
sitemap index with a plain and a gzipped file, product pages with JSON-LD, and
a category listing. It can be told to put Cloudflare in front and challenge
every httpx client, refuse some User-Agents, serve one cookie's requests one at
a time, answer 429 past a number of requests, drop connections, slow down with
more at a time, speak HTTP/1.1 only, answer 200 for what is not there, wrap its
listing, or ask for a Crawl-delay.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from typing import Any

from recon import settings
from recon.clients import Answer
from recon.probe import Recon
from recon.report import report

BASE = "https://shop.test"
HOME = (
    "<html><head><title>Shop</title>"
    '<meta name="generator" content="WooCommerce 9.1">'
    "<script src='/wp-content/plugins/woocommerce/assets/cart.js'></script></head><body>"
    + "".join(f'<a href="/product/{n}/">p{n}</a>' for n in range(1, 41))
    + '<a href="/cart/">cart</a><a href="https://elsewhere.test/x">x</a><a href="/logo.png">i</a>'
    '<a href="/category/">all</a><script src="https://www.searchanise.com/widgets/v1.0/init.js"></script>'
    '<script>fetch("/api/catalog/products?limit=24")</script>'
    "</body></html>"
)
PRODUCT = (
    "<html><head><title>{name}</title>"
    '<script type="application/ld+json">{{"@context":"https://schema.org","@graph":[{{"@type":"BreadcrumbList"}},'
    '{{"@type":"Product","name":"{name}","sku":"S-{n}","mpn":"MPN-{n}","brand":{{"@type":"Brand","name":"ACME"}},'
    '"offers":{{"@type":"Offer","price":"1.50","priceCurrency":"EUR","availability":"https://schema.org/InStock",'
    '"priceSpecification":{{"valueAddedTaxIncluded":false}}}}}}]}}</script></head>'
    '<body><h1>{name}</h1><span itemprop="sku" content="S-{n}"></span>'
    "<p>Part Number: MPN-{n}</p><p>Manufacturer: ACME</p><p>1.50 EUR excl. VAT</p><p>In stock: 4{n} pcs</p>"
    "</body></html>"
)
CHALLENGE = "<html><head><title>Just a moment...</title></head></html>"


def sitemap_index() -> bytes:
    return (
        f"<sitemapindex><sitemap><loc>{BASE}/sitemap-1.xml</loc></sitemap>"
        f"<sitemap><loc>{BASE}/sitemap-2.xml.gz</loc></sitemap></sitemapindex>"
    ).encode()


def urlset(numbers: Any) -> bytes:
    urls = "".join(f"<url><loc>{BASE}/product/{n}/</loc><lastmod>2026-10-0{n % 9 + 1}</lastmod></url>" for n in numbers)
    return f"<urlset>{urls}</urlset>".encode()


def page(body: str, **headers: str) -> Answer:
    """A 200 holding `body`."""
    return Answer("u", 200, headers, (), body.encode())


def ld(mpn: str, sku: str, extra: str = "") -> str:
    """A product page body: JSON-LD with `mpn` and `sku`, then `extra`."""
    data = {"@type": "Product", "mpn": mpn, "sku": sku, "offers": {"price": "1", "priceCurrency": "USD"}}
    return f'<script type="application/ld+json">{json.dumps(data)}</script>{extra}'


class FakeSite:
    def __init__(
        self,
        guard=None,
        refuse_uas=(),
        lock=False,
        limit=None,
        drop_after=None,
        slow=False,
        http="h2",
        disallow=None,
        sitemap_at=None,
        soft404=False,
        wrap=False,
        crawl_delay=None,
        rate=False,
        robots_status=200,
        robots_moved=False,
        home_extra="",
        home_captcha=False,
    ):
        self.guard, self.refuse_uas, self.lock, self.limit = guard, refuse_uas, lock, limit
        self.drop_after, self.slow, self.http, self.disallow = drop_after, slow, http, disallow
        self.sitemap_at = sitemap_at  # robots.txt names no sitemap, and it is here
        self.soft404, self.wrap = soft404, wrap  # 200 for what is not there; listing pages past the end as page 1
        self.crawl_delay, self.rate = crawl_delay, rate
        self.robots_status, self.robots_moved = robots_status, robots_moved  # robots.txt failing, or redirected
        self.home_extra = home_extra  # more HTML at the end of the home page
        self.home_captcha = home_captcha  # the home page redirects to a captcha page
        self.asked: list[tuple[str, str | None, str]] = []  # (client kind, ua, path)
        self.in_flight = 0
        self.session = asyncio.Lock() if lock else None

    def answer(self, client: FakeClient, url: str, headers: dict) -> Answer:
        path, _, query = (url.removeprefix(BASE) or "/").partition("?")
        h = {"server": "cloudflare", "cf-ray": "8f-WAW"} if self.guard else {"server": "nginx"}
        ua = client.ua if client.ua is not None else settings.CHROME_UA
        if self.guard == "cloudflare-tls" and client.kind.startswith("httpx") and path != "/robots.txt":
            return Answer(url, 403, {**h, "cf-mitigated": "challenge"}, (), CHALLENGE.encode(), 0.01, http=self.http)
        if any(name in ua for name in self.refuse_uas):
            return Answer(url, 403, h, (), b"<title>Forbidden</title>", 0.01, http=self.http)
        if path == "/" and self.home_captcha:
            return Answer(url, 302, {**h, "location": "/captcha/?from=/"}, (), b"", 0.01, http=self.http)
        if path == "/captcha/":
            return Answer(url, 200, h, (), b"<html><title>Are you a robot?</title></html>", 0.01, http=self.http)
        if path == "/robots.txt" and self.robots_moved:
            return Answer(url, 301, {**h, "location": f"{BASE}/real-robots.txt"}, (), b"", 0.01, http=self.http)
        if path == "/robots.txt" and self.robots_status != 200:
            return Answer(url, self.robots_status, h, (), b"<title>Service unavailable</title>", 0.01, http=self.http)
        if path in ("/robots.txt", "/real-robots.txt"):
            body = f"User-agent: *\nDisallow: {self.disallow or ''}\n"
            body += f"Crawl-delay: {self.crawl_delay}\n" if self.crawl_delay else ""
            body += "" if self.sitemap_at else f"Sitemap: {BASE}/sitemap.xml\n"
            return Answer(url, 200, h, (), body.encode(), 0.01, http=self.http)
        if path == (self.sitemap_at or "/sitemap.xml"):
            return Answer(url, 200, h, (), sitemap_index(), 0.01, http=self.http)
        if path == "/sitemap-1.xml":
            return Answer(url, 200, h, (), urlset(range(1, 21)), 0.01, http=self.http)
        if path == "/sitemap-2.xml.gz":
            return Answer(url, 200, h, (), gzip.compress(urlset(range(21, 41))), 0.01, http=self.http)
        if path == "/":
            body = HOME.replace("</body>", self.home_extra + "</body>")
            return Answer(url, 200, h, ("sid",), body.encode(), 0.01, http=self.http)
        number = path.strip("/").split("/")[-1]
        if path.startswith("/product/") and number.isdigit() and 1 <= int(number) <= 40:
            headers = {**h, "x-ratelimit-remaining": "99"} if self.rate else h
            body = PRODUCT.format(name=f"Part {number}", n=number)
            return Answer(url, 200, headers, ("sid",), body.encode(), 0.01, http=self.http)
        if path == "/category/":
            at = int(query.split("=")[1]) if query.startswith("page=") else 1
            if at <= 3 or self.wrap:
                links = "".join(f'<a href="/product/{n}/">p</a>' for n in range(1, 11))
                body = f'<html><title>All</title>{links}<a href="/category/?page=2">2</a></html>'
                return Answer(url, 200, h, (), body.encode(), 0.01, http=self.http)
        if path.startswith("/wp-json/wc/store"):
            first = b'[{"id":1,"sku":"S-1"}]'
            return Answer(url, 200, {**h, "x-wp-total": "40"}, (), first, 0.01, http=self.http)
        if self.soft404:
            return Answer(url, 200, h, (), b"<html><title>Shop</title>Nothing here</html>", 0.01, http=self.http)
        return Answer(url, 404, h, (), b"", 0.01, http=self.http)


class FakeClient:
    """recon's client interface over a FakeSite, with its pace, lock, limit and drops."""

    def __init__(self, site: FakeSite, kind: str, ua: str | None, cookies: bool):
        self.site, self.kind, self.ua, self.cookies = site, kind, ua, cookies
        self.jar = False
        self.pages = 0  # product pages asked through this client: the burst's is the only long run

    async def fetch(self, url: str, headers: dict | None = None, data: bytes | None = None) -> Answer:
        site = self.site
        site.asked.append((self.kind, self.ua, url.removeprefix(BASE)))
        began = asyncio.get_running_loop().time()
        if site.session and self.jar:  # one session's requests one at a time
            async with site.session:
                await asyncio.sleep(0.05)
        site.in_flight += 1
        try:
            await asyncio.sleep(0.01 * site.in_flight**2 if site.slow else 0.02)
        finally:
            site.in_flight -= 1
        if url.removeprefix(BASE).startswith("/product/"):
            self.pages += 1
            if site.limit is not None and self.pages > site.limit:
                return Answer(url, 429, {"retry-after": "60"}, (), b"", 0.01, http=site.http)
            if site.drop_after is not None and self.pages > site.drop_after:
                return Answer(url, error="RemoteProtocolError: Server disconnected without sending a response.")
        a = site.answer(self, url, headers or {})
        a.seconds = asyncio.get_running_loop().time() - began
        if self.cookies and a.cookies:
            self.jar = True
        return a

    async def aclose(self) -> None:
        pass


class FakeBrowser:
    """open_in_browser as Chrome would answer: let in, given cf_clearance; or not there."""

    def __init__(self, fail: bool = False):
        self.fail, self.urls = fail, []

    async def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if self.fail:
            raise RuntimeError("Chrome is not installed")
        return {
            "ua": "Mozilla/5.0 Chrome/155.0.0.0",
            "status": 200,
            "challenged": False,
            "title": "Shop",
            "passed": True,
            "cookies": ["cf_clearance", "sid"],
            "cf_clearance": "abc",
            "seconds": 1.1,
        }


def scan(site: FakeSite, browser: FakeBrowser | None = None, **kw: Any) -> tuple[dict, str, FakeBrowser]:
    """(findings, the report, the browser) of a whole run of recon against `site`."""
    browser = browser or FakeBrowser()

    def make(kind: str, ua: str | None = None, cookies: bool = False) -> FakeClient:
        return FakeClient(site, kind, ua, cookies)

    kw.setdefault("pause", 0)
    findings = asyncio.run(Recon(BASE, make=make, browse=browser, **kw).run())
    return findings, report(findings), browser

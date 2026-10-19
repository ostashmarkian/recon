"""A stand-in shop, its client and a stand-in browser: recon's tests touch no network.

FakeSite answers a home page with links and platform markers, robots.txt, a
sitemap index with a plain and a gzipped file, product pages with JSON-LD, and
a category listing. It can be told to put Cloudflare in front and challenge
every httpx client, refuse some User-Agents, serve one cookie's requests one at
a time, answer 429 past a number of requests, drop connections, slow down with
more at a time, speak HTTP/1.1 only, answer 200 for what is not there, wrap its
listing, ask for a Crawl-delay, put Myra in front, answer 200 with a PHP
warning in place of its product pages when too many are asked at once, give
some clients no answer, refuse its sitemap, redirect its home page away, or
block a client late in a long session.
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
# what an OpenCart shop served with status 200 once its database connections were spent
PHP_WARNING = (
    b"<b>Warning</b>: mysqli::mysqli(): (HY000/1226): User 'shop' has exceeded the 'max_user_connections'"
    b" resource (current value: 30)"
)


LISTED = json.dumps(
    {
        "products": [{"id": n, "sku": f"S-{n}", "name": f"Part {n}", "price": "1.50", "stock": 4} for n in range(24)],
        "total": 40,
        "page": 1,
    }
).encode()
FRAGMENT = "".join(f'<a href="/product/{n}/">p</a>' for n in range(10)).encode()


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
        shrink_over=None,
        silent_for=(),
        sitemap_refused=False,
        home_moved=False,
        block_after=None,
        nested=0,
    ):
        self.guard, self.refuse_uas, self.lock, self.limit = guard, refuse_uas, lock, limit
        self.drop_after, self.slow, self.http, self.disallow = drop_after, slow, http, disallow
        self.sitemap_at = sitemap_at  # robots.txt names no sitemap, and it is here
        self.soft404, self.wrap = soft404, wrap  # 200 for what is not there; listing pages past the end as page 1
        self.crawl_delay, self.rate = crawl_delay, rate
        self.robots_status, self.robots_moved = robots_status, robots_moved  # robots.txt failing, or redirected
        self.home_extra = home_extra  # more HTML at the end of the home page
        self.home_captcha = home_captcha  # the home page redirects to a captcha page
        self.shrink_over = shrink_over  # more product pages at once than this: a 200 with a PHP warning
        self.silent_for = silent_for  # client kinds that get no answer in time, on any page
        self.sitemap_refused = sitemap_refused  # the sitemap robots.txt names answers 403, as S3 does
        self.home_moved = home_moved  # the home page redirects to another site
        self.block_after = block_after  # product pages one client may ask before Akamai blocks it
        self.nested = nested  # the sitemap an index of this many indexes, each of the two files
        self.asked: list[tuple[str, str | None, str]] = []  # (client kind, ua, path)
        self.in_flight = 0
        self.most_in_flight = 0  # the most requests out at once
        self.posts: list[str] = []  # paths asked with a body
        self.sent: list[tuple[str, str, dict | None]] = []  # (client kind, path, the headers asked with)
        self.session = asyncio.Lock() if lock else None

    def answer(self, client: FakeClient, url: str, headers: dict) -> Answer:
        path, _, query = (url.removeprefix(BASE) or "/").partition("?")
        if self.guard == "myra":
            h = {"server": "myracloud"}
        else:
            h = {"server": "cloudflare", "cf-ray": "8f-WAW"} if self.guard else {"server": "nginx"}
        ua = client.ua if client.ua is not None else settings.CHROME_UA
        if self.guard == "cloudflare-tls" and client.kind.startswith("httpx") and path != "/robots.txt":
            return Answer(url, 403, {**h, "cf-mitigated": "challenge"}, (), CHALLENGE.encode(), 0.01, http=self.http)
        if any(name in ua for name in self.refuse_uas):
            return Answer(url, 403, h, (), b"<title>Forbidden</title>", 0.01, http=self.http)
        if path == "/" and self.home_captcha:
            return Answer(url, 302, {**h, "location": "/captcha/?from=/"}, (), b"", 0.01, http=self.http)
        if path == "/" and self.home_moved:
            return Answer(url, 301, {**h, "location": "https://moved.test/"}, (), b"", 0.01, http=self.http)
        if path == "/api/catalog/products":  # the list the pages fetch, open to any client
            return Answer(url, 200, {**h, "content-type": "application/json"}, (), LISTED, 0.01, http=self.http)
        if path == "/api/short/products":  # a stranger gets 3 of the 24 a visitor gets
            few = json.dumps({"products": json.loads(LISTED)["products"][:3]}).encode()
            return Answer(url, 200, {**h, "content-type": "application/json"}, (), few, 0.01, http=self.http)
        if path == "/api/private/products":  # the same, only with a key the page holds
            return Answer(url, 401, h, (), b'{"error": "no key"}', 0.01, http=self.http)
        if path == "/ajax/listing":
            return Answer(url, 200, {**h, "content-type": "text/html"}, (), FRAGMENT, 0.01, http=self.http)
        if path.startswith("/products/highlights/"):  # a shop's marketing pages under /products/
            body = b"<html><title>Our ranges</title><p>Capacitors for every need</p></html>"
            return Answer(url, 200, h, (), body, 0.01, http=self.http)
        if path.startswith("/p/") and path.strip("/").split("/")[-1].isdigit():  # a short address of a product
            moved = f"/product/{path.strip('/').split('/')[-1]}/"
            return Answer(url, 301, {**h, "location": moved}, (), b"", 0.01, http=self.http)
        if path == "/bad-request/":
            return Answer(url, 400, h, (), b"<title>Bad Request</title>", 0.01, http=self.http)
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
        if path == "/sitemap.xml" and self.sitemap_refused:
            return Answer(url, 403, h, (), b"<title>Forbidden</title>", 0.01, http=self.http)
        if path == "/sitemap.xml" and self.nested:
            listed = "".join(f"<sitemap><loc>{BASE}/sitemap-idx-{k}.xml</loc></sitemap>" for k in range(self.nested))
            return Answer(url, 200, h, (), f"<sitemapindex>{listed}</sitemapindex>".encode(), 0.01, http=self.http)
        if path.startswith("/sitemap-idx-"):
            return Answer(url, 200, h, (), sitemap_index(), 0.01, http=self.http)
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
        site.sent.append((self.kind, url.removeprefix(BASE), headers))
        if self.kind in site.silent_for:
            return Answer(url, error="TimeoutError: no answer within 90 s", seconds=90)
        began = asyncio.get_running_loop().time()
        if site.session and self.jar:  # one session's requests one at a time
            async with site.session:
                await asyncio.sleep(0.05)
        site.in_flight += 1
        crowd = site.in_flight
        site.most_in_flight = max(site.most_in_flight, site.in_flight)
        if data is not None:
            site.posts.append(url.removeprefix(BASE))
        try:
            await asyncio.sleep(0.01 * site.in_flight**2 if site.slow else 0.02)
        finally:
            site.in_flight -= 1
        if url.removeprefix(BASE).startswith("/product/"):
            self.pages += 1
            if site.limit is not None and self.pages > site.limit:
                return Answer(url, 429, {"retry-after": "60"}, (), b"", 0.01, http=site.http)
            if site.block_after is not None and self.pages > site.block_after:
                return Answer(url, 403, {"server": "AkamaiGHost"}, (), b"Access Denied", 0.01, http=site.http)
            if site.drop_after is not None and self.pages > site.drop_after:
                return Answer(url, error="RemoteProtocolError: Server disconnected without sending a response.")
            if site.shrink_over is not None and crowd > site.shrink_over:
                return Answer(url, 200, {"server": "nginx"}, (), PHP_WARNING, 0.01, http=site.http)
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


class FakeWatcher:
    """watch_in_browser as Chrome would answer: every page fetches a product list from the shop's own API,
    a search service's query and an HTML fragment of product links; or Chrome is not there."""

    def __init__(self, fail: bool = False, extra: tuple[dict, ...] = ()):
        self.fail, self.urls, self.extra = fail, [], extra

    async def __call__(self, urls: list[str]) -> dict:
        self.urls.extend(urls)
        if self.fail:
            raise RuntimeError("Chrome is not installed")
        listed, fragment = LISTED, FRAGMENT
        browser = {"accept": "application/json", "sec-fetch-mode": "cors", "user-agent": "Chrome"}
        calls = [
            {
                "method": "GET",
                "url": f"{BASE}/ajax/listing?page=2",
                "status": 200,
                "type": "text/html",
                "sent": "",
                "headers": {**browser, "x-requested-with": "XMLHttpRequest"},
                "body": fragment,
            },
            {
                "method": "POST",
                "url": "https://abc-dsn.algolia.net/1/indexes/*/queries",
                "status": 200,
                "type": "application/json; charset=UTF-8",
                "sent": '{"requests": []}',
                "body": b'{"results": [{"hits": [], "nbHits": 0}]}',
            },
            {
                "method": "GET",
                "url": f"{BASE}/api/catalog/products?limit=24",
                "status": 200,
                "type": "application/json",
                "sent": "",
                "body": listed,
            },
        ]
        calls += [
            {
                "method": "GET",
                "url": f"{BASE}/api/private/products?limit=24",
                "status": 200,
                "type": "application/json",
                "sent": "",
                "headers": {**browser, "x-api-key": "secret-key-123", "cookie": "sid=abc123; basket=7"},
                "body": listed,
            },
            *self.extra,
        ]
        for call in calls:
            call.setdefault("headers", browser)
        pages = [{"url": u, "status": 200, "title": "Shop", "calls": [dict(c) for c in calls]} for u in urls]
        return {"ua": "Chrome", "seconds": 3.2, "pages": pages}


def scan(site: FakeSite, browser: FakeBrowser | None = None, **kw: Any) -> tuple[dict, str, FakeBrowser]:
    """(findings, the report, the browser) of a whole run of recon against `site`."""
    browser = browser or FakeBrowser()

    def make(kind: str, ua: str | None = None, cookies: bool = False) -> FakeClient:
        return FakeClient(site, kind, ua, cookies)

    kw.setdefault("pause", 0)
    findings = asyncio.run(Recon(BASE, make=make, browse=browser, **kw).run())
    return findings, report(findings), browser

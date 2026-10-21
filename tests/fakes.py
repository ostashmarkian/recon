"""A stand-in shop, its client and a stand-in browser: recon's tests touch no network.

FakeSite answers a home page with links and platform markers, robots.txt, a
sitemap index with a plain and a gzipped file, product pages with JSON-LD, and
a category listing. It can be told to put Cloudflare in front and challenge
every httpx client, refuse some User-Agents, serve one cookie's requests one at
a time, answer 429 past a number of requests, drop connections, slow down with
more at a time, speak HTTP/1.1 only, answer 200 for what is not there, wrap its
listing, ask for a Crawl-delay, put Myra in front, answer 200 with a PHP
warning in place of its product pages when too many are asked at once, give
some clients no answer, refuse its sitemap, redirect its home page away,
block a client late in a long session, lose this machine's link for a while
(the neutral hosts silent too), or keep its sitemap behind a redirect into a
folder of its own.

NuxtSite is a Nuxt 3 shop of electronic parts: product pages under /products/
outnumbered by category listings with a JSON-LD ItemList, the top of its
category tree with a few featured products, the runtime config naming a public
API host behind Alibaba Cloud and an internal one, JS bundles naming the API
routes, a search that asks for a category or a search word, and __NUXT_DATA__
holding the listings' products. It can serve its bundles from a CDN, link a
tree of categories first, want a token for its search, or carry more scripts.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
from typing import Any
from urllib.parse import parse_qs

from recon import settings
from recon.browser import BrowserMissing
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
        link_down=None,
        sitemap_moved=False,
        dns=None,
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
        # (n, k): at the n-th request of a client with a cookie jar, this machine's link goes down for k requests
        self.link_down, self.down = link_down, 0
        # robots.txt names no sitemap; /sitemap-index.xml redirects into /maps/, to a file not there, and the index
        # is /maps/sitemap-index.xml
        self.sitemap_moved = sitemap_moved
        self.dns = dns or {}  # host: what its DNS answers; any other host has none
        self.resolved: list[str] = []
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
            body += "" if self.sitemap_at or self.sitemap_moved else f"Sitemap: {BASE}/sitemap.xml\n"
            return Answer(url, 200, h, (), body.encode(), 0.01, http=self.http)
        if self.sitemap_moved and path == "/sitemap-index.xml":
            return Answer(url, 301, {**h, "location": "/maps/sitemap-prod-index.xml"}, (), b"", 0.01, http=self.http)
        if self.sitemap_moved and path == "/maps/sitemap-index.xml":
            return Answer(url, 200, h, (), sitemap_index(), 0.01, http=self.http)
        if self.sitemap_moved and path in ("/sitemap.xml", "/maps/sitemap-prod-index.xml"):
            return Answer(url, 404, h, (), b"", 0.01, http=self.http)
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

    async def resolve(self, host: str) -> dict:
        """The DNS: the hosts of `dns`; any other has no public name."""
        self.resolved.append(host)
        if host in self.dns:
            return self.dns[host]
        raise OSError(f"[Errno 11001] getaddrinfo failed: {host}")


class FakeClient:
    """recon's client interface over a FakeSite, with its pace, lock, limit and drops."""

    def __init__(self, site: FakeSite, kind: str, ua: str | None, cookies: bool):
        self.site, self.kind, self.ua, self.cookies = site, kind, ua, cookies
        self.jar = False
        self.pages = 0  # product pages asked through this client: the burst's is the only long run
        self.n = 0  # requests made through this client

    async def fetch(self, url: str, headers: dict | None = None, data: bytes | None = None) -> Answer:
        site = self.site
        site.asked.append((self.kind, self.ua, url.removeprefix(BASE)))
        site.sent.append((self.kind, url.removeprefix(BASE), headers))
        self.n += 1
        if site.link_down and self.cookies and self.n == site.link_down[0]:
            site.down = site.link_down[1]
        if site.down > 0:  # this machine's link is down: no host answers
            site.down -= 1
            return Answer(url, error="ReadError: ")
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
    a search service's query and an HTML fragment of product links; or Chrome fails, or is not there."""

    def __init__(self, fail: bool = False, extra: tuple[dict, ...] = (), missing: bool = False):
        self.fail, self.urls, self.extra, self.missing = fail, [], extra, missing

    async def __call__(self, urls: list[str]) -> dict:
        self.urls.extend(urls)
        if self.missing:
            raise BrowserMissing("Google Chrome is not installed")
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
    kw.setdefault("watcher", FakeWatcher(missing=True))  # the watch is on by default: here no Chrome is there
    kw.setdefault("resolve", site.resolve)  # no DNS asked
    findings = asyncio.run(Recon(BASE, make=make, browse=browser, **kw).run())
    return findings, report(findings), browser


# ---------------------------------------------------------------- a Nuxt 3 shop, its API on another host
API = "https://api.shop.test"
INTERNAL = "http://api-noauth.backend.test"  # the servers' own API host: no public DNS
API_DNS = {
    "api.shop.test": {"addresses": ["47.246.1.1"], "canonical": "api.shop.test.w.kunlungr.com"},
    "static.shop.test": {"addresses": ["47.246.2.2"]},
}


class Wrap:
    """A value devalue writes wrapped: ["ShallowReactive", i], ["Ref", i]."""

    def __init__(self, tag: str, value: Any):
        self.tag, self.value = tag, value


def devalue(value: Any) -> str:
    """`value` as Nuxt 3 writes it into __NUXT_DATA__: one flat array, each value an index into it."""
    out: list[Any] = []

    def add(v: Any) -> int:
        i = len(out)
        out.append(None)
        if isinstance(v, Wrap):
            out[i] = [v.tag, add(v.value)]
        elif isinstance(v, (set, frozenset)):
            out[i] = ["Set", *[add(x) for x in sorted(v)]]
        elif isinstance(v, dict):
            out[i] = {k: add(x) for k, x in v.items()}
        elif isinstance(v, list):
            out[i] = [add(x) for x in v]
        else:
            out[i] = v
        return i

    add(value)
    return json.dumps(out)


def nuxt_item(n: int) -> dict:
    """One product as the shop's state and API hold it: pro_sno is the maker's part number."""
    return {
        "spu_id": 23120130 + n,
        "pro_sno": f"MPN-{n}",
        "std_pro_sno": f"MPN{n}",
        "goods_name": f"ACME MPN-{n}",
        "brand_name": "ACME",
        "price": "0.50",
        "stock_num": 100 + n,
    }


def nuxt_product_path(n: int) -> str:
    return f"/products/usb-accessories/mpn-{n}/{23120130 + n}.html"


NUXT_CONFIG = (
    '<script>window.__NUXT__={};window.__NUXT__.config={public:{apiHost:"https://api.shop.test",'
    'serverApiHost:"http://api-noauth.backend.test",API_HOST:"https://api.shop.test",'
    'SERVER_API_HOST:"http://api-noauth.backend.test"},app:{baseURL:"/",buildId:"b1",buildAssetsDir:"/_nuxt/",'
    'cdnURL:""}}</script>'
)


CDN = "https://static.shop.test"  # where NuxtSite(cdn=True) serves its bundles, as Nuxt's cdnURL does


def nuxt_page(
    title: str, body: str, data: dict, ld: Any = None, path: str = "/", assets: str = "", extra: str = ""
) -> str:
    """A page as Nuxt 3 draws it on the server: its bundles, its JSON-LD, its state and its runtime config;
    `extra` at the end of its head."""
    state = Wrap(
        "ShallowReactive",
        {
            "data": Wrap("ShallowReactive", data),
            "state": Wrap("Reactive", {}),
            "once": set(),
            "_errors": Wrap("ShallowReactive", {}),
            "serverRendered": True,
            "path": path,
        },
    )
    script = f'<script type="application/ld+json">{json.dumps(ld)}</script>' if ld else ""
    return (
        f"<!DOCTYPE html><html><head><title>{title}</title>"
        f'<link rel="modulepreload" as="script" crossorigin href="{assets}/_nuxt/Bx1api.js">'
        f'<script type="module" src="{assets}/_nuxt/entry.Cq2k.js" crossorigin></script>'
        f'{script}{extra}</head><body><div id="__nuxt">{body}</div>'
        '<script type="application/json" data-nuxt-data="nuxt-app" data-ssr="true" id="__NUXT_DATA__">'
        f"{devalue(state)}</script>{NUXT_CONFIG}</body></html>"
    )


BUNDLES = {
    "entry.Cq2k.js": (
        'const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["_nuxt/Dk3list.js"])))=>i.map(i=>d[i]);'
        'const r=e=>fetch(e.url,e);export{r};import("./Ab4detail.js");'
    ),
    "Bx1api.js": (
        'import{r as request}from"./entry.Cq2k.js";'
        'const getCateSearch=e=>request({url:"/www-api/search/cate-search/get-search-result-v2",method:"get",'
        "params:addAntiSpiderParams(e)});"
        'const getSpuDetail=e=>request({url:"/www-api/goods/spu-detail",method:"get",params:e});'
        'const getStock=e=>request({method:"post",url:"/www-api/goods/stock-info",data:e});'
        'const addCart=e=>request({url:"/www-api/cart/add",method:"post",data:e});'
        'const getNav=()=>request({url:"/catalog-api/nav-cate/get-cate-list",method:"get"});'
        'const menu=[{name:"About",url:"/about/us"}];'
        "function addAntiSpiderParams(t){const e=Date.now();return t.v=e,t.v_=Math.random(),t.p=e%7,t}"
    ),
    "Dk3list.js": 'const hot=t=>t.get("/www-api/search/hot-words");',
    "Ab4detail.js": 'const icons=()=>$fetch("/api/_nuxt_icon/icons.json");',
}


class NuxtSite(FakeSite):
    """A Nuxt 3 shop behind Cloudflare, its data on an open JSON API on another host, served as text/html."""

    def __init__(
        self, cdn: bool = False, tree: bool = False, token: bool = False, exact: bool = False, head: str = "", **kw: Any
    ):
        kw.setdefault("guard", "cloudflare-open")
        kw.setdefault("dns", API_DNS)
        super().__init__(**kw)
        self.assets = CDN if cdn else ""  # bundles on a CDN host of their own
        self.tree = tree  # the home page links /category first: a tree of categories, no listing
        self.token = token  # the API's search asks for a token recon has not: an error message whatever is sent
        self.exact = exact  # the search finds a part number's one product, not a page of them
        self.head = head  # more HTML in every page's <head>: scripts on other hosts

    def answer(self, client: FakeClient, url: str, headers: dict) -> Answer:
        h = {"server": "cloudflare", "cf-ray": "8f-WAW", "content-type": "text/html"}
        if url.startswith(API):
            return self.api_answer(url)
        if url.startswith(CDN):  # a static host: no robots.txt, the bundles under /_nuxt/
            name = url.removeprefix(f"{CDN}/_nuxt/")
            if name in BUNDLES:
                return Answer(url, 200, {"content-type": "application/javascript"}, (), BUNDLES[name].encode(), 0.01)
            return Answer(url, 404, {}, (), b"", 0.01)
        path, _, query = (url.removeprefix(BASE) or "/").partition("?")
        at = int(query.split("=")[1]) if query.startswith("page=") else 1
        if path == "/":
            links = '<a href="/category">all</a>' if self.tree else ""
            links += "".join(f'<a href="/category/cat-{k}/0704{k:02d}.html">c</a>' for k in range(30))
            links += "".join(f'<a href="{nuxt_product_path(n)}">p</a>' for n in range(8))
            links += "".join(f'<a href="/brands/acme-{k}/12345{k}.html">b</a>' for k in range(3))
            links += "".join(f'<a href="/manufacturers/maker-{k}/1691{k}.html">m</a>' for k in range(2))
            return Answer(url, 200, h, ("__cf_bm",), self.page("Shop", links, {}).encode(), 0.01)
        if path == "/category" and self.tree:
            body = "".join(f'<a href="/category/cat-{k}/0704{k:02d}.html">c</a>' for k in range(3))
            return Answer(
                url, 200, h, (), self.page("All categories", body, {"category-list": [{"cate_id": 1}]}).encode(), 0.01
            )
        if path == "/category/usb.html":  # the top of the tree: its branches and a few featured products
            data = {"first-cate-usb": {"featuredProducts": [nuxt_item(k) for k in range(8)]}}
            body = '<a href="/category/usb-accessories/070403.html">c</a>'
            return Answer(url, 200, h, (), self.page("USB", body, data, None, path).encode(), 0.01)
        if re.fullmatch(r"/manufacturers/maker-\d/1691\d\.html", path):  # a maker's page: words, no product
            body = "<h1>ACME</h1><p>Manufacturer Part Number search for ACME parts. In stock: many lines.</p>"
            return Answer(
                url, 200, h, (), self.page("ACME", body, {"maker": {"name": "ACME"}}, None, path).encode(), 0.01
            )
        if path == "/robots.txt":
            return Answer(url, 200, h, (), f"User-agent: *\nDisallow: {self.disallow or '/search'}\n".encode(), 0.01)
        if path == "/sitemap-index.xml":  # moved into a folder of its own, to a file that is not there
            return Answer(url, 301, {**h, "location": "/nuxt-sitemaps/sitemap-prod-index.xml"}, (), b"", 0.01)
        if path == "/nuxt-sitemaps/sitemap-index.xml":  # its static pages only
            pages = "".join(f"<url><loc>{BASE}/{p}/</loc></url>" for p in ("about", "contact", "faq"))
            return Answer(url, 200, h, (), f"<urlset>{pages}</urlset>".encode(), 0.01)
        if path.startswith("/_nuxt/") and path[7:] in BUNDLES:
            js = {**h, "content-type": "application/javascript"}
            return Answer(url, 200, js, (), BUNDLES[path[7:]].encode(), 0.01)
        product = re.fullmatch(r"/products/usb-accessories/mpn-(\d+)/(\d+)\.html", path)
        if product and int(product.group(1)) < 20 and int(product.group(2)) == 23120130 + int(product.group(1)):
            return Answer(url, 200, h, ("__cf_bm",), self.product_page(int(product.group(1))).encode(), 0.01)
        listing = re.fullmatch(r"/(?:category|brands)/[a-z0-9-]+/\d{6}\.html", path)
        if listing and at <= 20:
            return Answer(url, 200, h, (), self.listing_page(path, at).encode(), 0.01)
        return Answer(url, 404, h, (), b"<title>Page not found</title>", 0.01)

    def product_page(self, n: int) -> str:
        """Its JSON-LD carries the part number on even pages only; its state always does."""
        ld = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": f"MPN-{n}",
            "sku": str(23120130 + n),
            **({"mpn": f"MPN-{n}"} if n % 2 == 0 else {}),
            "brand": {"@type": "Brand", "name": "ACME"},
            "offers": {"@type": "Offer", "price": "1.32", "priceCurrency": "USD"},
        }
        data = {
            f"spu-detail-{23120130 + n}": {
                "goodsDetail": nuxt_item(n),
                "relatedList": [nuxt_item(k) for k in (1, 2, 3)],
            }
        }
        body = (
            '<a href="/category/usb.html">USB</a><a href="/category/usb-accessories/070403.html">Accessories</a>'
            f"<h1>MPN-{n}</h1>"
            f"<p>Manufacturer Part : MPN-{n}</p><p>In Stock 3,56{n}</p>"
        )
        return self.page(f"MPN-{n}", body, data, ld, nuxt_product_path(n))

    def page(self, title: str, body: str, data: dict, ld: Any = None, path: str = "/") -> str:
        return nuxt_page(title, body, data, ld, path, self.assets, self.head)

    def listing_page(self, path: str, at: int) -> str:
        """A category: a JSON-LD ItemList of 10 Products (a name and the shop's sku, no part number) and its 25
        products in the state, with the counts beside them."""
        ld = {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": k + 1,
                    "item": {
                        "@type": "Product",
                        "name": f"ACME MPN-{k}",
                        "sku": f"1003001{k:09d}",
                        "offers": {"@type": "Offer", "price": "0.77", "priceCurrency": "USD"},
                    },
                }
                for k in range(10)
            ],
        }
        data = {
            f"third-cate-{path}": {"pageOfItems": [nuxt_item(k) for k in range(25)], "resultTotal": 413, "pageSize": 25}
        }
        links = "".join(f'<a href="{nuxt_product_path(n)}">p</a>' for n in range(10, 20))
        body = f'<table><tr><th>Mfr. Part #</th></tr></table>{links}<a href="{path}?page={at + 1}">next</a>'
        title = f"Page {at} of USB Accessories" if at > 1 else "USB Accessories"
        return self.page(title, body, data, ld, path)

    def api_answer(self, url: str) -> Answer:
        """The API host: Alibaba Cloud in front, JSON served as text/html. Its search asks for a category or a
        search word, in a message with a 200."""
        h = {"server": "Tengine", "content-type": "text/html; charset=UTF-8"}
        path = url.removeprefix(API).partition("?")[0]
        if path == "/robots.txt":
            return Answer(
                url,
                200,
                {**h, "content-type": "text/plain"},
                ("acw_tc", "cdn_sec_tc"),
                b"User-agent: *\nDisallow: /private/\n",
                0.01,
            )
        if path == "/www-api/search/cate-search/get-search-result-v2":
            asked = parse_qs(url.partition("?")[2])
            if self.token or not (asked.get("keyword") or asked.get("cate_id")):  # as the shop's: 200, a message
                said = "token is required" if self.token else "Either cate_id or keyword is required."
                return Answer(url, 200, h, ("acw_tc",), json.dumps({"msg": said, "total": 0}).encode(), 0.01)
            body = {
                "code": 0,
                "msg": "success",
                "result": {"pageOfItems": [nuxt_item(k) for k in range(25)], "resultTotal": 413},
            }
            if self.exact and asked.get("keyword"):
                body = {"success": True, "msg": "", "result": {"total": 1, "products": [nuxt_item(4)]}}
            return Answer(url, 200, h, ("acw_tc",), json.dumps(body).encode(), 0.01)
        return Answer(url, 404, h, (), b"", 0.01)

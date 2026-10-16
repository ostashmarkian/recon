"""Reading pages: sitemaps, a product page's structured data and words,
made-up addresses, listings, catalogue sources, freshness."""

import contextlib
import html as entities
import json
import re
import zlib
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from . import settings
from .clients import Answer

# Pages a look-over must not ask for: they hold an account or change the site's state. Matched against the path
# and the query, since a cart action is often a query (?add-to-cart=12, ?controller=cart, ?route=checkout/cart).
SKIPPED_PATHS = re.compile(
    r"cart|checkout|basket|account|login|logout|signin|sign-in|register|wishlist|compare|customer|admin|password"
    # a cart in other languages: Czech and Slovak, Polish, German, French, Spanish, Italian, Dutch, Russian
    r"|kosik|ko%c5%a1%c3%adk|koszyk|warenkorb|panier|carrito|carrello|winkelwagen|korzina"
    r"|/orders?/(?:add|new|create)|[?&](?:buy|remove_item|add)="
    r"|[?&](?:action|do|op)=(?:add|remove|delete|buy|vote|subscribe)",
    re.I,
)


ASSET = re.compile(r"\.(jpe?g|png|gif|webp|svg|ico|css|js|pdf|zip|xml|gz|txt|mp4|woff2?)(\?|$)", re.I)


PRODUCT_HINT = re.compile(
    r"/(product|products|produkt|produkty|producto|prodotto|produit|item|items|goods|p|dp)/"
    r"|[-_/]p-?\d+|product_id=|/\d{5,}(?:[-/.]|$)",
    re.I,
)


# links a visitor follows: <a href>, not <link> (stylesheets, the WordPress shortlink ?p=123, canonicals)
HREF = re.compile(r"""<a\b[^<>]*?\bhref\s*=\s*["']([^"']*)["']""", re.I)


TITLE = re.compile(r"<title[^<>]*>([^<]*)</title>", re.I)


GENERATOR = re.compile(
    r"""<meta[^<>]+name=["']generator["'][^<>]+content=["']([^"']+)"""
    r"""|<meta[^<>]+content=["']([^"']+)["'][^<>]+name=["']generator["']""",
    re.I,
)


LOC = re.compile(r"<loc>\s*([^<]*?)\s*</loc>")


LASTMOD = re.compile(r"<lastmod>\s*([^<]*?)\s*</lastmod>")


ITEMPROP = re.compile(
    r"""<[^<>]*\bitemprop=["'](mpn|sku|gtin\d*|productID|brand|price|priceCurrency|availability|inventoryLevel)"""
    r"""["'][^<>]*>""",
    re.I,
)


CONTENT = re.compile(r"""\bcontent=["']([^"']*)["']""", re.I)


META = re.compile(r"""<meta[^<>]+(?:property|name)=["']((?:og|product):[a-z_:]+)["'][^<>]*>""", re.I)


TAG = re.compile(r"<[^<>]+>")


# What a product page says in words, in the shops' languages; a label is shown with what follows it.
LABELS = {
    "part number": re.compile(
        r"\b(?:MPN|Mfr\.?\s*Part\s*(?:No\.?|Number|#)|Manufacturer\s*Part\s*(?:No\.?|Number|#)?|"
        r"Part\s*(?:No\.?|Number|#)|Herstellernummer|Hersteller-?Nr|Kód výrobce|Katalogové číslo|"
        r"Numer katalogowy|N[úu]mero de (?:parte|pieza))|型番|品番|부품번호|Код производителя|Код виробника",
        re.I,
    ),
    "maker": re.compile(
        r"\b(?:Manufacturer|Brand|Hersteller|Výrobce|Producent|Fabricante|Marca|Производитель|Виробник)\b"
        r"|メーカー|제조사",
        re.I,
    ),
    "VAT": re.compile(
        r"\b(?:incl\.?|excl\.?|inc\.?|ex\.?|including|excluding|plus)\s*(?:VAT|GST|MwSt\.?|IVA|DPH)\b"
        r"|\b(?:s|bez|z)\s+(?:DPH|VAT)\b|\bIVA\s+incluid[oa]\b|\bsin\s+IVA\b|\b(?:inkl|zzgl|exkl)\.?\s*MwSt"
        r"|\bTTC\b|\bhors taxes?\b|\bbrutto\b|\bnetto\b|з ПДВ|без ПДВ|с НДС|без НДС|税込|税抜|부가세",
        re.I,
    ),
    "stock": re.compile(
        r"\b(?:in stock|out of stock|skladem|na stanie|auf Lager|en stock|en existencia|disponible)\b"
        r"|в наявності|в наличии|在庫|재고",
        re.I,
    ),
}


# Search services a shop's pages call, by what their scripts and calls show
SEARCH_SERVICES = (
    ("Algolia", ("algolianet.com", "algolia.net", "algoliasearch")),
    ("Searchanise", ("searchanise",)),
    ("Klevu", ("klevu",)),
    ("Doofinder", ("doofinder",)),
    ("Boost Commerce", ("boost-sd", "bc-sf-filter", "mybcapps.com")),
    ("Typesense", ("typesense",)),
    ("Constructor.io", ("cnstrc.com",)),
    ("Searchspring", ("searchspring",)),
    ("Bloomreach", ("bloomreach", "brcdn.com")),
    ("Luigi's Box", ("luigisbox",)),
    ("Clerk.io", ("clerk.io",)),
    ("Nosto", ("connect.nosto", "nosto.com")),
    ("Findify", ("findify",)),
    ("Solr", ("/solr/",)),
)


DATA_BLOBS = (
    ("Next.js page data", "__NEXT_DATA__"),
    ("Nuxt state", "__NUXT"),
    ("initial state", "__INITIAL_STATE__"),
    ("Apollo state", "__APOLLO_STATE__"),
    ("BigCommerce BODL", "window.bodl"),
    ("Shopify meta", "ShopifyAnalytics.meta"),
)


ENDPOINT = re.compile(
    r"""["'`](/(?:api|graphql|wp-json|rest|ajax|rpc|_next/data|search)\b[^"'`\s<>]{0,100})["'`]""", re.I
)


RATE_HEADER = re.compile(r"^(?:x-)?rate-?limit|^retry-after$", re.I)


CACHE_HEADERS = ("cf-cache-status", "x-cache", "x-cache-status", "x-proxy-cache", "x-varnish-cache")


APP_ROOT = re.compile(r"""<div[^<>]+id=["'](?:root|app|__next|__nuxt|svelte)["'][^<>]*>\s*</div>""", re.I)


PAGE_LINK = re.compile(r"([?&](?:page|p|pg|pagenumber|page_number|strana|seite|pagina)=)(\d+)|(/page/)(\d+)", re.I)


def blocks(html: str, tags: tuple[str, ...]) -> list[tuple[str, int, int, int]]:
    """(tag, where it opens, where its body starts, where it closes) of every <tag>...</tag> in `html`,
    found by scanning, never by backtracking: a page of a thousand unclosed tags stays linear."""
    low, at = html.lower(), 0
    found: list[tuple[str, int, int, int]] = []
    nexts = {tag: low.find(f"<{tag}", 0) for tag in tags}
    while True:
        for tag in tags:  # each tag's next opening, moved on only when passed
            while 0 <= nexts[tag] < at:
                nexts[tag] = low.find(f"<{tag}", at)
        open_at, tag = min(((n, tag) for tag, n in nexts.items() if n >= 0), default=(-1, ""))
        if open_at < 0:
            return found
        body = low.find(">", open_at)
        close = low.find(f"</{tag}", body) if body >= 0 else -1
        if close < 0:  # unclosed: the rest of the page is inside it
            found.append((tag, open_at, (body + 1) if body >= 0 else len(html), len(html)))
            return found
        found.append((tag, open_at, body + 1, close))
        end = low.find(">", close)
        at = (end + 1) if end >= 0 else len(html)


def visible_text(html: str) -> str:
    """The words of a page: scripts, styles and noscripts dropped, tags dropped, entities decoded, spaces collapsed."""
    parts, at = [], 0
    for _, open_at, _, close in blocks(html, ("script", "style", "noscript")):
        parts.append(html[at:open_at])
        end = html.find(">", close)
        at = (end + 1) if end >= 0 else len(html)
    parts.append(html[at:])
    return " ".join(entities.unescape(TAG.sub(" ", " ".join(parts))).split())


def gunzip(body: bytes, most: int) -> bytes:
    """`body` unpacked, at most `most` bytes: a gzip bomb raises ValueError instead of filling the memory."""
    unpack = zlib.decompressobj(zlib.MAX_WBITS | 16)
    out = unpack.decompress(body, most)
    if unpack.unconsumed_tail:
        raise ValueError(f"over {most:,} bytes unpacked")
    return out


def read_sitemap(body: bytes) -> tuple[str, list[str], list[str]]:
    """("index" | "urls", the addresses it lists, its lastmods)."""
    if body[:2] == b"\x1f\x8b":
        body = gunzip(body, settings.SITEMAP_MOST)
    text = body.decode("utf-8", "replace")
    locs = [entities.unescape(loc) for loc in LOC.findall(text)]  # "&amp;" in a <loc> is "&"
    return ("index" if "<sitemapindex" in text[:2000] else "urls"), locs, LASTMOD.findall(text)


def short(value: Any, most: int = 60) -> str | None:
    return None if value in (None, "") else " ".join(str(value).split())[:most]


LD_DEPTH = 64  # levels of JSON-LD nesting read; a page nested deeper is not a product page


def ld_products(html: str) -> list[dict[str, Any]]:
    """The schema.org Products of a page's JSON-LD blocks, @graph and nesting opened."""
    found = []

    def walk(root: Any) -> None:
        """Every dict in `root`, in order, by a stack: no recursion, LD_DEPTH levels at most."""
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if depth > LD_DEPTH:
                continue
            if isinstance(node, list):
                stack.extend((item, depth + 1) for item in reversed(node))
            elif isinstance(node, dict):
                kinds = node.get("@type")
                kinds = kinds if isinstance(kinds, list) else [kinds]
                if any(isinstance(k, str) and (k.endswith("Product") or k == "ProductGroup") for k in kinds):
                    found.append(node)
                stack.extend((v, depth + 1) for v in reversed(list(node.values())) if isinstance(v, (list, dict)))

    scripts = blocks(html, ("script",))
    lds = [
        html[start:close]
        for _, open_at, start, close in scripts
        if "application/ld+json" in html[open_at:start].lower()
    ]
    for block in lds:
        try:
            walk(json.loads(block.strip()))
        except (ValueError, RecursionError):
            try:  # raw line breaks inside its strings, as some themes write them
                walk(json.loads(re.sub(r"[\x00-\x1f]+", " ", block)))
            except (ValueError, RecursionError):  # nesting deeper than json can read
                continue
    return found


def product_fields(p: dict[str, Any]) -> dict[str, Any]:
    """What one JSON-LD Product holds of what a parts buyer needs."""
    offers = p.get("offers") or {}
    many = len(offers) if isinstance(offers, list) else None
    offers = (offers[0] if offers else {}) if isinstance(offers, list) else offers
    offers = offers if isinstance(offers, dict) else {}
    spec = offers.get("priceSpecification") or {}
    spec = (spec[0] if spec else {}) if isinstance(spec, list) else spec
    spec = spec if isinstance(spec, dict) else {}
    brand = p.get("brand")
    brand = brand.get("name") if isinstance(brand, dict) else brand
    level = offers.get("inventoryLevel")
    return {
        "name": short(p.get("name")),
        "sku": short(p.get("sku")),
        "mpn": short(p.get("mpn")),
        "gtin": short(next((p[k] for k in ("gtin", "gtin13", "gtin12", "gtin14", "gtin8") if p.get(k)), None)),
        "brand": short(brand),
        "price": short(offers.get("price") or offers.get("lowPrice") or spec.get("price")),
        "currency": short(offers.get("priceCurrency") or spec.get("priceCurrency")),
        "vat_included": spec.get("valueAddedTaxIncluded"),
        "availability": short(str(offers.get("availability") or "").rsplit("/", 1)[-1]),
        "inventory": short(level.get("value") if isinstance(level, dict) else level),
        "offers": many,
    }


def product_data(a: Answer) -> dict[str, Any]:
    """What a product page carries: JSON-LD, from the whole page (big pages carry it at their end, and
    its scan is linear); microdata, product meta tags and labels in its words, from its first HEAD bytes."""
    html = a.head
    products = ld_products(a.text)
    jsonld = {k: v for k, v in product_fields(products[0]).items() if v not in (None, "")} if products else {}
    microdata = {}
    for found in ITEMPROP.finditer(html):
        name = found.group(1)
        content = CONTENT.search(found.group(0))
        value = content.group(1) if content else html[found.end() : found.end() + 200].split("<", 1)[0]
        if name not in microdata and short(value):
            microdata[name] = short(value)
    meta = {}
    for found in META.finditer(html):
        content = CONTENT.search(found.group(0))
        if content and found.group(1).lower() not in meta:
            meta[found.group(1).lower()] = short(content.group(1))
    meta = {
        k: v
        for k, v in meta.items()
        if k.startswith("product:") or k in ("og:type", "og:price:amount", "og:price:currency")
    }
    words = visible_text(html)
    labels: dict[str, list[str]] = {}
    for name, pattern in LABELS.items():
        seen = [words[m.start() : m.end() + 50] for m in pattern.finditer(words)]
        if seen:
            labels[name] = list(dict.fromkeys(seen))[:3]
    has_data = bool(jsonld or microdata or meta.get("og:type") == "product" or "part number" in labels)
    return {
        "found": has_data,
        "jsonld": jsonld,
        "jsonld_products": len(products),
        "microdata": microdata,
        "meta": meta,
        "labels": labels,
    }


def made_up(url: str) -> str:
    """An address shaped like `url` that no shop holds: its last run of four
    or more digits turned to nines of the same width (/2020000010 ->
    /9999999999), else of two or more in its query, else NONCE added to its
    last part."""
    parts = urlsplit(url)
    for field_name, at_least in (("path", 4), ("query", 2)):
        value = getattr(parts, field_name)
        runs = list(re.finditer(rf"\d{{{at_least},}}", value))
        if runs:
            run = runs[-1]
            value = value[: run.start()] + "9" * len(run.group()) + value[run.end() :]
            return parts._replace(**{field_name: value}).geturl()
    head, _, last = parts.path.rstrip("/").rpartition("/")
    stem, dot, ext = last.partition(".")
    trail = "/" if parts.path.endswith("/") and last else ""
    return parts._replace(path=f"{head}/{stem}-{settings.NONCE}{dot}{ext}{trail}").geturl()


def listing_page(urls: Iterable[str]) -> tuple[str, str] | None:
    """(a listing page, the same with page FAR_PAGE) from the first address with a page number; None."""
    for url in urls:
        found = PAGE_LINK.search(url)
        if found:
            if found.group(1):
                far = url[: found.start(2)] + str(settings.FAR_PAGE) + url[found.end(2) :]
            else:
                far = url[: found.start(4)] + str(settings.FAR_PAGE) + url[found.end(4) :]
            return url, far
    return None


def sources_of(answers: Iterable[Answer]) -> dict[str, Any]:
    """Catalogue sources the pages point to: search services, page-data blobs, API paths."""
    services, blobs, endpoints = {}, [], []
    for a in answers:
        text = a.head
        low = text.lower()
        for name, needles in SEARCH_SERVICES:
            hit = next((n for n in needles if n in low), None)
            if hit and name not in services:
                services[name] = hit
        for name, needle in DATA_BLOBS:
            if needle in text and name not in blobs:
                blobs.append(name)
        for path in ENDPOINT.findall(text):
            if path not in endpoints:
                endpoints.append(path)
    return {"search": services, "blobs": blobs, "endpoints": endpoints[:20]}


def rate_headers(answers: Iterable[Answer]) -> dict[str, str | None]:
    """{header: a value} of the rate-limit headers any answer carried."""
    found = {}
    for a in answers:
        for name, value in a.headers.items():
            if RATE_HEADER.match(name) and name not in found:
                found[name] = short(value)
    return found


def freshness(answers: Iterable[Answer | None]) -> dict[str, Any]:
    """How fresh the pages are: cache statuses, the oldest Age and Last-Modified."""
    statuses: Counter[str] = Counter()
    controls: Counter[str] = Counter()
    ages: list[int] = []
    modified: list[datetime] = []
    pages = 0
    for a in answers:
        if not a or a.error or a.status != 200:
            continue
        pages += 1
        h = a.headers
        status = next((h[k] for k in CACHE_HEADERS if h.get(k)), None)
        if status:
            statuses[status.split(",")[0].strip().upper()[:24]] += 1
        if h.get("age", "").strip().isdigit():
            ages.append(int(h["age"].strip()))
        if h.get("last-modified"):
            with contextlib.suppress(TypeError, ValueError):
                when = parsedate_to_datetime(h["last-modified"])
                modified.append(when if when.tzinfo else when.replace(tzinfo=UTC))  # no zone written: GMT
        if h.get("cache-control"):
            controls[h["cache-control"][:60]] += 1
    oldest = min(modified) if modified else None
    return {
        "pages": pages,
        "cache": dict(statuses),
        "age_max": max(ages) if ages else None,
        "last_modified_oldest": oldest.isoformat() if oldest else None,
        "last_modified_days": round((datetime.now(UTC) - oldest).total_seconds() / 86_400, 1)
        if oldest and oldest.tzinfo
        else None,
        "cache_control": controls.most_common(1)[0][0] if controls else None,
    }


def drawn(a: Answer) -> dict[str, Any]:
    """Whether a page's HTML holds little but a JavaScript app: its visible
    text, and an empty app root."""
    words = visible_text(a.head)
    root = bool(APP_ROOT.search(a.head))
    code = bool(re.search(r"<script(?![^<>]*application/ld\+json)", a.head, re.I))
    return {"text": len(words), "empty_root": root, "drawn": root or (len(words) < 100 and code)}

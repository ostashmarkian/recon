"""Reading pages: sitemaps, a product page's structured data and words, whether a page is a product or a
listing, made-up addresses, listings, catalogue sources, freshness."""

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
from .state import read_state, short

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


def family(url: str) -> tuple[str, int, bool]:
    """A page address's shape: its first path segment, how many segments, and whether its last holds a digit.
    /product/123/ and /product/456/ are one family; /products/highlights/capacitors/ another."""
    segments = [s for s in urlsplit(url).path.lower().split("/") if s]
    return (segments[0] if segments else "", len(segments), bool(segments) and any(c.isdigit() for c in segments[-1]))


def by_family(urls: Iterable[str]) -> list[str]:
    """`urls`, one of each family in turn, the largest family first: a few tries meet several kinds of page."""
    groups: dict[tuple[str, int, bool], list[str]] = {}
    for url in urls:
        groups.setdefault(family(url), []).append(url)
    ordered = sorted(groups.values(), key=len, reverse=True)
    return [g[i] for i in range(max(map(len, ordered), default=0)) for g in ordered if i < len(g)]


def listing_of(products: list[str], links: list[str]) -> str | None:
    """A category page: a link whose path a product's path goes on from (a breadcrumb: /catalog/diodes for
    /catalog/diodes/1234), else one of the largest family of the other links two segments deep or more."""
    paths = [urlsplit(u).path.rstrip("/") for u in products[:500]]
    taken = set(products)
    others = [u for u in dict.fromkeys(links) if u not in taken]
    crumbs = [
        u
        for u in others
        if urlsplit(u).path.rstrip("/").count("/") >= 2
        and any(p.startswith(urlsplit(u).path.rstrip("/") + "/") for p in paths)
    ]
    if crumbs:  # the deepest: a category, not the catalogue's root
        return max(crumbs, key=lambda u: urlsplit(u).path.rstrip("/").count("/"))
    deeper = [u for u in others if urlsplit(u).path.strip("/").count("/") >= 1 and not urlsplit(u).query]
    return next(iter(by_family(deeper)), None)


# a sitemap file of products, by its name: sitemap_products_1.xml, xmlsitemap.php?type=products, items-3.xml.gz
SITEMAP_HINT = re.compile(r"product|item|goods|catalog|offer|sku", re.I)


def spread(items: list[str], most: int, prefer: re.Pattern[str] | None = None) -> list[str]:
    """Up to `most` of `items`, those `prefer` matches first; each group picked evenly from its first to its last."""

    def even(group: list[str], k: int) -> list[str]:
        if k <= 0:
            return []
        if len(group) <= k:
            return group
        return [group[round(i * (len(group) - 1) / (k - 1))] for i in range(k)] if k > 1 else group[:1]

    first = [u for u in items if prefer and prefer.search(u)]
    rest = [u for u in items if not (prefer and prefer.search(u))]
    picked = even(first, most)
    return picked + even(rest, most - len(picked))


ASSET = re.compile(r"\.(jpe?g|png|gif|webp|svg|ico|css|js|pdf|zip|xml|gz|txt|mp4|woff2?)(\?|$)", re.I)


PRODUCT_HINT = re.compile(
    r"/(product|products|produkt|produkty|producto|prodotto|produit|item|items|goods|p|dp)/"
    r"|[-_/]p-?\d+|product_id=|/\d{5,}(?:[-/.]|$)",
    re.I,
)


# A product's address by a path segment that says so: /product/, /products/, /p/, /item/, /dp/. Links like these are
# tried before those with only a long number (/category/usb/070403.html has one too)
PRODUCT_PATH = re.compile(
    r"/(?:product|products|produkt|produkty|producto|prodotto|produit|item|items|goods|p|dp)/", re.I
)


# A listing's address by its first segment: a category, a collection, a brand's or maker's page, a search. Only an
# order: such links are tried last, since a shop can keep its products under /catalog/ or /c/ as well
LISTING_PATH = re.compile(
    r"^/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?(?:category|categories|cat|c|collections?|brands?|manufacturers?|makers?"
    r"|search|tags?|kategorie|kategoria|categoria|categorie|kategorii)(?:[/.]|$)",
    re.I,
)


# a listing's title: "Page 2 of Resistors"
PAGE_OF = re.compile(r"\bpage\s+\d+\s+of\b", re.I)


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


LD_DEPTH = 64  # levels of JSON-LD nesting read; a page nested deeper is not a product page


def ld_products(html: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The schema.org Products of a page's JSON-LD blocks, @graph and nesting opened: (those standing on their own,
    those listed in an ItemList). A Product inside another one (a variant, a related product) is neither."""
    found: list[dict[str, Any]] = []
    listed: list[dict[str, Any]] = []

    def walk(root: Any) -> None:
        """Every dict in `root`, in order, by a stack: no recursion, LD_DEPTH levels at most. `inside` is "list"
        under an ItemList and "product" under a Product."""
        stack: list[tuple[Any, int, str]] = [(root, 0, "")]
        while stack:
            node, depth, inside = stack.pop()
            if depth > LD_DEPTH:
                continue
            if isinstance(node, list):
                stack.extend((item, depth + 1, inside) for item in reversed(node))
            elif isinstance(node, dict):
                kinds = node.get("@type")
                kinds = kinds if isinstance(kinds, list) else [kinds]
                below = inside
                if any(isinstance(k, str) and (k.endswith("Product") or k == "ProductGroup") for k in kinds):
                    if inside != "product":
                        (listed if inside == "list" else found).append(node)
                    below = "product"
                elif "ItemList" in kinds and inside != "product":
                    below = "list"
                stack.extend(
                    (v, depth + 1, below) for v in reversed(list(node.values())) if isinstance(v, (list, dict))
                )

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
    return found, listed


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


LISTED_MOST = 3  # JSON-LD Products standing side by side on a page: as many, and it lists them


def page_kind(
    a: Answer, products: list[dict[str, Any]], listed: list[dict[str, Any]], state: dict[str, Any] | None
) -> tuple[str, str]:
    """("product" | "listing" | "", why). A product page is about one product: a JSON-LD Product of its own, or a
    product in its state. A listing lists them: an ItemList of Products, several Products side by side, a product
    list in its state with its counts beside it, a page number in its address or "Page 2 of" in its title."""
    if len(products) >= LISTED_MOST:
        return "listing", f"{len(products)} JSON-LD Products side by side"
    if products:
        return "product", "a JSON-LD Product"
    if state and state.get("product"):
        return "product", f"a product in its state at `{state['product']['path']}`"
    if len(listed) >= 2:
        return "listing", f"a JSON-LD ItemList of {len(listed)} Products"
    counted = [x for x in (state or {}).get("lists") or [] if x["counts"]]
    if counted:
        return "listing", f"a list of {counted[0]['items']} products in its state at `{counted[0]['path']}`"
    title = TITLE.search(a.head)
    paged = PAGE_LINK.search(a.url)  # page 2 or more; ?p= left out, as WordPress names a post so
    if paged and (paged.group(1) or "").lower()[1:] != "p=" and int(paged.group(2) or paged.group(4)) >= 2:
        return "listing", "a page number in its address"
    if title and PAGE_OF.search(entities.unescape(title.group(1))):
        return "listing", "a page number in its title"
    return "", ""


def product_data(a: Answer) -> dict[str, Any]:
    """What a product page carries: JSON-LD, from the whole page (big pages carry it at their end, and
    its scan is linear); its state (Nuxt's, Next.js's); microdata, product meta tags and labels in its words,
    from its first HEAD bytes. And whether it is a product page at all, or a listing."""
    html = a.head
    products, listed = ld_products(a.text)
    state = read_state(a.text)
    kind, why = page_kind(a, products, listed, state)
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
    held = (state or {}).get("product")
    has_data = bool(jsonld or microdata or meta.get("og:type") == "product" or "part number" in labels or held)
    return {
        "found": has_data and kind != "listing",
        "kind": kind,
        "kind_why": why,
        "jsonld": jsonld,
        "jsonld_products": len(products),
        "jsonld_listed": len(listed),
        "microdata": microdata,
        "meta": meta,
        "labels": labels,
        # what the page's state holds: its format, the product it is about, its product lists
        "state": {"format": state["format"], "product": held, "lists": state["lists"][:3]} if state else None,
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

"""A site's platform from the markers its pages show, and the open API such a
platform has: its count, and a product's SKU and MPN."""

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import quote

from . import settings
from .clients import Answer
from .pages import GENERATOR, SCRIPTS, TAG

# (platform, markers): where a marker is looked for - "html" (as written),
# "header" ("name: value" lowercased), "cookie" (a name it starts) or
# "robots" - each one seen on that platform's shops.
PLATFORMS = (
    (
        "Shopify",
        (
            ("header", "powered-by: shopify"),
            ("cookie", "_shopify_y"),
            ("html", "Shopify.shop"),
            ("html", "cdn.shopify.com"),
        ),
    ),
    (
        "BigCommerce",
        (
            ("html", "bigcommerce.stencil"),
            ("html", "cdn11.bigcommerce.com"),
            ("html", "BCData"),
            ("header", "x-bc-store-id"),
        ),
    ),
    (
        "WooCommerce",
        (("html", "wp-content/plugins/woocommerce"), ("html", "wc_add_to_cart_params"), ("html", "woocommerce_params")),
    ),
    ("WordPress", (("html", "/wp-content/"), ("header", 'rel="https://api.w.org/"'))),
    (
        "Magento 2",
        (("html", "/static/version"), ("html", "Magento_"), ("header", "x-magento-"), ("header", "x-built-with: hyva")),
    ),
    ("Magento 1 / OpenMage", (("html", "skin/frontend/"), ("html", "Mage.Cookies"))),
    (
        "PrestaShop",
        (("cookie", "PrestaShop-"), ("robots", "PrestaShop"), ("html", "var prestashop"), ("html", "ajax_cart")),
    ),
    ("OpenCart", (("html", "index.php?route="), ("html", "catalog/view/theme"))),
    ("Zoho Commerce", (("html", "Zoho Commerce"), ("html", "zohoecommerce.com"))),
    ("IdoSell", (("html", "IdoSell"), ("html", "iai-shop"), ("html", "app_shop.vars"), ("cookie", "__IAI_SRC"))),
    ("Ocnk", (("html", "ocnk-min.js"),)),
    ("PinnacleCart", (("html", "cartVersionRaw"), ("cookie", "ShoppingCartSession"))),
    ("Shopamine", (("html", "myshopamine.com"),)),
    ("Shopsys", (("header", "x-powered-by: shopsys"),)),
    ("SummerCart", (("html", "Summer Cart"), ("cookie", "MIPHPF_SESSION"))),
    ("SvelteKit", (("header", "x-sveltekit-page"), ("html", "/_app/immutable/"))),
    ("ecbeing", (("html", "ecblib"), ("html", "/js/sys/sys.js"))),
    ("Nuxt", (("html", "__NUXT__"), ("html", "/_nuxt/"))),
    ("Next.js", (("html", "__NEXT_DATA__"), ("html", "/_next/static"))),
    ("nopCommerce", (("html", "nopCommerce"), ("cookie", "Nop."))),
    ("Shopware", (("html", "Shopware"),)),
    ("Odoo", (("html", "/web/assets/"),)),
    ("Wix", (("header", "x-wix-request-id"),)),
    ("Squarespace", (("html", "static1.squarespace.com"),)),
    ("Ecwid", (("html", "app.ecwid.com"),)),
)


STACKS = (
    ("ASP.NET", (("cookie", "ASP.NET_SessionId"), ("header", "x-aspnet-version"), ("header", "x-powered-by: asp.net"))),
    ("PHP", (("cookie", "PHPSESSID"), ("header", "x-powered-by: php"))),
    ("Laravel", (("cookie", "laravel_session"),)),
    ("Java", (("cookie", "JSESSIONID"),)),
    ("Express", (("header", "x-powered-by: express"),)),
)


# BigCommerce's storefront GraphQL token, in the HTML of any page of a Stencil theme
BC_TOKEN = re.compile(r"eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9\.[\w-]+\.[\w-]+")


# OpenCart's "Showing 1 to 1 of 18217 (18217 Pages)", in a few of its languages
OPENCART_TOTAL = re.compile(r"\b(?:of|z|von|de|из|з|di)\s+(\d[\d,. ]*?)\s*\(", re.I)


def api_request(name: str, origin: str, html: str) -> tuple[str, str, dict[str, str], bytes | None] | None:
    """(method, url, headers, body) for the open API of platform `name`; None
    when it has none, or (BigCommerce) its pages carry no token."""
    accept = {"Accept": "application/json"}
    if name == "Shopify":
        return "GET", origin + "/products.json?limit=1", accept, None
    if name == "WooCommerce":
        return "GET", origin + "/wp-json/wc/store/v1/products?per_page=1", accept, None
    if name == "WordPress":
        return "GET", origin + "/wp-json/", accept, None
    if name == "Zoho Commerce":
        return "GET", origin + "/api/v1/products?page_number=1", accept, None
    if name == "Magento 2":
        query = '{products(search:"",pageSize:1){total_count items{sku}}}'
        return "GET", origin + "/graphql?query=" + quote(query), accept, None
    if name == "OpenCart":
        return "GET", origin + "/index.php?route=product/search&search=&limit=1", {}, None
    if name == "BigCommerce":
        token = BC_TOKEN.search(html)
        if not token:
            return None
        body = json.dumps({"query": "{site{products(first:1){edges{node{entityId sku mpn}}}}}"}).encode()
        headers = {**accept, "Content-Type": "application/json", "Authorization": f"Bearer {token.group()}"}
        return "POST", origin + "/graphql", headers, body
    return None


def api_says(name: str, a: Answer) -> str:
    """What an open API's answer tells: the catalogue's count, and the part-number fields of a product."""
    if a.status != 200:
        return ""
    if name == "OpenCart":
        found = OPENCART_TOTAL.search(" ".join(TAG.sub(" ", SCRIPTS.sub(" ", a.head)).split()))
        return f"the empty search counts {found.group(1).strip()}" if found else "no 'of N (' counter on the page"
    try:
        data = json.loads(a.body)
    except ValueError:
        return "not JSON"
    try:
        if name == "Shopify":
            products = data.get("products") or []
            variant = (products[0].get("variants") or [{}])[0] if products else {}
            return (
                f"open; a variant has sku {variant.get('sku')!r}, barcode {variant.get('barcode')!r}"
                if products
                else "open, no product"
            )
        if name == "WooCommerce":
            first = data[0] if isinstance(data, list) and data else {}
            return f"X-WP-Total {a.headers.get('x-wp-total')}; a product has sku {first.get('sku')!r}"
        if name == "WordPress":
            return "namespaces " + ", ".join((data.get("namespaces") or [])[:12])
        if name == "Zoho Commerce":
            return f"keys {sorted(data)[:8]}"
        if data.get("errors"):
            return "errors: " + "; ".join(str(e.get("message"))[:80] for e in data["errors"][:2])
        if name == "Magento 2":
            products = data["data"]["products"]
            first = (products.get("items") or [{}])[0]
            return f"total_count {products.get('total_count')}; a product has sku {first.get('sku')!r}"
        if name == "BigCommerce":
            edges = data["data"]["site"]["products"]["edges"]
            node = edges[0]["node"] if edges else {}
            return f"storefront GraphQL open; a product has sku {node.get('sku')!r}, mpn {node.get('mpn')!r}"
    except (AttributeError, KeyError, IndexError, TypeError):
        return "an answer of another shape"
    return ""


def markers_found(markers: Iterable[tuple[str, str]], home: Answer, robots_text: str) -> list[str]:
    lines = "\n".join(f"{k}: {v}" for k, v in home.headers.items()).lower()
    html = home.text[: settings.BODY_KEPT]
    found = []
    for where, needle in markers:
        hit = (
            (where == "html" and needle in html)
            or (where == "header" and needle in lines)
            or (where == "cookie" and any(c.startswith(needle) for c in home.cookies))
            or (where == "robots" and needle in robots_text)
        )
        if hit:
            found.append(f"{where} {needle}")
    return found


def platforms_of(
    home: Answer, robots_text: str = "", notes: Sequence[tuple[Path, str]] = ()
) -> tuple[list[tuple[str, list[str], str | None]], list[tuple[str, list[str]]], str | None]:
    """([(platform, evidence, a note named after it or None)], [(stack, evidence)], generator).
    `notes`: (path, text) of the Markdown notes to link to."""
    names = sorted(path.stem for path, _ in notes)
    platforms = []
    for name, markers in PLATFORMS:
        found = markers_found(markers, home, robots_text)
        if found:
            note = next((n for n in names if n.lower().startswith(name.lower())), None)
            platforms.append((name, found, note))
    stacks = [(name, found) for name, markers in STACKS if (found := markers_found(markers, home, robots_text))]
    generator = GENERATOR.search(home.text[: settings.BODY_KEPT])
    return platforms, stacks, (generator.group(1) or generator.group(2)) if generator else None

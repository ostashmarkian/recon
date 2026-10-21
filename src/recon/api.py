"""The site's own API, found without a browser: the API bases a page's runtime config names (Nuxt's
window.__NUXT__.config, Next.js's __NEXT_DATA__, a plain apiHost or API_URL in an inline script), the routes its
own JS bundles call (on its host, or its build on a CDN), and a helper that signs or marks their calls. Whether
each API host resolves in public DNS: an internal one is reported and never asked."""

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

from .browser import TRACKERS
from .pages import ASSET, blocks

# a config key that names where the API is: apiHost, API_URL, serverApiHost, graphqlEndpoint, an axios baseURL
BASE_KEY = re.compile(r"api|endpoint|graphql|backend|gateway|^base_?url$", re.I)
# an address in a config object, JSON or an assignment, after its key ("https://..." or "//..."); the key is read
# back from there, so the scan meets a key only where an address follows
URL_VALUE = re.compile(r"""[:=]\s*(["'`])((?:https?:)?//[^"'`\s<>\\]{3,300})\1""")
KEY_BEFORE = re.compile(r"""["']?([A-Za-z_$][\w$]{0,60})["']?\s*$""")


def scripts_of(html: str) -> list[tuple[str, str]]:
    """(opening tag, text) of every inline <script> of a page: its own code and data, not a file it loads."""
    found = []
    for _, open_at, start, close in blocks(html, ("script",)):
        tag = html[open_at:start]
        if "src=" not in tag.lower() and "ld+json" not in tag.lower():
            found.append((tag, html[start:close]))
    return found


def config_source(tag: str, text: str) -> str:
    if "__NUXT__.config" in text:
        return "the Nuxt runtime config"
    if "__NUXT__" in text:
        return "the Nuxt state"
    if "__NEXT_DATA__" in tag:
        return "Next.js __NEXT_DATA__"
    return "an inline script"


def api_bases(html: str) -> list[dict[str, Any]]:
    """The API bases a page's inline scripts name: [{url, keys, source}], one per address, in the order seen.
    Escaped slashes (Nuxt 2 writes https:\\u002F\\u002F) are read as slashes; trackers and files are left out."""
    found: dict[str, dict[str, Any]] = {}
    for tag, text in scripts_of(html):
        plain = text.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
        for match in URL_VALUE.finditer(plain):
            named = KEY_BEFORE.search(plain, max(0, match.start() - 70), match.start())
            key, url = (named.group(1) if named else ""), match.group(2).rstrip("/")
            if not BASE_KEY.search(key) or TRACKERS.search(url) or ASSET.search(urlsplit(url).path):
                continue
            url = "https:" + url if url.startswith("//") else url
            base = found.setdefault(url, {"url": url, "keys": [], "source": config_source(tag, text)})
            if key not in base["keys"]:
                base["keys"].append(key)
    return list(found.values())


SCRIPT_SRC = re.compile(r"""<script\b[^<>]*?\bsrc\s*=\s*["']?([^"'\s<>]+)""", re.I)
LINK_TAG = re.compile(r"<link\b[^<>]*>", re.I)
ATTR = re.compile(r"""\b(href|rel|as)\s*=\s*["']?([^"'<>]+?)["'\s>]""", re.I)
JS_FILE = re.compile(r"\.m?js(?:\?|$)", re.I)
# Nuxt's runtime config names where its build is: app:{buildAssetsDir:"/_nuxt/",cdnURL:"https://cdn.example.com"};
# Next.js's __NEXT_DATA__ its assetPrefix
ASSETS_DIR = re.compile(r"""buildAssetsDir["']?\s*:\s*["'](/[^"'\s]{0,100})["']""")
CDN_URL = re.compile(r"""(?:cdnURL|assetPrefix)["']?\s*:\s*["']((?:https?:)?//[^"'\s/]{1,200})""")


def builds_of(html: str) -> tuple[set[str], set[str]]:
    """(the build directories, the hosts of a CDN) a page's runtime config names (Nuxt's cdnURL, Next's assetPrefix)."""
    dirs = {d.replace("\\u002F", "/") for d in ASSETS_DIR.findall(html) if len(d) > 1}
    hosts = {(urlsplit(u if "://" in u else "https:" + u).hostname or "").lower() for u in CDN_URL.findall(html)}
    return dirs, hosts - {""}


def bundle_refs(html: str, page: str) -> list[str]:
    """The JS files a page loads, in its order: <script src>, and <link> preloads of scripts (modulepreload)."""
    found = [urljoin(page, src) for src in SCRIPT_SRC.findall(html)]
    for tag in LINK_TAG.findall(html):
        attrs = {k.lower(): v.strip().lower() if k.lower() != "href" else v.strip() for k, v in ATTR.findall(tag)}
        rel = attrs.get("rel", "")
        script = "modulepreload" in rel or (("preload" in rel or "prefetch" in rel) and attrs.get("as") == "script")
        if "href" in attrs and script:
            found.append(urljoin(page, attrs["href"]))
    return [u for u in dict.fromkeys(found) if JS_FILE.search(urlsplit(u).path)]


# a chunk a bundle loads: "./index.B2kx.js", "/_nuxt/B2kx.js", "_nuxt/B2kx.js" (Vite's map of a page's chunks)
CHUNK = re.compile(
    r"""["'`]((?:\.{1,2}/|/?(?:_nuxt|_next/static|assets|static/js|js|build|dist)/)[\w@./-]{1,200}?\.m?js)["'`]"""
)


def chunk_refs(js: str, bundle: str) -> list[str]:
    """The other JS files a bundle names: relative ones read against it, the others against the site's root."""
    origin = "{0.scheme}://{0.netloc}/".format(urlsplit(bundle))
    found = []
    for ref in CHUNK.findall(js):
        found.append(urljoin(bundle if ref.startswith(".") else origin, ref))
    return list(dict.fromkeys(found))


# An API route in a bundle: {url: "/www-api/search/get-list", method: "get"} as axios takes it; .get("/x") and
# .post("/x"); fetch("/x"), $fetch("/x"), useFetch("/x"); `${base}/api/x`; and any string under /api/ (or api/,
# as Angular writes it, relative), /graphql, /rest, /ajax
URL_PROP = re.compile(r"""\burl\s*:\s*(["'`])(/[^"'`\s<>\\]{1,200})\1""")
CALL = re.compile(
    r"""(?:\.(get|post|put|delete|patch)|(?<![\w$])(\$fetch|useFetch|useLazyFetch|ofetch|fetch|request|http))"""
    r"""\s*\(\s*(["'`])((?:/|api/)[^"'`\s<>\\]{1,200})\3""",
    re.I,
)
# one run of path characters after the first segment, not a repeated group: a group of segments that may hold
# slashes themselves backtracks exponentially on a long path with no closing quote
API_PATH = re.compile(
    r"""(["'`])(/?api/[^"'`\s<>\\]{1,200}|/(?:[\w-]{0,40}api[\w-]{0,40}|graphql|gql|rest|ajax|rpc)/[^"'`\s<>\\]{1,200})\1""",
    re.I,
)
TEMPLATE_PATH = re.compile(r"""`\$\{[^}`]{1,60}\}(/[^`\s<>\\]{1,200})`""")
METHOD = re.compile(r"""\bmethod\s*:\s*["'`](get|post|put|delete|patch)["'`]""", re.I)
TEMPLATE = re.compile(r"\$\{[^}]{0,80}\}")
NOT_ROUTES = re.compile(r"^//|^/_nuxt/|^/_next/|[*:]", re.I)


def method_near(js: str, start: int, end: int) -> str | None:
    """The method written in the object around js[start:end]: from its "{" to its "}", 200 characters each way."""
    opened = js.rfind("{", max(0, start - 200), start)
    closed = js.find("}", end, end + 200)
    found = METHOD.search(js[opened if opened >= 0 else start : closed if closed >= 0 else end])
    return found.group(1).upper() if found else None


def routes_in(js: str) -> list[dict[str, str]]:
    """The API routes a script names, with their method where it shows ("?" where it does not): [{route, method}]."""
    found: dict[str, str] = {}

    def add(route: str, method: str | None) -> None:
        route = TEMPLATE.sub("{}", route).rstrip(".,;")
        route = route if route.startswith("/") else f"/{route}"  # api/x, relative to the site's root
        bare = route.count("/") < 2 and "api" not in route  # /login: a page, not an API route
        if bare or NOT_ROUTES.search(route) or ASSET.search(route.split("?")[0]):
            return
        if found.get(route, "?") == "?":
            found[route] = method or "?"

    for match in URL_PROP.finditer(js):
        method = method_near(js, match.start(), match.end())
        if method or API_PATH.fullmatch(f"{match.group(1)}{match.group(2)}{match.group(1)}"):  # not a menu's link
            add(match.group(2), method)
    for match in CALL.finditer(js):
        if match.group(1):
            method = match.group(1).upper()
        else:
            said = METHOD.search(js[match.end() : js.find(")", match.end(), match.end() + 300)])
            fetches = match.group(2).lower() not in ("request", "http")
            method = said.group(1).upper() if said else ("GET" if fetches else None)
        add(match.group(4), method)
    for match in API_PATH.finditer(js):
        add(match.group(2), method_near(js, match.start(), match.end()))
    for match in TEMPLATE_PATH.finditer(js):  # `${base}/x`: a route on a base the code holds
        method = method_near(js, match.start(), match.end())
        if method or API_PATH.fullmatch(f'"{match.group(1)}"'):
            add(match.group(1), method)
    return [{"route": r, "method": m} for r, m in found.items()]


# what a route is for, by its words: the first that fits
ROUTE_KINDS = (
    ("stock and price", re.compile(r"stock|inventor|availab|price|quote|qty", re.I)),
    ("detail", re.compile(r"detail|info(?:\b|[-_])", re.I)),
    (
        "lists and search",
        re.compile(r"search|query|find|suggest|list|filter|cate|catalog|product|goods|items|spu|sku", re.I),
    ),
)
PRODUCT_WORDS = re.compile(r"product|goods|spu|sku|item|part", re.I)
LIST_WORDS = re.compile(r"search|list|query|filter|page|result", re.I)


def route_kind(route: str) -> str:
    return next((name for name, pattern in ROUTE_KINDS if pattern.search(route.split("?")[0])), "other")


# a route's words, snake, kebab or camel case: wish-lists-for-user, getRecommendedProducts
WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")
# words of a route that changes the site's state, or reads a visitor's own: never asked, even by GET
STATE_WORDS = {
    "add", "new", "create", "edit", "update", "delete", "del", "remove", "save", "send", "submit", "set", "put",
    "login", "logout", "signin", "signup", "register", "pay", "payment", "order", "orders", "checkout", "cart",
    "basket", "subscribe", "unsubscribe", "vote", "rate", "review", "comment", "upload", "wish", "wishlist",
    "favorite", "favourite", "favorites", "favourites", "account", "user", "users", "profile", "password",
}  # fmt: skip


def stateful(route: str) -> bool:
    """Whether a route's words say it changes something or reads a visitor's own data."""
    return any(w.lower() in STATE_WORDS for w in WORDS.findall(route.split("?")[0]))


# a key that names the API's own base: apiHost, API_URL, apiBaseUrl, baseURL; not paymentApiUrl or serverApiHost
API_KEY = re.compile(r"(?:public)?api(?:host|url|base|baseurl|root|endpoint|domain|server|prefix)?|baseurl")


def names_api(keys: list[str]) -> bool:
    """Whether a base's keys name it as the API's own base, not another service's or the servers'."""
    return any(API_KEY.fullmatch(re.sub(r"[_-]", "", k).lower()) for k in keys)


# where a host's registrable domain is two labels under a country's code: shop.co.uk, shop.com.au
SECOND_LEVELS = {"co", "com", "net", "org", "gov", "edu", "ac", "or", "ne", "go", "gob", "nic", "ltd", "plc"}


def domain_of(host: str) -> str:
    """The domain a host is registered under: www.shop.com and static.shop.com are shop.com, a.shop.co.uk is
    shop.co.uk. A guess without the public suffix list; an address is itself."""
    host = host.lower().strip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVELS else 2
    return ".".join(labels[-keep:])


def same_domain(a: str, b: str) -> bool:
    """Two hosts under one registered domain: the site's API or CDN on a host of its own."""
    return bool(a) and bool(b) and domain_of(a) == domain_of(b)


# what an API's JSON says of itself, under one of these keys
MESSAGE_KEYS = {"msg", "message", "error", "errmsg", "error_msg", "errormessage", "detail", "error_description"}
# a message that says the call failed, not that it worked
ERROR_WORDS = re.compile(
    r"required|missing|invalid|error|denied|not allowed|forbidden|fail|illegal|unauthori[sz]ed|wrong|"
    r"不能|错误|失败|缺少",
    re.I,
)
# a message naming what the call lacks: "Either cate_id or keyword is required"
NEEDS = re.compile(
    r"required|missing|must be (?:given|provided|set)|needed|cannot be (?:empty|blank|null)|不能为空", re.I
)
# the parameters recon can fill with a value the run has: a search word (a part number), a category's id
KEYWORD_PARAM = re.compile(r"^(?:keywords?|q|query|search|kw|term|wd|search_?(?:key|term|word|text)s?)$", re.I)
CATEGORY_PARAM = re.compile(r"^(?:cate(?:gory)?_?id|cat_?id|cid)$", re.I)
PARAM = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")


def message_of(data: Any) -> str | None:
    """The message a JSON answer carries: the first text under msg, message, error and the like, at its top or
    one level down ({"error": {"message": ...}})."""
    for node in (data, *(data.values() if isinstance(data, dict) else ())):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if str(key).lower() in MESSAGE_KEYS and isinstance(value, str) and value.strip():
                return " ".join(value.split())[:200]
    return None


def failed(message: str | None, status: int | None) -> bool:
    """Whether a JSON answer that holds no list is an error message: a 4xx or 5xx, or words that say it failed."""
    return bool(message) and ((status or 0) >= 400 or bool(ERROR_WORDS.search(message or "")))


def wanted(message: str | None) -> list[str]:
    """The parameters an error message says a call lacks, of those recon can fill: ["cate_id", "keyword"]."""
    if not message or not NEEDS.search(message):
        return []
    names = dict.fromkeys(PARAM.findall(message))
    return [n for n in names if KEYWORD_PARAM.match(n) or CATEGORY_PARAM.match(n)]


# a category's address, by its first segment: /category/eeprom/160112.html; not a brand's or a search's
CATEGORY_PATH = re.compile(
    r"^/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?(?:category|categories|cat|c|kategorie|kategoria|categoria|categorie)[/.]",
    re.I,
)


def fill_for(wants: list[str], part_number: str | None, listings: list[str]) -> dict[str, str] | None:
    """A value the run has for a parameter a call lacks: the product page's part number for a search word, read
    from its data; else, for a category's id, the last number in the address of a category page found to list
    products (/category/eeprom/160112.html), which is a guess. None for none."""
    for name in wants:
        if KEYWORD_PARAM.match(name) and part_number:
            return {name: part_number}
    category = None
    for url in listings:
        path = urlsplit(url).path
        numbers = re.findall(r"\d{2,}", path) if CATEGORY_PATH.match(path) else []
        if numbers:
            category = numbers[-1]
            break
    for name in wants:
        if CATEGORY_PARAM.match(name) and category:
            return {name: category}
    return None


def lists_to_ask(routes: list[dict[str, str]]) -> list[dict[str, str]]:
    """The routes to ask without the browser, best first: lists and searches whose method the code names as GET,
    with nothing to fill in and no word of a change of state or of a visitor's own; those that name products
    first, then a list."""
    fit = [
        r
        for r in routes
        if r["kind"] == "lists and search"
        and r["method"] == "GET"
        and "{}" not in r["route"]
        and not stateful(r["route"])
    ]
    return sorted(
        fit,
        key=lambda r: -2 * len(PRODUCT_WORDS.findall(r["route"])) - len(LIST_WORDS.findall(r["route"].split("?")[0])),
    )


# a helper that adds parameters to every call, against scrapers or to sign it: addAntiSpiderParams, signParams;
# the word is looked for, then the name around it. The word must start one of the name's own (a capital, a "_",
# the name's start): signParams is in assignParams too
HELPER = re.compile(r"anti_?spider|anti_?crawl|anti_?bot|spider_?param|sign_?param|encrypt_?param", re.I)
# what a function sets on its argument: t.v=..., t["v_"]=...
SETS = re.compile(r"""\b[A-Za-z_$][\w$]{0,10}\.([A-Za-z_$][\w$]{0,15})\s*=(?!=)|\[["']([\w$]{1,16})["']\]\s*=(?!=)""")
# or merges in: Object.assign(e||{},{v:t,v_:r,p:n}), {...e,v:t}
MERGED = re.compile(
    r"""Object\.assign\([^,()]{1,40},\s*\{([^{}]{0,300})\}"""
    r"""|\{\s*\.\.\.[\w$.?]{1,40}\s*,([^{}]{0,300})\}"""
)
# a key of an object literal's text, "v:t,v_:r" or the shorthand "v,v_"
LITERAL_KEY = re.compile(r"""(?:^|,)\s*["']?([A-Za-z_$][\w$]{0,15})["']?\s*(?=[:,]|$)""")
# where a name is defined, up to its body's "{": name(t){, name=function(t){, name=(t)=>{, name: t=>{
DEFINED = re.compile(
    r"""\s*(?:[:=]\s*(?:async\s*)?(?:function\b[^{]{0,80}|\([^)]{0,80}\)\s*=>\s*|[\w$]+\s*=>\s*)"""
    r"""|\([^)]{0,80}\)\s*)\{"""
)
HELPER_BODY = 2_000  # characters of a helper's body read for what it sets


def body_of(js: str, start: int) -> str:
    """A function's body, from past its "{" to the "}" that closes it, HELPER_BODY characters at most. Braces in
    its strings are counted too: a body cut short shows less, never more."""
    depth = 1
    for i in range(start, min(len(js), start + HELPER_BODY)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i]
    return js[start : start + HELPER_BODY]


def sets_in(body: str) -> list[str]:
    """The parameters a helper's body sets on its argument or merges into it."""
    found = [a or b for a, b in SETS.findall(body)]
    for a, b in MERGED.findall(body):
        found += LITERAL_KEY.findall(a or b)
    return [k for k in dict.fromkeys(found) if k not in ("length", "prototype")][:8]


def helpers_in(js: str) -> list[dict[str, Any]]:
    """The helpers a script defines that add parameters to calls: [{name, sets}], `sets` the parameters its body
    assigns, when it shows."""
    found: dict[str, list[str]] = {}

    def word(c: str) -> bool:
        return c.isalnum() or c in "_$"

    for match in HELPER.finditer(js):
        start, end = match.start(), match.end()
        while start > 0 and match.start() - start < 30 and word(js[start - 1]):
            start -= 1
        while end < len(js) and end - match.end() < 30 and word(js[end]):
            end += 1
        first = js[match.start()]
        if start != match.start() and not first.isupper() and js[match.start() - 1] not in "_$":
            continue  # inside a word of its own: assignParams
        name = js[start:end]
        if found.get(name):
            continue
        body = DEFINED.match(js, end)
        found[name] = sets_in(body_of(js, body.end())) if body else []
        if len(found) >= 3:
            break
    return [{"name": name, "sets": sets} for name, sets in found.items()]


# names no public DNS holds: a host of a private network
INTERNAL = re.compile(r"(?:^|\.)(?:localhost|local|internal|intranet|lan|corp|home\.arpa|svc|cluster\.local)$", re.I)


def internal_name(host: str) -> bool:
    """A host a site's servers reach and the public cannot: a private address, a name of one label or under
    .local, .internal and the like."""
    try:
        return not ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        return "." not in host or bool(INTERNAL.search(host))


def all_private(addresses: list[str]) -> bool:
    try:
        return bool(addresses) and all(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
    except ValueError:
        return False


async def resolve(host: str) -> dict[str, Any]:
    """`host` in the system's DNS: its addresses and canonical name (where its CNAMEs lead). OSError when the
    name has none."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM, flags=socket.AI_CANONNAME)
    names = [str(i[3]) for i in infos if i[3]]
    return {"addresses": sorted({str(i[4][0]) for i in infos}), "canonical": names[0] if names else None}

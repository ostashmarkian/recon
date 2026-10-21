"""What a page's own XHR and fetch calls answer, read for a scraper: a product list with its fields and its
paging, an HTML fragment of product links, or other data."""

import json
import re
from typing import Any
from urllib.parse import urlsplit

from .clients import cookie_names
from .pages import HREF, PRODUCT_HINT
from .state import product_like, signals_of

# what every browser sends: a call that carries more needs it, a token, a key or a marker
STANDARD = {
    "accept",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "dnt",
    "host",
    "origin",
    "pragma",
    "priority",
    "referer",
    "te",
    "upgrade-insecure-requests",
    "user-agent",
}
# sent again when a call is asked once more without the browser: none of them is a secret
REPLAYED = ("accept", "content-type", "x-requested-with")

# the keys that page through a list, near the top of the answer
PAGING = re.compile(
    r"^(?:total|total_?(?:count|items|results|pages)|count|nb_?(?:hits|pages)|pages?|has_?(?:more|next)"
    r"|next(?:_?page)?|offset|limit|per_?page|page_?size|cursor|end_?cursor)$",
    re.I,
)
DEPTH = 8  # levels of nesting looked into


def json_shape(data: Any) -> dict[str, Any]:
    """The largest list of objects in a JSON answer: where it sits, how many items, their keys, which of ids,
    names, prices and stock they carry; and the paging keys near the top. "products" when the list has ids or
    names, and prices or stock."""
    best: tuple[int, str, list[dict[str, Any]]] | None = None
    paging: list[str] = []
    stack: list[tuple[Any, str, int]] = [(data, "", 0)]
    while stack:  # a stack, not recursion: an answer nested a thousand deep is read all the same
        node, path, depth = stack.pop()
        if depth > DEPTH:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                key = str(key)
                if depth <= 3 and PAGING.match(key) and not isinstance(value, (dict, list)) and key not in paging:
                    paging.append(key)
                stack.append((value, f"{path}.{key}" if path else key, depth + 1))
        elif isinstance(node, list):
            items = [x for x in node if isinstance(x, dict)]
            if len(items) >= 2 and (best is None or len(items) > best[0]):
                best = (len(items), path or "(the answer)", items)
            stack.extend((x, f"{path}[]", depth + 1) for x in node[:3])
    if best is None:
        return {"kind": "data", "paging": paging[:6]}
    count, path, items = best
    keys = list(dict.fromkeys(str(k) for item in items[:5] for k in item))[:14]
    signals = signals_of(keys)
    return {
        "kind": "products" if product_like(count, signals) else "list",
        "path": path,
        "items": count,
        "keys": keys,
        "signals": signals,
        "paging": paging[:6],
    }


# what some APIs put before their JSON so a page cannot run it as a script
XSSI = (b")]}',", b")]}'", b"while(1);", b"for(;;);")


def as_json(body: bytes) -> tuple[bool, Any]:
    """(True, the data) when `body` is JSON, whatever its Content-Type says: an API can serve JSON as text/html.
    A BOM and an anti-XSSI prefix are skipped. (False, None) otherwise."""
    text = body.lstrip()
    if text.startswith(b"\xef\xbb\xbf"):
        text = text[3:].lstrip()
    for prefix in XSSI:
        if text.startswith(prefix):
            text = text[len(prefix) :].lstrip()
            break
    if text[:1] not in (b"{", b"["):
        return False, None
    try:
        return True, json.loads(text)
    except (ValueError, RecursionError):
        return False, None


def shape(body: bytes, kind: str) -> dict[str, Any]:
    """What one answer holds: a JSON shape (the body read, not its Content-Type), an HTML fragment's links and
    product links, or only its size."""
    is_json, data = as_json(body)
    if is_json:
        return json_shape(data)
    if "json" in kind:  # a bare string or number
        try:
            return json_shape(json.loads(body))
        except (ValueError, RecursionError):
            pass
    if "html" in kind or body.lstrip()[:1] == b"<":
        links = HREF.findall(body.decode("utf-8", "replace"))
        return {
            "kind": "html",
            "links": len(links),
            "product_links": sum(1 for h in links if PRODUCT_HINT.search(h)),
        }
    return {"kind": "other"}


def sent_needs(headers: dict[str, str]) -> list[str]:
    """What a page's call carried beyond what any browser sends: header names, never their values, and the
    names of the cookies it sent."""
    names = sorted(k.lower() for k in headers if k.lower() not in STANDARD and not k.lower().startswith("sec-"))
    cookie = next((v for k, v in headers.items() if k.lower() == "cookie"), "")
    return names + [f"cookie {c}" for c in cookie_names(cookie.split(";"))]


def replay_headers(headers: dict[str, str]) -> dict[str, str]:
    """The headers a call is asked again with: REPLAYED only, so no cookie and no token goes with it."""
    lowered = {k.lower(): v for k, v in headers.items()}
    return {k: lowered[k] for k in REPLAYED if k in lowered}


def operation(sent: str) -> str | None:
    """A GraphQL call's operationName, from what was posted."""
    try:
        data = json.loads(sent)
    except ValueError:
        return None
    name = data.get("operationName") if isinstance(data, dict) else None
    return str(name)[:60] if name else None


def call_record(call: dict[str, Any], host: str) -> dict[str, Any]:
    """One call a page made, without its body: method, address, answer, whether it is the site's own, and
    what it holds."""
    try:
        own = (urlsplit(call["url"]).hostname or "").removeprefix("www.").endswith(host.removeprefix("www."))
    except ValueError:
        own = False
    found = shape(call["body"], call["type"])
    kind = call["type"].split(";")[0].strip()
    return {
        "method": call["method"],
        "url": call["url"][:300],
        "status": call["status"],
        "type": kind,
        "bytes": len(call["body"]),
        "own": own,
        "operation": operation(call["sent"]) if call.get("sent") else None,
        "needs": sent_needs(call.get("headers") or {}),
        # JSON served as text/html: a scraper must parse it whatever the header says
        "json_as": kind if found["kind"] in ("products", "list", "data") and "json" not in kind else None,
        **found,
    }


def rank(record: dict[str, Any]) -> tuple[int, int, int]:
    """Product lists first, then other lists and fragments of product links, then the rest; the site's own first."""
    if record["kind"] == "products":
        kind = 0
    elif record["kind"] == "list" or (record["kind"] == "html" and record.get("product_links", 0) >= 3):
        kind = 1
    else:
        kind = 2
    return (kind, 0 if record["own"] else 1, -record.get("items", 0))

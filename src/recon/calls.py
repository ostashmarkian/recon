"""What a page's own XHR and fetch calls answer, read for a scraper: a product list with its fields and its
paging, an HTML fragment of product links, or other data."""

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

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
# the keys that say how many a list holds in all, near the top of the answer; "count" only when no other does, as
# some APIs count the page they give with it
TOTAL = re.compile(
    r"^(?:total|total_?(?:count|items|results|records|rows|num|hits|size)|result_?total|record_?count"
    r"|nb_?hits|num_?found|count)$",
    re.I,
)


def count_of(value: Any) -> int | None:
    """A count as an answer writes it: 413, "413", or {"value": 413} as Elasticsearch does; None for anything else."""
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit() and len(value) <= 15:
        return int(value)
    return None


def walk(data: Any) -> tuple[tuple[int, str, list[dict[str, Any]]] | None, list[str], int | None]:
    """A JSON answer read once: its largest list of objects (how many, where it sits, the items), the paging keys
    near the top, and the total near the top, by its own key."""
    best: tuple[int, str, list[dict[str, Any]]] | None = None
    paging: list[str] = []
    totals: list[tuple[int, bool, int]] = []  # (depth, a bare "count", the count)
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
                if depth <= 3 and TOTAL.match(key) and (n := count_of(value)) is not None:
                    totals.append((depth, key.lower() == "count", n))
                stack.append((value, f"{path}.{key}" if path else key, depth + 1))
        elif isinstance(node, list):
            items = [x for x in node if isinstance(x, dict)]
            if len(items) >= 2 and (best is None or len(items) > best[0]):
                best = (len(items), path or "(the answer)", items)
            stack.extend((x, f"{path}[]", depth + 1) for x in node[:3])
    total = min(totals, key=lambda t: (t[1], t[0]))[2] if totals else None
    return best, paging, total


def json_shape(data: Any) -> dict[str, Any]:
    """The largest list of objects in a JSON answer: where it sits, how many items, their keys, which of ids,
    names, prices and stock they carry; the paging keys near the top, and the total they give. "products" when
    the list has ids or names, and prices or stock."""
    best, paging, total = walk(data)
    counted = {"total": total} if total is not None else {}
    if best is None:
        return {"kind": "data", "paging": paging[:6], **counted}
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
        **counted,
    }


def list_at(data: Any, path: str) -> list[dict[str, Any]] | None:
    """The list of objects at `path` as json_shape() names it ("result.pageOfItems", "data[].rows", "(the answer)"),
    the first item taken where it goes through a list; None when the answer has nothing there. A page past the end
    holds an empty list where the first page held its items, which json_shape() does not call a list."""
    node = data
    if path != "(the answer)":
        for part in path.split("."):
            key, through = (part[:-2], True) if part.endswith("[]") else (part, False)
            node = node.get(key) if isinstance(node, dict) and key else node if not key else None
            if through:
                node = node[0] if isinstance(node, list) and node else None
            if node is None:
                return None
    return [x for x in node if isinstance(x, dict)] if isinstance(node, list) else None


def digest(items: list[dict[str, Any]]) -> str:
    """A list's first items in a few characters: two pages that give the same rows have the same digest."""
    return hashlib.sha1(json.dumps(items[:3], sort_keys=True, default=str).encode()).hexdigest()[:12]


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
        **({"unfinished": True} if call.get("unfinished") else {}),
        **({"after_click": True} if call.get("after_click") else {}),
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


# the parameters a list call pages with: how many a page holds, which page, or how many rows it skips
SIZE_KEY = re.compile(r"^(?:page_?size|per_?page|page_?limit|limit|size|rows|hits_?per_?page|psize)$", re.I)
PAGE_KEY = re.compile(r"^(?:page|page_?(?:no|num|number|index)|pn|current_?page|current)$", re.I)
OFFSET_KEY = re.compile(r"^(?:offset|start|from|skip)$", re.I)
PAGING_KEYS = (("size", SIZE_KEY), ("page", PAGE_KEY), ("offset", OFFSET_KEY))


def sent_as(call: dict[str, Any]) -> str:
    """Where a call carries its parameters: "query" for a GET, "json" or "form" for what a POST sends; "" when a POST
    sends something else."""
    if call["method"] == "GET":
        return "query"
    body = (call.get("sent") or "").strip()
    if body[:1] == "{":
        return "json"
    return "form" if "=" in body and body[:1] not in ("[", "<") else ""


def as_int(value: Any) -> int | None:
    """A whole number as a call sends it, 20 or "20"; None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() and len(value) <= 9 else None


def pairs(text: str) -> list[tuple[str, str]]:
    """A query string or a form body as (name, value) pairs, in order, repeated names kept."""
    return parse_qsl(text, keep_blank_values=True)


def paging_of(call: dict[str, Any]) -> dict[str, tuple[tuple[str, ...], int]]:
    """The call's paging parameters that hold a whole number: {"size" | "page" | "offset": (where, its value)}, where
    is the name, or the names down to it in a JSON body one level deep ({"page": {"size": 20}})."""
    how = sent_as(call)
    found: list[tuple[tuple[str, ...], Any]] = []
    if how == "query":
        found = [((k,), v) for k, v in pairs(urlsplit(call["url"]).query)]
    elif how == "form":
        found = [((k,), v) for k, v in pairs(call["sent"])]
    elif how == "json":
        _, data = as_json(call["sent"].encode())
        if isinstance(data, dict):
            for k, v in data.items():
                found.append(((str(k),), v))
                if isinstance(v, dict):
                    found += [((str(k), str(k2)), v2) for k2, v2 in v.items()]
    keys: dict[str, tuple[tuple[str, ...], int]] = {}
    for where, value in found:
        n = as_int(value)
        for name, pattern in PAGING_KEYS:
            if n is not None and name not in keys and pattern.match(where[-1]):
                keys[name] = (where, n)
    return keys


def paging_said(data: Any) -> dict[str, tuple[tuple[str, ...], int]]:
    """The page and the page size a JSON answer says it holds, near its top ({"page": 1, "pageSize": 25}), as
    paging_of() gives a call's: for a call that sends neither, the names to try sending."""
    keys: dict[str, tuple[tuple[str, ...], int]] = {}
    stack: list[tuple[Any, int]] = [(data, 0)]
    while stack:
        node, depth = stack.pop(0)
        if not isinstance(node, dict) or depth > 3:
            continue
        for key, value in node.items():
            n = as_int(value)
            for name, pattern in PAGING_KEYS[:2]:
                if n is not None and name not in keys and pattern.match(str(key)):
                    keys[name] = ((str(key),), n)
            if isinstance(value, dict):
                stack.append((value, depth + 1))
    return keys


def with_paging(call: dict[str, Any], changes: dict[tuple[str, ...], int]) -> dict[str, Any]:
    """The call with these paging parameters set, all else as it was sent: the query string or the form body
    rewritten pair by pair (one it does not send yet added at its end), a JSON body with each value of the type it
    had."""
    how = sent_as(call)
    if how in ("query", "form"):
        text = urlsplit(call["url"]).query if how == "query" else call["sent"]
        out = []
        done = set()
        for part in text.split("&") if text else []:
            name = parse_qsl(part, keep_blank_values=True)
            if name and (name[0][0],) in changes:
                part = urlencode({name[0][0]: changes[(name[0][0],)]})
                done.add((name[0][0],))
            out.append(part)
        out += [urlencode({where[-1]: n}) for where, n in changes.items() if where not in done and len(where) == 1]
        if how == "form":
            return {**call, "sent": "&".join(out)}
        return {**call, "url": urlsplit(call["url"])._replace(query="&".join(out)).geturl()}
    if how == "json":
        _, data = as_json(call["sent"].encode())
        for where, n in changes.items():
            node = data
            for k in where[:-1]:
                node = node[k]
            node[where[-1]] = str(n) if isinstance(node[where[-1]], str) else n
        return {**call, "sent": json.dumps(data, ensure_ascii=False)}
    return call

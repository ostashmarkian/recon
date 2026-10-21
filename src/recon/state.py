"""A page's own state, as its framework writes it into the HTML for the browser: Nuxt 3's __NUXT_DATA__ (devalue),
Next.js's __NEXT_DATA__, a plain window.__INITIAL_STATE__. Read for a scraper: the product lists it holds with the
counts beside them, and the product a page is about, its part number among its fields. A listing drawn on the
server carries its products here, and the pages fetch them by no XHR."""

import contextlib
import json
import re
from collections import deque
from typing import Any

from . import settings

# the keys of a list's items that make it a catalogue, snake_case or camelCase: id, variant_id, VariantId, sku
IDS = re.compile(
    r"^(?:id|sku|mpn|code|handle|slug|ean|upc|gtin\d*)$|_(?:id|key|code|sku)$|sku|mpn|gtin|part_?n(?:o|umber)", re.I
)
CAMEL_IDS = re.compile(r"[a-z](?:Id|ID|Key|Code|Sku)$")
NAMES = re.compile(r"name|title|^label$", re.I)
# a price's key: price, amount, cost, or a currency's code as a key of its own (usd, unit_usd)
PRICES = re.compile(r"price|amount|cost|(?:^|_)(?:usd|eur|gbp|cny|rmb|jpy)(?:_|$)", re.I)
STOCKS = re.compile(r"stock|qty|quantity|inventory|availab", re.I)
# a stock's own count: stock, stock_num, qty, available_qty; not a flag (in_stock 1, is_stock) or an order's step
# (min_qty, moq, mult)
STOCK_COUNT = re.compile(
    r"^(?:stock|qty|quantity|inventory|available|availability)(?:_?(?:num|qty|quantity|count|amount|level|total))?$"
    r"|(?:stock|available|inventory)_?(?:num|qty|quantity|count|amount|level|total)$",
    re.I,
)
NOT_STOCK = re.compile(r"^(?:in|is|has)(?:_|[A-Z])|(?i:min|max|moq|mpq|mult|step|pack|status|state|flag|type)")
BRANDS = re.compile(r"brand|maker|manufacturer|vendor|mfr|mfg", re.I)
# a part number's key: mpn, partNumber, mfr_part_no, manufacturerPartNumber; and pro_sno, std_pro_sno, the maker's
# part number as some Chinese distributors' sites name it ("product serial number")
MPN_KEY = re.compile(
    r"^(?:mpn|(?:std_?)?pro_?sno|part_?(?:no|num|number)|(?:mfr|mfg|manufacturer)_?(?:part_?)?(?:no|num|number|pn)"
    r"|manufacturer_?part)$",
    re.I,
)
# the counts beside a list: resultTotal, pageSize, totalCount, total_pages, pageNum
COUNTS = re.compile(
    r"(?:total|count|size|pages|hits)$|^(?:total|count|page|page_?(?:no|num|index|size)|per_?page|current_?page)$",
    re.I,
)


def short(value: Any, most: int = 60) -> str | None:
    return None if value in (None, "") else " ".join(str(value).split())[:most]


def signals_of(keys: list[str]) -> list[str]:
    """Which of ids, names, prices and stock the keys of a list's items carry; a part number counts as an id."""
    return [
        name
        for name, pattern in (("ids", IDS), ("names", NAMES), ("prices", PRICES), ("stock", STOCKS))
        if any(pattern.search(k) or (name == "ids" and (CAMEL_IDS.search(k) or MPN_KEY.match(k))) for k in keys)
    ]


def product_like(count: int, signals: list[str]) -> bool:
    """A list of products: three items or more, with ids or names, and prices or stock."""
    return count >= 3 and bool({"ids", "names"} & set(signals)) and bool({"prices", "stock"} & set(signals))


# devalue's numbers for what JSON cannot hold: undefined, a hole, NaN, Infinity, -Infinity, -0
SPECIAL = {-1: None, -2: None, -3: None, -4: None, -5: None, -6: 0}
AS_TEXT = {"Date", "RegExp", "BigInt", "URL", "URLSearchParams"}


def unflatten(values: Any) -> Any:
    """devalue's flat array (Nuxt 3's __NUXT_DATA__) back to its value. Each value is an index into the array;
    ["Reactive", i], ["ShallowReactive", i], ["Ref", i] and Nuxt's other wrappers read as the value they wrap; a Set
    reads as a list, a Map as a dict, a Date or a RegExp as its text. Read by a stack, each index once, so shared and
    circular values come back shared, and STATE_VALUES values at most."""
    if not isinstance(values, list) or not values:
        return None
    size = len(values)
    done: dict[int, Any] = {}
    todo: list[tuple[Any, str, Any]] = []  # (a container made, how it is filled, what fills it)

    def node(i: Any) -> Any:
        """The value at index `i`: a container is made empty and filled later, from `todo`."""
        wrappers: list[int] = []
        value: Any = None
        while True:
            if isinstance(i, bool) or not isinstance(i, int):
                break
            if not 0 <= i < size:
                value = SPECIAL.get(i)
                break
            if i in done:
                value = done[i]
                break
            raw = values[i]
            if isinstance(raw, list) and raw and isinstance(raw[0], str):
                tag = raw[0]
                if tag in AS_TEXT:
                    value = str(raw[1]) if len(raw) > 1 else None
                elif tag == "Set":
                    value = []
                    todo.append((value, "list", raw[1:]))
                elif tag in ("Map", "null"):  # "null": an object of no prototype, its keys written out
                    value = {}
                    todo.append((value, "pairs" if tag == "Map" else "named", raw[1:]))
                elif len(raw) == 2 and i not in wrappers:  # a wrapper: the value it wraps
                    wrappers.append(i)
                    i = raw[1]
                    continue
            elif isinstance(raw, list):
                value = []
                todo.append((value, "list", raw))
            elif isinstance(raw, dict):
                value = {}
                todo.append((value, "dict", raw))
            else:
                value = raw
            done[i] = value
            break
        for w in wrappers:
            done[w] = value
        return value

    root = node(0)
    spent = 0
    while todo and spent < settings.STATE_VALUES:
        made, how, raw = todo.pop()
        spent += len(raw)
        if how == "list":
            made.extend(node(x) for x in raw if x != -2)  # -2: a hole
        elif how == "dict":
            for key, x in raw.items():
                made[str(key)] = node(x)
        else:
            for key, x in zip(raw[0::2], raw[1::2], strict=False):
                if how == "pairs":  # a Map's key is a value too
                    key = node(key)
                    key = key if isinstance(key, (str, int, float)) else "#"
                made[str(key)] = node(x)
    return root


def script_text(html: str, marker: str) -> str | None:
    """The text of the first <script> whose opening tag holds `marker` (its id), found by scanning: the first 20
    times the marker shows are looked at, each within 1,000 characters of its tag, so a hostile page stays linear."""
    at = 0
    for _ in range(20):
        at = html.find(marker, at)
        if at < 0:
            return None
        opened = html.rfind("<", max(0, at - 1_000), at)
        start = html.find(">", at, at + 1_000)
        if opened >= 0 and start >= 0 and html[opened : opened + 7].lower() == "<script" and ">" not in html[opened:at]:
            end = html.find("</script", start)
            return html[start + 1 : end if end >= 0 else len(html)]
        at += len(marker)
    return None


def states_of(html: str) -> list[tuple[str, Any]]:
    """(format, the state read) of each state the page carries."""
    found: list[tuple[str, Any]] = []
    for name, marker in (("Nuxt 3 __NUXT_DATA__", "__NUXT_DATA__"), ("Next.js __NEXT_DATA__", "__NEXT_DATA__")):
        text = script_text(html, marker)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            continue
        found.append((name, unflatten(data) if marker == "__NUXT_DATA__" else data))
    at = html.find("window.__INITIAL_STATE__")
    if at >= 0:  # window.__INITIAL_STATE__ = {...}; when what follows is JSON
        start, end = html.find("=", at), html.find("</script", at)
        end = end if end >= 0 else len(html)
        if 0 <= start < end:
            with contextlib.suppress(ValueError, RecursionError):
                found.append(("window.__INITIAL_STATE__", json.loads(html[start + 1 : end].strip().rstrip(";"))))
    return found


def path_of(path: str, key: str) -> str:
    """`path` and `key`, as a scraper writes it: data.items, data["spu-detail-12"]."""
    if key.isidentifier():
        return f"{path}.{key}" if path else key
    return f'{path}["{key}"]'


def scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool) and value != ""


def is_count(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, str) and value.isdigit())


def list_of(value: list[Any], path: str, parent: dict[str, Any] | None) -> dict[str, Any] | None:
    """A list of products: where it sits, how many items, their keys, the part number's key and the counts beside it
    (resultTotal, pageSize); None for any other list."""
    items = [x for x in value if isinstance(x, dict)]
    keys = list(dict.fromkeys(str(k) for item in items[:5] for k in item))[:14]
    signals = signals_of(keys)
    mpn = next((k for k in keys if MPN_KEY.match(k)), None)
    if not (product_like(len(items), signals) or (mpn and len(items) >= 3)):  # a part number marks a catalogue
        return None
    counts = {str(k): v for k, v in (parent or {}).items() if COUNTS.search(str(k)) and is_count(v)}
    return {
        "path": path or "(the state)",
        "items": len(items),
        "keys": keys,
        "signals": signals,
        "mpn_key": mpn,
        "counts": dict(list(counts.items())[:4]),
    }


def stock_of(node: dict[str, Any]) -> str | None:
    """A product's stock: a stock's own count first (stock 599, not in_stock 1 before it), then any other stock
    key's count, then its text ("InStock"); never a flag or an order's step."""
    found = [
        (str(k), v)
        for k, v in node.items()
        if STOCKS.search(str(k)) and not NOT_STOCK.search(str(k)) and not MPN_KEY.match(str(k)) and scalar(v)
    ]
    for rank in range(3):  # a stock of 0 is a stock: picked by rank, not by truth
        for k, v in found:
            if rank == 2 or (is_count(v) and (rank == 1 or STOCK_COUNT.search(k))):
                return short(v)
    return None


def product_of(node: dict[str, Any], path: str) -> dict[str, Any] | None:
    """The product an object is: a part number, and a name, a price or stock beside it; None otherwise."""
    mpn = next((str(k) for k, v in node.items() if MPN_KEY.match(str(k)) and scalar(v) and short(v)), None)
    if mpn is None:
        return None

    def first(pattern: re.Pattern[str], but: re.Pattern[str] | None = None) -> str | None:
        return next(
            (
                short(v)
                for k, v in node.items()
                if pattern.search(str(k)) and not MPN_KEY.match(str(k)) and not (but and but.search(str(k)))
                if scalar(v)
            ),
            None,
        )

    fields = {
        "mpn": short(node[mpn]),
        "name": first(NAMES, BRANDS),
        "brand": first(BRANDS),
        "price": first(PRICES),
        "stock": stock_of(node),
    }
    if not any(fields[k] for k in ("name", "price", "stock")):
        return None
    return {"path": path or "(the state)", "mpn_key": mpn, "fields": {k: v for k, v in fields.items() if v}}


def state_findings(data: Any) -> dict[str, Any]:
    """The product lists of a state, and the product it is about: the shallowest object outside any list that has
    a part number. Read breadth first, by a queue, each object once and STATE_DEPTH levels deep at most; of a
    list, its first items only."""
    lists: list[dict[str, Any]] = []
    product: dict[str, Any] | None = None
    if isinstance(data, list):
        found = list_of(data, "", None)
        lists += [found] if found else []
    seen: set[int] = set()
    listed: set[int] = set()  # a list the state names twice is reported once
    queue: deque[tuple[Any, str, int, bool]] = deque([(data, "", 0, False)])
    while queue:
        node, path, depth, in_list = queue.popleft()
        if depth > settings.STATE_DEPTH or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, dict):
            if product is None and not in_list:
                product = product_of(node, path)
            for key, value in node.items():
                if isinstance(value, list) and id(value) not in listed:
                    listed.add(id(value))
                    found = list_of(value, path_of(path, str(key)), node)
                    lists += [found] if found else []
                if isinstance(value, (dict, list)):
                    queue.append((value, path_of(path, str(key)), depth + 1, in_list))
        elif isinstance(node, list):
            queue.extend((item, f"{path}[]", depth + 1, True) for item in node[:3] if isinstance(item, (dict, list)))
    lists.sort(key=lambda found: found["items"], reverse=True)
    return {"lists": lists[:5], "product": product}


def read_state(html: str) -> dict[str, Any] | None:
    """What the page's state holds for a scraper: its format, its product lists and the product it is about;
    None when the page carries no state recon reads."""
    states = states_of(html)
    if not states:
        return None
    read = [(name, state_findings(data)) for name, data in states]
    name, found = next(((n, f) for n, f in read if f["lists"] or f["product"]), read[0])
    return {"format": name, **found}

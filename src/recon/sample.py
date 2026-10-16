"""A sample of product pages: what share carries each field, and the traps a
scraper falls into in them."""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from .clients import Answer
from .pages import product_data, visible_text

# What a sample of product pages can show wrong in a field
SAMPLE_FIELDS = ("mpn", "sku", "gtin", "brand", "price", "currency", "availability", "inventory")


GTIN_LIKE = re.compile(r"^\d{8}$|^\d{12,14}$")


EXCEL = re.compile(r"^\d(?:[.,]\d+)?E\+?\d+$", re.I)


PLACEHOLDER = re.compile(r"^(?:n/?a|none|null|nil|-+|0|tbd|unknown|\?+)$", re.I)


LADDER_WORDS = re.compile(
    r"\b(?:price breaks?|quantity discounts?|volume pricing|tier(?:ed)? pric\w*|bulk pricing|Staffelpreis\w*"
    r"|Mengenrabatt\w*|množstevní slev\w*|rabat ilościowy|precio por cantidad|оптов\w+ цін\w*|оптов\w+ цен\w*)"
    r"|数量割引|수량 할인",
    re.I,
)


QTY_STEP = re.compile(r"(?<![\w.,])(\d{1,6})\s*\+(?=\s)")  # "10+ 100+ 1000+" in a price table


# a price table's quantity column read as text: "Qty 2 10 25+ Unit Price ..."
QTY_ROW = re.compile(
    r"\b(?:qty|quantity|menge|množství|ilość|cantidad|кількість|количество)\b\s*:?((?:\s+\d[\d,.]*\+?){3,})", re.I
)


STOCK_COUNT = re.compile(
    r"\b(?:in stock|stock|skladem|na stanie|auf Lager|en stock|available|disponible)\b\D{0,20}?"
    r"(\d[\d,. ]{0,9}\d|\d)\s*(\+)?",
    re.I,
)


def page_record(a: Answer) -> dict[str, Any]:
    """One product page's fields for the sample: JSON-LD first, microdata
    after; the stock number its words show; a hint of a price ladder."""
    data = product_data(a)
    ld, md = data["jsonld"], data["microdata"]
    gtin = next((v for k, v in md.items() if k.lower().startswith("gtin")), None)
    fields = {
        "mpn": ld.get("mpn") or md.get("mpn"),
        "sku": ld.get("sku") or md.get("sku"),
        "gtin": ld.get("gtin") or gtin,
        "brand": ld.get("brand") or md.get("brand"),
        "price": ld.get("price") or md.get("price"),
        "currency": ld.get("currency") or md.get("priceCurrency"),
        "availability": ld.get("availability") or md.get("availability"),
        "inventory": ld.get("inventory") or md.get("inventoryLevel"),
    }
    words = visible_text(a.head)
    count = STOCK_COUNT.search(words)
    steps = {int(s) for s in QTY_STEP.findall(words)}
    rows = [{n.rstrip("+") for n in found.group(1).split()} for found in QTY_ROW.finditer(words)]
    ladder = bool(
        LADDER_WORDS.search(words)
        or len(steps) >= 3
        or any(len(r) >= 3 for r in rows)
        or (ld.get("offers") or 0) > 1
        or "eligibleQuantity" in a.head
    )
    return {
        "url": a.url,
        "fields": fields,
        "vat_included": ld.get("vat_included"),
        "labels": sorted(data["labels"]),
        "stock_words": (count.group(1).replace(" ", "") + (count.group(2) or "")) if count else None,
        "ladder": ladder,
    }


def sample_findings(records: list[dict[str, Any]]) -> dict[str, Any]:
    """What the product pages read show together: each field's share, and the traps."""
    n = len(records)
    coverage = {k: sum(1 for r in records if r["fields"].get(k)) for k in SAMPLE_FIELDS}
    mpns = [r["fields"].get("mpn") for r in records]
    traps = []

    def trap(found: list[Any], said: Callable[[list[Any]], str]) -> None:
        if found:
            traps.append(said(found))

    trap(
        [r for r in records if r["fields"].get("mpn") and r["fields"]["mpn"] == r["fields"].get("sku")],
        lambda f: f"the MPN equals the SKU on {len(f)} of {n}: maybe the shop's own code",
    )
    trap(
        [m for m in mpns if m and GTIN_LIKE.match(m)],
        lambda f: f"an MPN of 8 or 12-14 digits on {len(f)} of {n} (a GTIN?): `{f[0]}`",
    )
    trap([m for m in mpns if m and EXCEL.match(m)], lambda f: f"Excel notation as an MPN: `{f[0]}`")
    trap([m for m in mpns if m and PLACEHOLDER.match(m)], lambda f: f"a placeholder as an MPN: `{f[0]}`")
    trap(
        [m for m, c in Counter(m for m in mpns if m).items() if c > 1],
        lambda f: f"one MPN on several products: `{f[0]}`",
    )
    trap(
        [r for r in records if not r["fields"].get("mpn") and "part number" in r["labels"]],
        lambda f: f"a part number in the page's words but not in its data on {len(f)} of {n}",
    )
    stock = [r["fields"].get("inventory") or r["stock_words"] for r in records]
    shown = [s for s in stock if s]
    if len(shown) >= 3 and len(set(shown)) == 1:
        traps.append(f"the same stock `{shown[0]}` on all {len(shown)} pages showing one: a placeholder or a cap?")
    trap([s for s in shown if str(s).endswith("+")], lambda f: f"stock shown capped (`{f[0]}`) on {len(f)} of {n}")
    vats = Counter(str(r["vat_included"]) for r in records if r["vat_included"] is not None)
    return {
        "read": n,
        "coverage": coverage,
        "traps": traps,
        "currencies": sorted({r["fields"]["currency"] for r in records if r["fields"].get("currency")}),
        "vat_included": dict(vats),
        "ladder": sum(r["ladder"] for r in records),
        "stock_numbers": len(shown),
        "rows": [
            {
                "url": r["url"],
                **{k: r["fields"].get(k) for k in ("mpn", "sku", "price", "currency")},
                "stock": r["fields"].get("inventory") or r["stock_words"],
                "ladder": r["ladder"],
            }
            for r in records
        ],
    }

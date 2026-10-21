"""A page's own state: Nuxt 3's __NUXT_DATA__ (devalue), Next.js's __NEXT_DATA__, window.__INITIAL_STATE__."""

import json
import time

from fakes import NuxtSite, Wrap, devalue, nuxt_item, nuxt_page

from recon import settings
from recon.state import read_state, state_findings, unflatten


def test_devalue_wrappers_and_types() -> None:
    flat = [
        ["ShallowReactive", 1],
        {"data": 2, "when": 5, "seen": 6, "map": 8, "gone": -1, "list": 10},
        ["Reactive", 3],
        {"name": 4},
        "Part 1",
        ["Date", "2026-10-21T00:00:00.000Z"],
        ["Set", 7],
        "a",
        ["Map", 7, 4],
        "unused",
        [4, -2, 7],
    ]
    assert unflatten(flat) == {
        "data": {"name": "Part 1"},
        "when": "2026-10-21T00:00:00.000Z",
        "seen": ["a"],
        "map": {"a": "Part 1"},
        "gone": None,
        "list": ["Part 1", "a"],
    }


def test_devalue_shared_and_circular_values_come_back_shared() -> None:
    flat = [{"a": 1, "b": 1}, {"self": 0, "x": 2}, 3]
    got = unflatten(flat)
    assert got["a"] is got["b"] and got["a"]["self"] is got
    assert unflatten([["Ref", 1], ["Ref", 0]]) is None, "two wrappers wrapping each other"
    assert unflatten("not a list") is None and unflatten([]) is None


def test_devalue_deep_and_long_is_read_without_recursion() -> None:
    deep: list = [{"next": i + 1} for i in range(50_000)] + ["end"]
    got = unflatten(deep)
    for _ in range(100):
        got = got["next"]
    assert isinstance(got, dict), "50,000 levels read by a stack"


def test_devalue_stops_at_its_budget(monkeypatch) -> None:
    monkeypatch.setattr(settings, "STATE_VALUES", 10)
    flat = [list(range(1, 1001)), *range(1000)]
    began = time.monotonic()
    got = unflatten(flat)
    assert len(got) == 1000 and time.monotonic() - began < 1.0


def test_a_listing_state_holds_its_products_and_counts() -> None:
    site = NuxtSite()
    html = site.listing_page("/category/usb/070403.html", 1)
    state = read_state(html)
    assert state is not None and state["format"] == "Nuxt 3 __NUXT_DATA__"
    [found] = state["lists"]
    assert found == {
        "path": 'data["third-cate-/category/usb/070403.html"].pageOfItems',
        "items": 25,
        "keys": ["spu_id", "pro_sno", "std_pro_sno", "goods_name", "brand_name", "price", "stock_num"],
        "signals": ["ids", "names", "prices", "stock"],
        "mpn_key": "pro_sno",
        "counts": {"resultTotal": 413, "pageSize": 25},
    }
    assert state["product"] is None, "the items are in a list: none is the page's product"


def test_a_product_state_holds_its_part_number() -> None:
    state = read_state(NuxtSite().product_page(3))
    assert state is not None
    assert state["product"] == {
        "path": 'data["spu-detail-23120133"].goodsDetail',
        "mpn_key": "pro_sno",
        "fields": {"mpn": "MPN-3", "name": "ACME MPN-3", "brand": "ACME", "price": "0.50", "stock": "103"},
    }


def test_next_data_and_initial_state() -> None:
    items = [{"id": n, "name": f"P{n}", "price": 1.5} for n in range(4)]
    next_page = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"products": items, "totalCount": 120}}, "page": "/c/[slug]"})
        + "</script>"
    )
    state = read_state(next_page)
    assert state is not None and state["format"] == "Next.js __NEXT_DATA__"
    assert (state["lists"][0]["path"], state["lists"][0]["counts"]) == ("props.pageProps.products", {"totalCount": 120})
    plain = f"<script>window.__INITIAL_STATE__ = {json.dumps({'item': {'mpn': 'X-1', 'title': 'x'}})};</script>"
    held = read_state(plain)
    assert held is not None and held["product"]["fields"] == {"mpn": "X-1", "name": "x"}


def test_what_is_no_product_and_no_state() -> None:
    assert read_state("<html><script>var a = 1;</script></html>") is None
    menu = {"menu": [{"label": "Home"}, {"label": "Shop"}, {"label": "Blog"}], "q": {"mpn": ""}}
    assert state_findings(menu) == {"lists": [], "product": None}, "names only, and an empty part number"
    assert read_state('<script id="__NUXT_DATA__">[{"x" broken</script>') is None


def test_the_fakes_flatten_as_nuxt_does() -> None:
    """The test helper itself: what it writes reads back as it was."""
    value = {"data": Wrap("ShallowReactive", {"a": [nuxt_item(1)]}), "once": {"x"}}
    assert unflatten(json.loads(devalue(value))) == {"data": {"a": [nuxt_item(1)]}, "once": ["x"]}
    assert "__NUXT_DATA__" in nuxt_page("t", "", {})


def test_a_list_named_twice_is_reported_once() -> None:
    shared = [nuxt_item(n) for n in range(4)]
    found = state_findings({"data": {"items": shared}, "cache": {"items": shared}})
    assert [x["path"] for x in found["lists"]] == ["data.items"]


def test_the_makers_name_and_a_price_under_a_currency() -> None:
    """A goodsDetail as a parts distributor's state holds it: std_mfr_name is the maker's, usd the price."""
    held = state_findings(
        {"goodsDetail": {"pro_sno": "M24512", "std_mfr_name": "ST", "goods_title": "EEPROM", "usd": 0.38}}
    )
    assert held["product"]["fields"] == {"mpn": "M24512", "name": "EEPROM", "brand": "ST", "price": "0.38"}


def test_the_stock_is_a_count_not_a_flag() -> None:
    """A goodsDetail with in_stock 1 before stock 599: the count, not the flag; nor an order's step (moq)."""
    detail = {"pro_sno": "M24512", "in_stock": 1, "moq": 1, "mult": 1, "stock": 599, "usd": 0.38}
    assert state_findings({"goodsDetail": detail})["product"]["fields"]["stock"] == "599"
    none_left = {"pro_sno": "X1", "isStock": 1, "min_qty": 5, "stock_num": 0, "price": 1}
    assert state_findings({"d": none_left})["product"]["fields"]["stock"] == "0", "a stock of 0 is a stock"
    flag = {"pro_sno": "X1", "in_stock": 1, "price": 1}
    assert "stock" not in state_findings({"d": flag})["product"]["fields"], "a flag is no stock"
    said = {"pro_sno": "X1", "availability": "InStock", "price": 1}
    assert state_findings({"d": said})["product"]["fields"]["stock"] == "InStock"

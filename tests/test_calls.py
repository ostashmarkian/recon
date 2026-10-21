"""What a page's own calls answer: product lists, paging, fragments, GraphQL operations."""

import json

from fakes import BASE

from recon.browser import TRACKERS
from recon.calls import as_json, call_record, json_shape, operation, rank, replay_headers, sent_needs, shape


def items(n: int, **extra: object) -> list[dict[str, object]]:
    return [{"id": i, "title": f"Part {i}", **extra} for i in range(n)]


def test_a_product_list_with_its_paging() -> None:
    got = json_shape({"products": items(24, price="1.50", inventory_quantity=4), "total": 40, "page": 1})
    assert (got["kind"], got["path"], got["items"]) == ("products", "products", 24)
    assert got["signals"] == ["ids", "names", "prices", "stock"]
    assert got["paging"] == ["total", "page"]


def test_a_list_nested_in_graphql_and_algolia() -> None:
    graphql = {"data": {"products": {"items": items(12, price_range={"min": 1}), "total_count": 300}}}
    assert (json_shape(graphql)["path"], json_shape(graphql)["kind"]) == ("data.products.items", "products")
    assert json_shape(graphql)["paging"] == ["total_count"]
    algolia = {"results": [{"hits": [{"objectID": "a", "name": "x"}] * 5, "nbHits": 120, "page": 0}]}
    assert (json_shape(algolia)["path"], json_shape(algolia)["kind"]) == ("results[].hits", "list")
    assert json_shape(algolia)["paging"] == ["nbHits", "page"]


def test_camel_case_keys() -> None:
    """A shop's own API in camelCase: VariantId, commonName, priceWithVat, Availabilities."""
    rows = [{"VariantId": n, "commonName": "LED", "priceWithVat": 9.9, "Availabilities": []} for n in range(16)]
    got = json_shape(rows)
    assert (got["kind"], got["signals"]) == ("products", ["ids", "names", "prices", "stock"])


def test_trackers_and_consent_are_left_out() -> None:
    for noise in (
        "https://www.google-analytics.com/g/collect?v=2",
        "https://www.gme.cz/api/cookies-consent/get-all-cookies",
        "https://consent.cookiebot.com/uc.js",
    ):
        assert TRACKERS.search(noise), noise
    assert not TRACKERS.search("https://www.gme.cz/api/product/get-availabilities")


def test_what_a_call_needs_by_name_only() -> None:
    sent = {
        "Accept": "application/json",
        "User-Agent": "Chrome",
        "sec-fetch-mode": "cors",
        "Authorization": "Bearer eyJ-secret",
        "X-CSRF-Token": "t0k3n",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": "sid=abc; basket=7",
    }
    assert sent_needs(sent) == ["authorization", "x-csrf-token", "x-requested-with", "cookie sid", "cookie basket"]
    assert replay_headers(sent) == {"accept": "application/json", "x-requested-with": "XMLHttpRequest"}


def test_lists_that_are_no_catalogue() -> None:
    menu = {"menu": [{"label": "Home", "href": "/"}, {"label": "Shop", "href": "/shop"}, {"label": "Blog"}]}
    assert json_shape(menu)["kind"] == "list", "names but no prices or stock"
    assert json_shape({"user": {"logged_in": False}})["kind"] == "data"


def test_a_deep_answer_is_read_without_recursion() -> None:
    deep: object = items(3, price=1)
    for _ in range(5000):
        deep = {"a": deep}
    assert json_shape(deep)["kind"] == "data", "past DEPTH levels the list is not reached, and nothing breaks"


def test_shapes_of_other_answers() -> None:
    fragment = "".join(f'<a href="/product/{n}/">p</a>' for n in range(6)).encode() + b'<a href="/about/">a</a>'
    assert shape(fragment, "text/html") == {"kind": "html", "links": 7, "product_links": 6}
    assert shape(b"not json {", "application/json")["kind"] == "other"
    assert shape(b"\x89PNG", "image/png") == {"kind": "other"}


def test_a_graphql_operation_and_a_record() -> None:
    assert operation(json.dumps({"operationName": "ProductList", "query": "{}"})) == "ProductList"
    assert operation("a=1") is None
    call = {
        "method": "POST",
        "url": "https://api.shop.test/graphql",
        "status": 200,
        "type": "application/json; charset=utf-8",
        "sent": '{"operationName":"ProductList"}',
        "body": json.dumps({"data": {"products": items(5, price=1)}}).encode(),
    }
    record = call_record(call, "www.shop.test")
    assert (record["own"], record["type"], record["operation"], record["kind"]) == (
        True,
        "application/json",
        "ProductList",
        "products",
    )
    assert "body" not in record
    third = call_record({**call, "url": "https://abc-dsn.algolia.net/1/indexes"}, "shop.test")
    assert third["own"] is False


def test_product_lists_rank_first() -> None:
    data = call_record({"method": "GET", "url": f"{BASE}/a", "status": 200, "type": "", "body": b"{}"}, "shop.test")
    lst = call_record(
        {
            "method": "GET",
            "url": f"{BASE}/b",
            "status": 200,
            "type": "",
            "body": json.dumps(items(4, price=1)).encode(),
        },
        "shop.test",
    )
    assert sorted([data, lst], key=rank) == [lst, data]


def test_json_is_read_from_the_body_not_its_type() -> None:
    """A shop's API serves JSON as text/html; others put an anti-XSSI prefix or a BOM before it."""
    listed = json.dumps({"code": 0, "result": {"pageOfItems": items(25, price=1, stock_num=3)}}).encode()
    assert shape(listed, "text/html; charset=UTF-8")["kind"] == "products"
    assert as_json(b")]}',\n" + listed)[0] and as_json(b"\xef\xbb\xbf" + listed)[0]
    assert as_json(b"<html>{}</html>") == (False, None) and as_json(b"{broken") == (False, None)
    call = {"method": "GET", "url": f"{BASE}/x", "status": 200, "type": "text/html; charset=UTF-8", "body": listed}
    assert call_record(call, "shop.test")["json_as"] == "text/html"
    typed = call_record({**call, "type": "application/json"}, "shop.test")
    assert typed["json_as"] is None

"""platforms_of(), api_request(), api_says(): a platform and its open API."""

from pathlib import Path

import pytest
from fakes import BASE, HOME

from recon.clients import Answer
from recon.notes import read_notes
from recon.platforms import api_request, api_says, platforms_of


def test_platforms_stack_generator_and_a_note(tmp_path: Path) -> None:
    (tmp_path / "platforms").mkdir()
    (tmp_path / "platforms" / "WooCommerce store — where to start.md").write_text("x", encoding="utf-8")
    home = Answer("u", 200, {"x-powered-by": "PHP/8.1"}, ("PHPSESSID",), HOME.encode())
    platforms, stacks, generator = platforms_of(home, "", read_notes(tmp_path))
    assert [(name, note) for name, _, note in platforms] == [
        ("WooCommerce", "WooCommerce store — where to start"),
        ("WordPress", None),
    ]
    assert [name for name, _ in stacks] == ["PHP"]
    assert generator == "WooCommerce 9.1"


def test_image_path_is_no_magento_marker() -> None:
    assert platforms_of(Answer("u", 200, {}, (), b"<img src='/image/x.png'>"))[0] == []


SAYS = [
    (
        "OpenCart's counter",
        "OpenCart",
        Answer("u", 200, {}, (), b"<div>Showing 1 to 1 of 18217 (18217 Pages)</div>"),
        "the empty search counts 18217",
    ),
    (
        "Magento's total",
        "Magento 2",
        Answer("u", 200, {}, (), b'{"data":{"products":{"total_count":8601,"items":[{"sku":"A-1"}]}}}'),
        "total_count 8601; a product has sku 'A-1'",
    ),
    (
        "BigCommerce's product",
        "BigCommerce",
        Answer("u", 200, {}, (), b'{"data":{"site":{"products":{"edges":[{"node":{"sku":"S","mpn":"M"}}]}}}}'),
        "storefront GraphQL open; a product has sku 'S', mpn 'M'",
    ),
    (
        "GraphQL errors",
        "Magento 2",
        Answer("u", 200, {}, (), b'{"errors":[{"message":"Minimum length"}]}'),
        "errors: Minimum length",
    ),
    (
        "Shopify",
        "Shopify",
        Answer("u", 200, {}, (), b'{"products":[{"variants":[{"sku":"X","barcode":""}]}]}'),
        "open; a variant has sku 'X', barcode ''",
    ),
    ("not JSON", "Shopify", Answer("u", 200, {}, (), b"<html>"), "not JSON"),
    ("another shape", "Magento 2", Answer("u", 200, {}, (), b'{"data":null}'), "an answer of another shape"),
    ("not a 200", "Shopify", Answer("u", 401), ""),
]


@pytest.mark.parametrize(("platform", "answer", "said"), [pytest.param(p, a, s, id=n) for n, p, a, s in SAYS])
def test_api_says(platform: str, answer: Answer, said: str) -> None:
    assert api_says(platform, answer) == said


def test_bigcommerce_asks_with_the_pages_token() -> None:
    token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.abc.def"
    asked = api_request("BigCommerce", BASE, f'"authorization":"Bearer {token}"')
    assert asked is not None
    method, url, headers, _ = asked
    assert (method, url, headers["Authorization"]) == ("POST", f"{BASE}/graphql", f"Bearer {token}")
    assert api_request("BigCommerce", BASE, "<html>") is None

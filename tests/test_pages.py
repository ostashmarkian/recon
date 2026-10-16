"""Reading pages: sitemaps, product data, made-up addresses, listings, freshness, rendering."""

import gzip

import pytest
from fakes import BASE, PRODUCT, ld, page, sitemap_index, urlset

from recon import settings
from recon.clients import Answer
from recon.pages import (
    HREF,
    PRODUCT_HINT,
    drawn,
    freshness,
    listing_page,
    made_up,
    product_data,
    read_sitemap,
)
from recon.report import freshness_line


def test_sitemap_index() -> None:
    assert read_sitemap(sitemap_index())[:2] == ("index", [f"{BASE}/sitemap-1.xml", f"{BASE}/sitemap-2.xml.gz"])


def test_gzipped_urlset() -> None:
    kind, locs, lastmods = read_sitemap(gzip.compress(urlset([1, 2])))
    assert (kind, len(locs), lastmods) == ("urls", 2, ["2026-10-02", "2026-10-03"])


def test_an_escaped_ampersand_in_a_sitemap_loc() -> None:
    _, locs, _ = read_sitemap(b"<urlset><url><loc>https://s.test/i.php?a=1&amp;id=42</loc></url></urlset>")
    assert locs == ["https://s.test/i.php?a=1&id=42"]


def test_links_are_anchors_not_link_tags() -> None:
    html = (
        '<link rel="shortlink" href="/?p=12"><link rel="stylesheet" href="/s.css"><a class="x" href="/c/?page=2">2</a>'
    )
    assert HREF.findall(html) == ["/c/?page=2"]
    assert listing_page(["/?p=12"]) is not None, "a ?p= address still reads as a page number"


def test_a_json_ld_nested_too_deep_is_no_product() -> None:
    body = '<script type="application/ld+json">' + "[" * 5000 + "]" * 5000 + "</script>"
    assert product_data(Answer("u", 200, {}, (), body.encode()))["found"] is False


def test_last_modified_with_and_without_a_zone() -> None:
    fresh = freshness(
        [
            page("x", **{"last-modified": "Mon, 13 Oct 2025 10:00:00 GMT"}),
            page("y", **{"last-modified": "Mon, 13 Oct 2025 09:00:00"}),
        ]
    )
    assert fresh["last_modified_oldest"].startswith("2025-10-13T09:00:00")


def test_digits_only_product_address() -> None:
    assert PRODUCT_HINT.search("/2020000001")


def test_product_data_from_a_json_ld_graph() -> None:
    data = product_data(Answer("u", 200, {}, (), PRODUCT.format(name="Part 7", n=7).encode()))
    assert data["jsonld"] == {
        "name": "Part 7",
        "sku": "S-7",
        "mpn": "MPN-7",
        "brand": "ACME",
        "price": "1.50",
        "currency": "EUR",
        "vat_included": False,
        "availability": "InStock",
    }
    assert data["microdata"] == {"sku": "S-7"}
    assert data["found"]


def test_product_data_mends_raw_line_breaks_and_reads_meta() -> None:
    raw = (
        '<script type="application/ld+json">{"@type":["Product"],"mpn":"A\\nB","name":"x\ny",'
        '"offers":[{"price":2,"priceCurrency":"USD"},{"price":3}]}</script>'
        '<meta property="product:price:amount" content="2.00"><meta property="og:type" content="product">'
    )
    data = product_data(Answer("u", 200, {}, (), raw.encode()))
    assert (data["jsonld"]["name"], data["jsonld"]["price"], data["jsonld"]["offers"]) == ("x y", "2", 2)
    assert data["meta"] == {"product:price:amount": "2.00", "og:type": "product"}


def test_json_ld_past_the_first_head_bytes_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Big pages carry their JSON-LD at the end, past what is read for words and tags."""
    monkeypatch.setattr(settings, "HEAD", 1_000)
    body = "<html><title>P</title>" + "<p>filler</p>" * 500 + ld("MPN-9", "S-9") + "</html>"
    data = product_data(page(body))
    assert data["jsonld"]["mpn"] == "MPN-9"


def test_product_data_on_a_page_with_none() -> None:
    data = product_data(Answer("u", 200, {}, (), b"<html><title>About us</title>Our story</html>"))
    assert (data["found"], data["jsonld"], data["labels"]) == (False, {}, {})


def test_words_in_other_languages_and_entities() -> None:
    assert product_data(page("<p>Cena 10 Kč bez DPH</p>"))["labels"]["VAT"][0][:7] == "bez DPH"
    assert product_data(page("<p>IN STOCK &mdash;&nbsp;READY</p>"))["labels"]["stock"][0] == "IN STOCK — READY"


@pytest.mark.parametrize(
    ("url", "fake"),
    [
        pytest.param(f"{BASE}/2020000010", f"{BASE}/9999999999", id="an id's digits to nines"),
        pytest.param(f"{BASE}/product/foo-bar/", f"{BASE}/product/foo-bar-recon-x7q2/", id="a slug"),
        pytest.param(f"{BASE}/c/foo.html", f"{BASE}/c/foo-recon-x7q2.html", id="an .html slug"),
        pytest.param(
            f"{BASE}/index.php?route=product/product&product_id=42",
            f"{BASE}/index.php?route=product/product&product_id=99",
            id="an id in the query",
        ),
    ],
)
def test_made_up(url: str, fake: str) -> None:
    assert made_up(url) == fake


def test_listing_page() -> None:
    assert listing_page([f"{BASE}/a", f"{BASE}/c?sort=x&page=2"]) == (
        f"{BASE}/c?sort=x&page=2",
        f"{BASE}/c?sort=x&page=9999",
    )
    assert listing_page([f"{BASE}/c/page/3/"]) == (f"{BASE}/c/page/3/", f"{BASE}/c/page/9999/")
    assert listing_page([f"{BASE}/c/"]) is None


def test_freshness() -> None:
    old = "Mon, 13 Oct 2025 10:00:00 GMT"
    fresh = freshness(
        [
            page("x", **{"cf-cache-status": "HIT", "age": "172800", "last-modified": old}),
            page("y", **{"cf-cache-status": "HIT", "age": "60"}),
            page("z", **{"x-cache": "MISS, MISS from edge", "cache-control": "max-age=0"}),
            Answer("u", 404),
            None,
        ]
    )
    assert (fresh["pages"], fresh["cache"], fresh["age_max"], fresh["cache_control"]) == (
        3,
        {"HIT": 2, "MISS": 1},
        172800,
        "max-age=0",
    )
    assert fresh["last_modified_days"] > 300
    assert "stock and prices may be that old" in freshness_line(fresh)


def test_drawn_by_javascript() -> None:
    assert drawn(page('<body><div id="root"></div><script>x</script>'))["drawn"]
    assert not drawn(page("<body>" + "word " * 100 + "</body>"))["drawn"]

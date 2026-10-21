"""sample_findings(): the traps in a sample of product pages."""

import pytest
from fakes import NuxtSite, ld, page

from recon.sample import page_record, sample_findings

RECORDS = [
    page_record(page(ld("ABC-1", "ABC-1", "<p>In stock: 5000</p>"))),
    page_record(page(ld("4.84E+11", "S2", "<p>In stock: 5000</p>"))),
    page_record(page(ld("N/A", "S3", "<p>In stock: 5000</p>"))),
    page_record(page(ld("4006381333931", "S4", "<p>Qty 1+ 10+ 100+ price</p>"))),
    page_record(page(ld("DUP-7", "S5"))),
    page_record(page(ld("DUP-7", "S6"))),
    page_record(page("<p>Part Number: X-9</p><p>in stock 999+ pcs</p>")),
]


@pytest.mark.parametrize(
    "trap",
    [
        "the MPN equals the SKU on 1 of 7",
        "an MPN of 8 or 12-14 digits on 1 of 7",
        "Excel notation",
        "a placeholder as an MPN: `N/A`",
        "one MPN on several products: `DUP-7`",
        "a part number in the page's words but not in its data on 1 of 7",
        "stock shown capped (`999+`)",
    ],
)
def test_trap_found(trap: str) -> None:
    assert any(said.startswith(trap) for said in sample_findings(RECORDS)["traps"])


def test_the_same_stock_only_when_every_page_shows_it() -> None:
    assert not any("the same stock" in said for said in sample_findings(RECORDS)["traps"])
    same = sample_findings([page_record(page(ld(f"M{i}", f"S{i}", "<p>In stock: 5000</p>"))) for i in range(4)])
    assert same["traps"] == ["the same stock `5000` on all 4 pages showing one: a placeholder or a cap?"]


def test_price_ladder_hints() -> None:
    assert RECORDS[3]["ladder"], "quantity steps 1+ 10+ 100+"
    assert not RECORDS[0]["ladder"]
    assert page_record(page("<p>Qty 2 10 25+ Unit Price 0.50 0.40</p>"))["ladder"], "a quantity column of three"
    assert not page_record(page("<p>Qty 2 2+ Unit Price 19.98</p>"))["ladder"], "one tier and its quote row"


def test_a_part_number_only_the_state_holds_counts() -> None:
    """A Nuxt shop: JSON-LD without mpn on some product pages, the state's pro_sno on all of them."""
    site = NuxtSite()
    records = [page_record(page(site.product_page(n))) for n in range(4)]
    found = sample_findings(records)
    assert (found["coverage"]["mpn"], found["from_state"]) == (4, {"mpn": 2})
    assert not any("part number in the page's words" in t for t in found["traps"])
    assert records[1]["from_state"] == ["mpn"] and records[0]["from_state"] == []

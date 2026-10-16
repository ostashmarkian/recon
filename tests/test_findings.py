"""compare(), previous_report(), and the notes a site is looked up in."""

from pathlib import Path

from recon.findings import compare, guards_named, previous_report, protection_level
from recon.notes import notes_on, read_notes

BEFORE = {
    "protection": [],
    "vendors": {},
    "let_in": ["httpx-h2"],
    "way_in": "httpx-h2",
    "sitemap": {"addresses": 1000},
    "product": {"jsonld": {"mpn": "A"}},
}
AFTER = {
    "protection": ["in front: Cloudflare"],
    "vendors": {"Cloudflare": ["cf-ray"]},
    "let_in": ["curl-chrome"],
    "way_in": "curl-chrome",
    "sitemap": {"addresses": 1030},
    "product": {"jsonld": {"mpn": "A"}},
}


def test_what_changed() -> None:
    assert compare(BEFORE, AFTER) == [
        "protection: none -> in front: Cloudflare",
        "in front: none -> Cloudflare",
        "clients let in: httpx-h2 -> curl-chrome",
        "way in: httpx-h2 -> curl-chrome",
    ], "a sitemap 3% larger is no change"
    assert compare(AFTER, AFTER) == []


def test_what_an_older_report_never_read_is_no_change() -> None:
    assert compare(BEFORE, dict(BEFORE, sample={"traps": ["x"]}, ua_filter="refused GPTBot")) == []


def test_another_deeper_page_is_no_change_in_protection() -> None:
    on_x = dict(AFTER, protection=["clients turned away: httpx-h2 challenge on /, /x"])
    on_y = dict(AFTER, protection=["clients turned away: httpx-h2 challenge on /, /y"])
    assert compare(on_x, on_y) == []


def test_akamai_bot_manager_named_from_its_cookies() -> None:
    f = {"vendors": {"Akamai": ["cookie ak_bmsc (Bot Manager)", "cookie bm_mi (Bot Manager)"], "Fastly (CDN)": ["via"]}}
    assert guards_named(f) == ["Akamai Bot Manager (cookie ak_bmsc, cookie bm_mi)"]


def test_a_level_names_services_not_page_titles() -> None:
    rows = [
        {"client": "httpx-h2", "page": "https://s.test/", "verdict": "refused", "why": "403 Forbidden"},
        {"client": "curl-chrome", "page": "https://s.test/", "verdict": "ok", "why": ""},
    ]
    level = protection_level({"clients": rows, "let_in": ["curl-chrome"], "vendors": {}})
    assert level["level"] == 3
    assert level["said"].startswith("The site turns away httpx HTTP/2 (refused)")


def test_refused_only_under_load_is_a_rate_limit() -> None:
    rows = [{"client": "httpx-h2", "page": "https://s.test/", "verdict": "ok", "why": ""}]
    level = protection_level(
        {"clients": rows, "let_in": ["httpx-h2"], "vendors": {}, "session": {"refused": "with no cookies"}}
    )
    assert (level["level"], level["label"]) == (1, "a rate limit")
    assert "Refused under load in the session test, 4 at a time: a rate limit." in level["said"]


def test_a_change_of_level() -> None:
    assert compare(dict(AFTER, level={"level": 2}), dict(AFTER, level={"level": 3})) == ["protection level: 2 -> 3"]


def test_previous_report(tmp_path: Path) -> None:
    for name in ("shop.test-2026-10-01-0900.json", "shop.test-2026-10-15-1100.json", "other.test-2026-10-20-0900.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    found = previous_report(tmp_path, "shop.test")
    assert found is not None and found.name == "shop.test-2026-10-15-1100.json"
    assert previous_report(tmp_path, "none.test") is None


def test_notes_on_a_site(tmp_path: Path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "shop.md").write_text(
        "---\ndomain: shop.test\nscraper: built\ntype: hub\n---\n", encoding="utf-8"
    )
    (tmp_path / "shop" / "a note.md").write_text("www.shop.test answers 403", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "x.md").write_text("shop.test", encoding="utf-8")
    assert notes_on("www.shop.test", read_notes(tmp_path)) == {
        "domain": "shop.test",
        "note": {"note": "shop", "scraper": "built"},
        "mentions": 2,
    }
    assert notes_on("shop.test", []) is None

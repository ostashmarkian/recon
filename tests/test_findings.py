"""compare(), previous_report(), and the notes a site is looked up in."""

from pathlib import Path

from recon.findings import compare, guards_named, previous_report, protection, protection_level
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
    assert "A rate limit: refused in the session test, 4 at a time." in level["said"]


OK_ROW = {"client": "httpx-h2", "page": "https://s.test/", "verdict": "ok", "why": ""}


def test_a_bot_manager_in_front_is_level_4() -> None:
    """Akamai Bot Manager let every client in over a short run: it scores sessions, so 4, not 2."""
    f = {
        "clients": [OK_ROW],
        "let_in": ["httpx-h2"],
        "ua_filter": "blocked python-requests",
        "vendors": {"Akamai": ["header x-akamai-transformed", "cookie ak_bmsc (Bot Manager)"]},
    }
    level = protection_level(f)
    assert (level["level"], level["label"], level["scorers"]) == (4, "a bot manager in front", ["Akamai Bot Manager"])
    assert level["said"].startswith(
        "Akamai Bot Manager (header x-akamai-transformed, cookie ak_bmsc) scores every client over its session:"
        " all 1 clients with a browser User-Agent let in now, a long run can be turned away (--long measures it)."
    )
    assert "User-Agents refused by name: blocked python-requests." in level["said"]


def test_a_waf_by_rules_stays_at_what_was_seen() -> None:
    """Akamai with no Bot Manager cookie, Cloudflare with no __cf_bm: what was seen is what their rules do."""
    for vendors in ({"Akamai": ["server: AkamaiGHost"]}, {"Cloudflare": ["cf-ray", "server: cloudflare"]}):
        level = protection_level({"clients": [OK_ROW], "let_in": ["httpx-h2"], "vendors": vendors})
        assert (level["level"], level["scorers"]) == (1, [])
        assert "acts on the site owner's rules: what this run saw holds until they change." in level["said"]
    bm = protection_level(
        {"clients": [OK_ROW], "let_in": ["httpx-h2"], "vendors": {"Cloudflare": ["cf-ray", "cookie __cf_bm"]}}
    )
    assert (bm["level"], bm["scorers"]) == (4, ["Cloudflare's bot detection"])


def test_a_challenge_only_a_browser_passes_is_5_and_none_passing_is_closed() -> None:
    rows = [{"client": "httpx-h2", "page": "https://s.test/", "verdict": "challenge", "why": "Cloudflare"}]
    f = {"clients": rows, "let_in": [], "vendors": {"Cloudflare": ["cf-ray"]}, "browser": {"passed": True}}
    level = protection_level(f)
    assert (level["level"], level["state"], level["label"]) == (5, None, "a challenge for every client")
    assert level["said"].startswith("Cloudflare challenges every client, a browser User-Agent or not: only a real")
    closed = protection_level({**f, "browser": {"passed": False, "cookies": []}})
    assert (closed["level"], closed["state"], closed["label"]) == (None, "closed", "closed")
    assert closed["said"] == "Cloudflare lets no client in. A real browser is refused too."


def test_a_long_session_turned_away_late() -> None:
    late = {"at": 37, "minutes": 6.2, "url": "u", "status": 403, "verdict": "blocked", "why": "Akamai"}
    f = {
        "clients": [OK_ROW],
        "let_in": ["httpx-h2"],
        "vendors": {},
        "long": {"asked": 37, "minutes": 6.2, "refused": late},
    }
    level = protection_level(f)
    assert (level["level"], level["label"]) == (4, "a long session turned away")
    assert "A long session was turned away at request 37, 6.2 min in (403 blocked, Akamai)." in level["said"]
    assert "refused in the long session (403 blocked at request 37)" in protection(f)
    limited = {**late, "status": 429, "verdict": "limited", "why": ""}
    f["long"]["refused"] = limited
    level = protection_level(f)
    assert (level["level"], level["label"]) == (1, "a rate limit"), "a 429 is a limit"
    assert "the long session (429 at request 37, 6.2 min in)" in level["said"]


def test_a_long_session_not_turned_away() -> None:
    f = {"clients": [OK_ROW], "let_in": ["httpx-h2"], "vendors": {}, "long": {"asked": 90, "minutes": 15.0}}
    level = protection_level(f)
    assert "A long session of 15.0 min (90 requests) was not refused." in level["said"]
    assert level["unseen"] == "limits past 15.0 min of one session, the IP's reputation"


def test_a_refusal_one_at_a_time_is_a_pages_not_a_rate_limit() -> None:
    """A sitemap answering 403, as S3 does for a missing file: said, but no rate limit and no level up."""
    f = {"clients": [OK_ROW], "let_in": ["httpx-h2"], "vendors": {}, "refused_elsewhere": {"sitemaps": {"refused": 1}}}
    level = protection_level(f)
    assert (level["level"], level["label"]) == (0, "none seen")
    assert (
        level["said"]
        == "Nothing in front; no client or User-Agent turned away. Refused one at a time in sitemaps (1 refused)."
    )


def test_a_429_one_at_a_time_is_a_rate_limit() -> None:
    f = {"clients": [OK_ROW], "let_in": ["httpx-h2"], "vendors": {}, "refused_elsewhere": {"sample": {"limited": 6}}}
    level = protection_level(f)
    assert (level["level"], level["label"]) == (1, "a rate limit")
    assert "A rate limit: refused in sample (429, one at a time)." in level["said"]


def test_a_client_with_no_answer_is_not_turned_away() -> None:
    """A timeout is no refusal: no filter by fingerprint for a slow page."""
    rows = [OK_ROW, {"client": "curl-chrome", "page": "https://s.test/", "verdict": "error", "why": "TimeoutError"}]
    f = {"clients": rows, "let_in": ["httpx-h2"], "no_answer": ["curl-chrome"], "vendors": {}}
    level = protection_level(f)
    assert level["level"] == 0
    assert "No answer in time from curl_cffi as Chrome: not counted as turned away." in level["said"]
    silent = protection_level({"clients": rows[1:], "let_in": [], "no_answer": ["curl-chrome"], "vendors": {}})
    assert (silent["level"], silent["state"], silent["said"]) == (
        None,
        "unknown",
        "No client got an answer in time: the protection could not be judged.",
    ), "not 'level 5, nothing let in'"


def test_a_burst_compared_by_how_it_stopped_not_its_timings() -> None:
    slow1 = dict(AFTER, burst={"stop": "answers slowed to 1.20s against 0.30s at 8", "stop_kind": "slowed"})
    slow2 = dict(AFTER, burst={"stop": "answers slowed to 1.45s against 0.28s at 8", "stop_kind": "slowed"})
    limited = dict(AFTER, burst={"stop": "429 limited at 4", "stop_kind": "refused: limited"})
    assert compare(slow1, slow2) == []
    assert compare(slow1, limited) == ["burst: slowed -> refused: limited"]


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


def test_a_long_session_cut_by_the_local_link_is_not_judged() -> None:
    outage = {"at": 14, "minutes": 4.5, "url": "u", "why": "ReadError", "back": False, "waited": 10.5}
    f = {
        "clients": [OK_ROW],
        "let_in": ["httpx-h2"],
        "vendors": {},
        "long": {"asked": 14, "minutes": 15.0, "refused": None, "lost": None, "link": [outage], "cut": True},
    }
    level = protection_level(f)
    assert level["level"] == 0, "no level raised by this machine's link"
    assert "cut short at request 14, 4.5 min in, by this machine's link, not the site: inconclusive." in level["said"]
    assert "was not refused" not in level["said"]


def test_an_api_base_that_changed() -> None:
    before = {**BEFORE, "api": {"bases": [{"url": "https://api.a.test"}]}}
    after = {**BEFORE, "api": {"bases": [{"url": "https://api.b.test"}]}}
    assert compare(before, after) == ["API bases: https://api.a.test -> https://api.b.test"]
    assert compare(BEFORE, after) == [], "an older report, made before recon read the API"

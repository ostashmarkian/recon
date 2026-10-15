"""Whole runs of recon against a FakeSite: what it found, what it asked, what the report says."""

import pytest
from fakes import BASE, CHALLENGE, FakeBrowser, FakeSite, scan

from recon import settings
from recon.clients import Answer


@pytest.fixture(scope="module")
def open_site() -> tuple[dict, str, FakeBrowser, FakeSite]:
    """One run against an open shop, shared by the checks below: the burst alone is 350 requests."""
    site = FakeSite()
    findings, text, browser = scan(site)
    return findings, text, browser, site


class TestOpenSite:
    """No protection, so the burst runs every step."""

    def test_protection_and_way_in(self, open_site):
        f, text, browser, _ = open_site
        assert f["protection"] == []
        assert f["way_in"] == "httpx-h2, a browser User-Agent, cookies or none alike"
        assert f["let_in"] == list(settings.CLIENTS)
        assert (f["browser"], browser.urls) == (None, []), "no browser without a challenge"
        assert len(f["uas"]) == len(settings.UAS)
        assert f["ua_filter"] is None
        assert f["session"]["lock"] is False
        assert "**Protection:** none found" in text

    def test_pages_and_sitemap(self, open_site):
        f, *_ = open_site
        assert f["page"] == f"{BASE}/product/1/"
        assert (f["sitemap"]["files_read"], f["sitemap"]["addresses"]) == (3, 40)
        assert f["pool"] == 41, "the cart, the image and the other host left out"

    def test_platform_apis(self, open_site):
        f, *_ = open_site
        assert [(a["platform"], a["says"]) for a in f["apis"]] == [
            ("WooCommerce", "X-WP-Total 40; a product has sku 'S-1'"),
            ("WordPress", ""),
        ]

    def test_burst(self, open_site):
        f, text, _, site = open_site
        burst = f["burst"]
        assert ([s["at_once"] for s in burst["steps"]], burst["stop"]) == ([1, 2, 4, 8, 16], None)
        assert (burst["asked"], burst["distinct"]) == (350, 41)
        assert "no limit seen in 350 requests" in text
        assert f["requests"] == len(site.asked), "every request counted"

    def test_product_page(self, open_site):
        product = open_site[0]["product"]
        assert (product["url"], product["jsonld"]["mpn"], product["jsonld"]["vat_included"]) == (
            f"{BASE}/product/1/",
            "MPN-1",
            False,
        )
        assert product["labels"]["part number"][0][:20] == "Part Number: MPN-1 M"
        assert product["labels"]["VAT"][0][:9] == "excl. VAT"

    def test_product_sample(self, open_site):
        f, text, *_ = open_site
        sample = f["sample"]
        assert (sample["asked"], sample["read"]) == (10, 10)
        assert sample["coverage"] == {
            "mpn": 10,
            "sku": 10,
            "gtin": 0,
            "brand": 10,
            "price": 10,
            "currency": 10,
            "availability": 10,
            "inventory": 0,
        }
        assert (sample["currencies"], sample["vat_included"], sample["stock_numbers"], sample["traps"]) == (
            ["EUR"],
            {"False": 10},
            10,
            [],
        )
        assert "## Product sample, 10 pages" in text and "**Product sample:** 10 of 10" in text

    def test_not_found_pages(self, open_site):
        f, *_ = open_site
        assert f["not_found"]["findings"] == [
            "a made-up product: 404 gone",
            "a made-up path: 404 gone",
            "page 9999: 404 gone",
        ]
        assert [r["url"] for r in f["not_found"]["rows"]][2:] == [
            f"{BASE}/category/?page=2",
            f"{BASE}/category/?page=9999",
        ], "the listing found on the category page"

    def test_sources_freshness_rendering(self, open_site):
        f, *_ = open_site
        assert (f["sources"]["search"], f["sources"]["endpoints"]) == (
            {"Searchanise": "searchanise"},
            ["/api/catalog/products?limit=24"],
        )
        assert f["freshness"]["cache"] == {}
        assert {k: v["drawn"] for k, v in f["rendering"].items()} == {"home": False, "product": False}


def test_session_lock():
    f, text, _ = scan(FakeSite(lock=True), burst=False)
    assert f["session"]["lock"] is True
    assert f["way_in"].endswith("no cookies (a session lock)")
    assert "**Session lock:** yes" in text


def test_cloudflare_by_tls():
    """Cloudflare challenging httpx: curl_cffi the way in, no burst."""
    f, _, browser = scan(FakeSite(guard="cloudflare-tls"))
    assert f["let_in"] == ["curl-chrome", "curl-safari", "curl-firefox"]
    assert f["way_in"] == "curl-chrome, its own User-Agent, cookies or none alike"
    assert browser.urls == [f"{BASE}/"], "the browser opened on the page challenged"
    assert {c["verdict"] for c in f["browser"]["clearance_carried"]} == {"challenge"}
    assert [p.split(":")[0] for p in f["protection"]] == ["in front", "clients turned away"]
    assert "skipped" in f["burst"] and "steps" not in f["burst"]
    assert f["uas_through"] == "curl-chrome"
    assert [p["name"] for p in f["platforms"]] == ["WooCommerce", "WordPress"], "read from a page let in"


def test_guard_letting_every_probe_in():
    f, _, browser = scan(FakeSite(guard="cloudflare-open"))
    assert (f["let_in"], browser.urls) == (list(settings.CLIENTS), [])
    assert f["protection"] == ["in front: Cloudflare"]
    assert f["burst"] == {"skipped": ["in front: Cloudflare"]}


def test_user_agent_filter_is_not_protection():
    f, text, _ = scan(FakeSite(refuse_uas=("GPTBot", "ClaudeBot")))
    assert f["ua_filter"] == "refused GPTBot, ClaudeBot"
    assert f["protection"] == []
    assert [s["at_once"] for s in f["burst"]["steps"]] == [1, 2, 4, 8, 16]
    assert "- **User-Agent filter:** refused GPTBot, ClaudeBot (not protection" in text


def test_crawl_delay():
    f, text, _ = scan(FakeSite(crawl_delay=10, rate=True))
    assert f["protection"] == []
    assert f["burst"] == {"skipped": ["robots.txt asks Crawl-delay 10"]}
    assert "- **Burst:** skipped (robots.txt asks Crawl-delay 10)" in text
    assert f["rate_headers"] == {"x-ratelimit-remaining": "99"}
    assert f["session"] == {"skipped": "robots.txt asks Crawl-delay 10"}, "several at a time is what it asks not to do"


def test_crawl_delay_paces_the_requests(monkeypatch):
    monkeypatch.setattr(settings, "PAUSE", 0.001)
    f, text, _ = scan(FakeSite(crawl_delay=0.02), burst=False, pause=None)
    assert f["pause"] == 0.02
    assert "**Pace:** one request every 0.02 s" in text


def test_silent_200s():
    f, text, _ = scan(FakeSite(soft404=True, wrap=True), burst=False)
    said = f["not_found"]["findings"]
    assert said[0].startswith("a made-up product answers 200")
    assert said[2].startswith("page 9999 answers 200 like the real page")
    assert "## Not-found pages" in text and "a soft 404" in text


class TestBurstStops:
    def test_at_the_first_refusal(self):
        f, text, _ = scan(FakeSite(limit=60))
        burst = f["burst"]
        assert [s["at_once"] for s in burst["steps"]] == [1, 2, 4]
        assert burst["stop"].startswith("429 limited (Retry-After 60)")
        assert burst["steps"][-1]["answers"].get("429 limited", 0) <= 4, "no more sent than were in flight"
        assert burst["after"]["verdict"] == "ok", "asked again RECOVER s later"
        assert "stopped after" in text and "at 4 at a time" in text

    def test_at_the_second_connection_lost(self):
        burst = scan(FakeSite(drop_after=40))[0]["burst"]
        assert burst["steps"][-1]["at_once"] == 2
        assert "connections lost at 2 at a time" in burst["stop"]

    def test_when_answers_slow(self, monkeypatch):
        monkeypatch.setattr(settings, "SLOW_FLOOR", 0.0)
        burst = scan(FakeSite(slow=True))[0]["burst"]
        assert "slowed" in (burst["stop"] or "")

    def test_at_8_over_http1(self):
        burst = scan(FakeSite(http="h1"))[0]["burst"]
        assert [s["at_once"] for s in burst["steps"]] == [1, 2, 4, 8]

    def test_never_with_no_burst(self):
        assert scan(FakeSite(), burst=False)[0]["burst"] == {"skipped": ["--no-burst"]}


def test_nothing_let_in():
    class Wall(FakeSite):
        def answer(self, client, url, headers):
            return Answer(url, 403, {"cf-mitigated": "challenge", "cf-ray": "x"}, (), CHALLENGE.encode(), 0.01)

    f, text, _ = scan(Wall(), browser=FakeBrowser(fail=True))
    assert f["way_in"] == "none found: no client let in"
    assert "Not run on" in text and "Chrome is not installed" in text
    assert f["session"]["skipped"] == "no client let in"
    assert "no client let in" in f["burst"]["skipped"]


def test_robots_txt_keeps_pages_out_of_the_pool():
    f, _, _ = scan(FakeSite(disallow="/product/1"), burst=False)
    assert f["pool"] == 41 - 11


def test_sitemap_guessed_when_robots_names_none():
    site = FakeSite(sitemap_at="/xmlsitemap.php")
    f, _, _ = scan(site, burst=False)
    assert (f["sitemap"]["addresses"], f["sitemap"]["files_read"]) == (40, 5)
    assert [p for _, _, p in site.asked if "sitemap" in p][:3] == [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/xmlsitemap.php",
    ]

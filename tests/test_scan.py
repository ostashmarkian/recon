"""Whole runs of recon against a FakeSite: what it found, what it asked, what the report says."""

import asyncio

import pytest
from fakes import BASE, CHALLENGE, FakeBrowser, FakeClient, FakeSite, FakeWatcher, scan

from recon import settings
from recon.clients import Answer
from recon.probe import Recon


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
        assert f["way_in"] == "httpx HTTP/2, a browser User-Agent, cookies or none alike"
        assert f["level"]["level"] == 0
        assert "**Protection: level 0 of 5, none seen.** Nothing in front; no client or User-Agent turned away." in text
        assert f["let_in"] == list(settings.CLIENTS)
        assert (f["browser"], browser.urls) == (None, []), "no browser without a challenge"
        assert len(f["uas"]) == len(settings.UAS)
        assert f["ua_filter"] is None
        assert f["session"]["lock"] is False

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
        assert site.most_in_flight <= 16, "never more than 16 at once"
        assert site.posts == [], "nothing posted: no platform here asks with a body"
        assert burst["stop_kind"] is None

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
    assert f["way_in"] == "curl_cffi as Chrome, its own User-Agent, cookies or none alike"
    level = f["level"]
    assert (level["level"], level["label"]) == (3, "a filter by fingerprint")
    assert "Python's own TLS is what is turned away: the TLS fingerprint decides." in level["said"]
    assert "A real browser is let in and gets cf_clearance, but the cookie does not carry over" in level["said"]
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
    assert (f["level"]["level"], f["level"]["label"]) == (1, "a service in front, no client turned away")


def test_myra_in_front_keeps_the_burst_off():
    """Every probe let in, as Myra lets the first requests in before it bans the IP."""
    f, _, _ = scan(FakeSite(guard="myra"))
    assert f["vendors"] == {"Myra Security": ["server: myracloud"]}
    assert f["burst"] == {"skipped": ["in front: Myra Security"]}
    assert (f["level"]["level"], f["level"]["label"]) == (4, "a bot manager in front")


class TestLongSession:
    def test_turned_away_late_keeps_the_burst_off(self, monkeypatch):
        """Akamai lets a client have 15 product pages, then blocks it: only a long session sees it."""
        monkeypatch.setattr(settings, "LONG_PAUSE", (0, 0))
        site = FakeSite(block_after=15)
        f, text, _ = scan(site, long=1.0)
        late = f["long"]["refused"]
        assert (late["status"], late["verdict"], late["why"]) == (403, "blocked", "Akamai")
        assert f["long"]["asked"] == late["at"], "nothing more asked after the refusal"
        assert (f["level"]["level"], f["level"]["label"]) == (4, "a long session turned away")
        assert "**Protection: level 4 of 5, a long session turned away.** All 7 clients" in text
        assert f"- **Long session:** refused at request {late['at']}" in text
        assert f["burst"]["skipped"] == [
            "in front: Akamai",
            f"refused in the long session (403 blocked at request {late['at']})",
        ]

    def test_not_turned_away_runs_to_its_cap(self, monkeypatch):
        monkeypatch.setattr(settings, "LONG_PAUSE", (0, 0))
        monkeypatch.setattr(settings, "LONG_MOST", 6)
        f, text, _ = scan(FakeSite(), long=1.0, burst=False)
        assert (f["long"]["asked"], f["long"]["refused"]) == (6, None)
        assert "- **Long session:** 6 requests over 0.0 min, none refused (httpx HTTP/2, one cookie jar" in text
        assert "A long session of 0.0 min (6 requests) was not refused." in f["level"]["said"]

    def test_not_run_without_the_flag(self):
        f, text, _ = scan(FakeSite(), burst=False)
        assert "long" not in f and "Long session" not in text


def test_user_agent_filter_is_not_protection():
    f, text, _ = scan(FakeSite(refuse_uas=("GPTBot", "ClaudeBot")))
    assert f["ua_filter"] == "refused GPTBot, ClaudeBot"
    assert f["protection"] == []
    assert [s["at_once"] for s in f["burst"]["steps"]] == [1, 2, 4, 8, 16]
    assert "**Protection: level 2 of 5, a filter by name.** The site refuses User-Agents by name" in text
    assert "- **User-Agent filter:**" not in text, "level 2 is the filter: said once"
    assert f["level"]["level"] == 2
    assert f["level"]["said"].startswith("The site refuses User-Agents by name (refused GPTBot, ClaudeBot); all 7")


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
        assert burst["stop_kind"] == "refused: limited"
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

    def test_when_200s_shrink(self):
        """A shop failing quietly under load: 200s with a PHP warning in place of its product pages."""
        site = FakeSite(shrink_over=4)
        f, text, _ = scan(site)
        burst = f["burst"]
        assert [s["at_once"] for s in burst["steps"]] == [1, 2, 4, 8]
        assert burst["stop_kind"] == "answers shrank"
        said = "at 8 at a time were 200 but under 50% of the smallest page read one at a time: /product/"
        assert said in burst["stop"]
        assert burst["stop"].endswith(" read alone") and "stopped after" in text
        assert burst["after"]["verdict"] == "ok"
        assert f["requests"] == len(site.asked), "the page read alone counted"

    def test_a_page_small_by_itself_has_not_shrunk(self):
        """Under half the first step's smallest page, but as small read alone: the site's own, nothing stops."""
        site = FakeSite(soft404=True)  # any other page: a short 200
        client = FakeClient(site, "httpx-h2", None, False)
        recon = Recon(BASE, make=lambda kind, ua=None, cookies=False: client, pause=0)
        short = asyncio.run(client.fetch(f"{BASE}/about/"))
        floor = len(asyncio.run(client.fetch(f"{BASE}/product/1/")).body)
        assert len(short.body) < settings.SHRUNK_SHARE * floor, "a small page here"
        said, lowered = asyncio.run(recon.shrank(client, [short, short], floor, 8))
        assert (said, lowered) == (None, len(short.body)), "the floor drops to it, so it is not read again"
        assert [p for _, _, p in site.asked].count("/about/") == 2, "read alone once"

    def test_at_8_over_http1(self):
        site = FakeSite(http="h1")
        burst = scan(site)[0]["burst"]
        assert [s["at_once"] for s in burst["steps"]] == [1, 2, 4, 8]
        assert site.most_in_flight <= 8, "never more than 8 connections over HTTP/1.1"

    def test_never_with_no_burst(self):
        assert scan(FakeSite(), burst=False)[0]["burst"] == {"skipped": ["--no-burst"]}


def test_nothing_let_in():
    class Wall(FakeSite):
        def answer(self, client, url, headers):
            return Answer(url, 403, {"cf-mitigated": "challenge", "cf-ray": "x"}, (), CHALLENGE.encode(), 0.01)

    f, text, _ = scan(Wall(), browser=FakeBrowser(fail=True))
    assert f["way_in"] == "none found: no client let in"
    assert (f["level"]["level"], f["level"]["state"]) == (None, "closed")
    assert "- **Protection: closed.** Cloudflare lets no client in." in text
    assert "The browser could not run (RuntimeError: Chrome is not installed)." in f["level"]["said"]
    assert "Not run on" in text and "Chrome is not installed" in text
    assert f["session"]["skipped"] == "no client let in"
    assert "no client let in" in f["burst"]["skipped"]

    f, text, _ = scan(Wall(), burst=False)  # a browser that passes: level 5, only a real browser gets in
    assert (f["level"]["level"], f["level"]["label"]) == (5, "a challenge for every client")
    assert f["level"]["said"].startswith("Cloudflare challenges every client")
    assert "A real browser is let in and gets cf_clearance" in f["level"]["said"]


def test_robots_txt_keeps_pages_out_of_the_pool():
    f, _, _ = scan(FakeSite(disallow="/product/1"), burst=False)
    assert f["pool"] == 41 - 11


def test_a_redirected_robots_txt_is_followed():
    f, _, _ = scan(FakeSite(robots_moved=True, disallow="/product/1"), burst=False)
    assert (f["robots"]["state"], f["robots"]["url"]) == ("read", f"{BASE}/real-robots.txt")
    assert f["pool"] == 41 - 11, "its Disallow kept"


def test_an_unreadable_robots_txt_keeps_recon_to_the_home_page():
    site = FakeSite(robots_status=503)
    f, _, _ = scan(site)
    assert f["robots"]["state"] == "unreadable"
    assert f["pool"] == 0
    assert "robots.txt could not be read: everything counts as disallowed" in f["burst"]["skipped"]
    assert not any(path.startswith("/product/") for _, _, path in site.asked)


def test_links_that_change_the_sites_state_stay_out():
    state = [
        "/?add-to-cart=7",
        "/index.php?route=checkout/cart",
        "/?remove_item=ab12",
        "/?buy=12",
        "/order/add?product=12",
        "/kosik/pridat/?id=4",
        "/warenkorb/",
        "/koszyk/",
    ]
    site = FakeSite(home_extra="".join(f'<a href="{s}">x</a>' for s in state))
    scan(site, burst=False)
    assert not [path for _, _, path in site.asked if path in state]


def test_a_crawl_delay_past_the_limit_stops_the_run(monkeypatch):
    monkeypatch.setattr(settings, "PAUSE", 0.001)
    site = FakeSite(crawl_delay=3600)
    f, text, _ = scan(site, pause=None)
    assert f["stopped"].startswith("robots.txt asks Crawl-delay 3600 s, more than recon's limit of 60 s")
    assert [path for _, _, path in site.asked] == ["/", "/robots.txt"]
    assert "- **Stopped:** robots.txt asks Crawl-delay 3600 s" in text
    assert "level" not in f, "not 'level 5, nothing let in'"


def test_refusals_in_the_product_sample_keep_the_burst_off():
    f, _, _ = scan(FakeSite(limit=3))
    assert f["refused_elsewhere"] == {"sample": {"limited": 6}}
    assert "refused in other steps: sample (6 limited)" in f["burst"]["skipped"]
    assert (f["level"]["level"], f["level"]["label"]) == (1, "a rate limit"), "a 429 is a limit at any pace"


def test_a_refused_sitemap_keeps_the_burst_off_but_is_no_rate_limit():
    f, text, _ = scan(FakeSite(sitemap_refused=True))
    assert f["refused_elsewhere"] == {"sitemaps": {"refused": 1}}
    assert "refused in other steps: sitemaps (1 refused)" in f["burst"]["skipped"]
    assert (f["level"]["level"], f["level"]["label"]) == (0, "none seen")
    assert "Refused one at a time in sitemaps (1 refused)." in f["level"]["said"]
    assert "rate limit" not in text


def test_a_deeper_page_answering_400_turns_no_client_away():
    f, _, _ = scan(FakeSite(), page=f"{BASE}/bad-request/", burst=False)
    assert f["let_in"] == list(settings.CLIENTS), "a 4xx is the page's own, no refusal"
    assert f["level"]["level"] == 0


def test_a_client_with_no_answer_is_no_filter():
    f, text, _ = scan(FakeSite(silent_for=("curl-safari",)), burst=False)
    assert f["no_answer"] == ["curl-safari"]
    assert "curl-safari" not in f["let_in"]
    assert f["level"]["level"] == 0, "not 'level 3, a filter by fingerprint'"
    assert "No answer in time from curl_cffi as Safari: not counted as turned away." in text


def test_a_home_page_moved_to_another_site_stops_the_run():
    site = FakeSite(home_moved=True)
    f, text, _ = scan(site)
    assert f["stopped"].startswith("the home page redirects (301) to https://moved.test/, another site")
    assert [path for _, _, path in site.asked] == ["/"], "nothing more asked"
    assert "level" not in f, "a stopped run judges no protection"
    assert "- **Stopped:** the home page redirects (301) to https://moved.test/" in text
    assert "robots.txt:" not in text


def test_an_api_robots_txt_disallows_is_not_asked():
    site = FakeSite(disallow="/wp-json/")
    f, _, _ = scan(site, burst=False)
    assert [a["says"] for a in f["apis"] if a["platform"] == "WooCommerce"] == [
        "robots.txt disallows /wp-json/wc/store/v1/products"
    ]
    assert not any(path.startswith("/wp-json") for _, _, path in site.asked)


def test_a_home_page_redirecting_to_a_captcha_is_no_way_in():
    f, text, _ = scan(FakeSite(home_captcha=True), burst=False)
    assert f["home_redirect"] == "302 to /captcha/?from=/: not followed (a block)"
    assert f["let_in"] == []
    assert f["level"]["state"] == "closed", "not 'level 0, nothing refused'"
    assert "The home page redirects 302 to /captcha/?from=/: not followed (a block)" in text


def test_an_address_python_cannot_parse_is_left_out():
    f, _, _ = scan(FakeSite(home_extra='<a href="https://[shop-domain]/help">help</a>'), burst=False)
    assert "errors" not in f
    assert f["pool"] == 41


def test_a_step_that_breaks_leaves_the_others_their_report(monkeypatch):
    import recon.probe

    def broken(answers):
        raise RuntimeError("a page recon cannot read")

    monkeypatch.setattr(recon.probe, "sources_of", broken)
    f, text, _ = scan(FakeSite())
    assert f["errors"] == [{"step": "sources", "error": "RuntimeError: a page recon cannot read"}]
    assert f["burst"]["steps"], "the burst ran all the same"
    assert "## Errors" in text and "- sources: RuntimeError: a page recon cannot read" in text


def test_with_no_deeper_page_robots_txt_is_no_main_page():
    class Bare(FakeSite):
        def answer(self, client, url, headers):
            path = url.removeprefix(BASE) or "/"
            if path == "/":
                return Answer(url, 200, {"server": "nginx"}, (), b"<html><title>Hi</title>no links</html>", 0.01)
            if path == "/robots.txt":
                return Answer(url, 403, {"server": "nginx"}, (), b"<title>403 Forbidden</title>", 0.01)
            return Answer(url, 404, {"server": "nginx"}, (), b"", 0.01)

    f, _, _ = scan(Bare(), burst=False)
    assert f["page"] is None
    assert f["let_in"] == list(settings.CLIENTS)
    assert f["level"]["level"] != 5


def test_indexes_of_indexes_do_not_spend_the_sitemap_budget():
    """30 indexes under the sitemap: read depth first, a few of each, so the address files are reached."""
    f, text, _ = scan(FakeSite(nested=30), burst=False)
    sm = f["sitemap"]
    assert sm["addresses"] == 40, "both address files read, through the first index"
    assert sm["files_read"] == 1 + settings.SITEMAP_CHILDREN + 2, "the index, 4 of its indexes, the 2 files once"
    assert sm["files_named"] == 1 + 30 + 2
    assert f["pool"] == 41
    assert "more files named, not read" in text


def test_a_product_is_looked_for_in_another_family_of_pages():
    """50 marketing pages under /products/ outnumber the 40 products: the second try is a product all the same,
    and the sample is drawn from the products' family."""
    extra = "".join(f'<a href="/products/highlights/topic-{n}/">x</a>' for n in range(50))
    f, _, _ = scan(FakeSite(home_extra=extra), burst=False)
    product = f["product"]
    assert product["tried"][0].startswith(f"{BASE}/products/highlights/"), "the largest family is tried first"
    assert product["url"].startswith(f"{BASE}/product/") and len(product["tried"]) == 2
    assert f["sample"]["coverage"]["mpn"] == f["sample"]["read"] == 10


def test_a_product_address_that_redirects_is_followed_once():
    f, _, _ = scan(FakeSite(), page=f"{BASE}/p/7/", burst=False)
    assert (f["product"]["url"], f["product"]["found"]) == (f"{BASE}/product/7/", True)


class TestWatch:
    def test_what_the_pages_fetch(self):
        site, watcher = FakeSite(), FakeWatcher()
        f, text, _ = scan(site, burst=False, watch=True, watcher=watcher)
        assert watcher.urls == [f"{BASE}/", f["product"]["url"], f"{BASE}/category/?page=2"]
        assert f["requests"] == len(site.asked) + 3, "a page Chrome opens counts as a request"
        first = f["watch"]["pages"][0]["calls"]
        assert [c["kind"] for c in first] == ["products", "html", "data"], "the product list first"
        assert (first[0]["own"], first[2]["own"]) == (True, False)
        assert (
            "- **What the pages fetch:** 9 calls on 3 pages; GET /api/catalog/products?limit=24: a product list at"
            " `products` (24: id, sku, name, price, stock); paging total, page" in text
        )
        assert "## What the pages fetch, in Chrome" in text and "(abc-dsn.algolia.net)" in text

    def test_not_past_a_site_that_lets_no_client_in(self):
        class Wall(FakeSite):
            def answer(self, client, url, headers):
                return Answer(url, 403, {"cf-mitigated": "challenge", "cf-ray": "x"}, (), CHALLENGE.encode(), 0.01)

        watcher = FakeWatcher()
        f, text, _ = scan(Wall(), burst=False, watch=True, watcher=watcher)
        assert (f["watch"], watcher.urls) == ({"skipped": "no client let in"}, [])
        assert "- **What the pages fetch:** not watched (no client let in)" in text

    def test_only_pages_robots_txt_allows(self):
        watcher = FakeWatcher()
        f, _, _ = scan(FakeSite(disallow="/"), burst=False, watch=True, watcher=watcher)
        assert (f["watch"], watcher.urls) == ({"skipped": "robots.txt allows none of the pages"}, [])

    def test_chrome_missing_is_said(self):
        _, text, _ = scan(FakeSite(), burst=False, watch=True, watcher=FakeWatcher(fail=True))
        assert "Chrome could not run (RuntimeError: Chrome is not installed)" in text

    def test_not_without_the_flag(self):
        watcher = FakeWatcher()
        f, _, _ = scan(FakeSite(), burst=False, watcher=watcher)
        assert ("watch" not in f, watcher.urls) == (True, [])


def test_sitemap_guessed_when_robots_names_none():
    site = FakeSite(sitemap_at="/xmlsitemap.php")
    f, _, _ = scan(site, burst=False)
    assert (f["sitemap"]["addresses"], f["sitemap"]["files_read"]) == (40, 5)
    assert [p for _, _, p in site.asked if "sitemap" in p][:3] == [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/xmlsitemap.php",
    ]

"""Whole runs of recon against a FakeSite: what it found, what it asked, what the report says."""

import asyncio
import json

import pytest
from fakes import (
    API,
    API_DNS,
    BASE,
    CDN,
    CHALLENGE,
    INTERNAL,
    LISTED,
    FakeBrowser,
    FakeClient,
    FakeSite,
    FakeWatcher,
    NuxtSite,
    scan,
)

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

    def test_the_local_link_failing_is_not_the_site(self, monkeypatch):
        """At request 15 this machine's link goes down for 4 requests: the site and both neutral hosts silent,
        then the first neutral host once more; the second answers, and the session goes on to its cap."""
        monkeypatch.setattr(settings, "LONG_PAUSE", (0, 0))
        monkeypatch.setattr(settings, "LINK_WAIT", 0)
        monkeypatch.setattr(settings, "LONG_MOST", 30)
        site = FakeSite(link_down=(15, 4))
        f, text, _ = scan(site, long=1.0, burst=False)
        long = f["long"]
        assert (long["lost"], long["refused"], long["cut"], long["asked"]) == (None, None, False, 30)
        [outage] = long["link"]
        assert (outage["at"], outage["back"], outage["why"]) == (15, True, "ReadError")
        assert [p for _, _, p in site.asked if p in settings.NEUTRAL_HOSTS] == [*settings.NEUTRAL_HOSTS] * 2
        assert "this machine's link failed at request 15" in text and "not the site" in text
        assert "A long session of 0.0 min (30 requests) was not refused." in f["level"]["said"]

    def test_a_link_that_stays_down_leaves_the_site_unjudged(self, monkeypatch):
        monkeypatch.setattr(settings, "LONG_PAUSE", (0, 0))
        monkeypatch.setattr(settings, "LINK_WAIT", 0.05)
        site = FakeSite(link_down=(15, 100_000))  # past the session test's 13 requests with a jar
        f, text, _ = scan(site, long=0.02, burst=False)
        long = f["long"]
        assert (long["cut"], long["lost"], long["refused"], long["asked"]) == (True, None, None, 15)
        assert long["link"][0]["at"] == 15 and not long["link"][0]["back"]
        assert "- **Long session:** cut short at request 15" in text and "the site is not judged past it" in text
        assert "by this machine's link, not the site: inconclusive." in f["level"]["said"]
        assert "answers lost" not in text

    def test_the_site_dropping_while_the_link_works_is_the_site(self, monkeypatch):
        monkeypatch.setattr(settings, "LONG_PAUSE", (0, 0))
        site = FakeSite(drop_after=12)
        f, text, _ = scan(site, long=1.0, burst=False)
        long = f["long"]
        assert long["lost"]["verdict"] == "dropped" and long["link"] == [] and not long["cut"]
        assert "- **Long session:** answers lost at request" in text
        assert [p for _, _, p in site.asked].count(settings.NEUTRAL_HOSTS[0]) == settings.LOST_MAX, "asked at each loss"


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


def test_the_apis_own_refusals_leave_the_burst_on():
    """A 401 of an API route is its key, and a 403 of an API host is that host's: neither is the site's, whose
    own pages let every client in, so its burst runs."""

    class Keyed(FakeSite):
        def answer(self, client, url, headers):
            if url.startswith("https://api.other.test"):
                return Answer(url, 403, {"server": "nginx"}, (), b"<title>403 Forbidden</title>", 0.01)
            if url.startswith(f"{BASE}/api/catalog/products"):
                return Answer(url, 401, {"server": "nginx"}, (), b'{"error": "no key"}', 0.01)
            return super().answer(client, url, headers)

    extra = '<script>window.cfg={apiHost:"https://api.other.test"}</script>'
    site = Keyed(home_extra=extra, dns={"api.other.test": {"addresses": ["8.8.4.4"]}})
    f, _, _ = scan(site)
    probe = f["api"]["probe"]
    assert (probe["url"], probe["status"]) == (f"{BASE}/api/catalog/products?limit=24", 401)
    assert f["api"]["bases"][0]["robots"] == "unreadable", "the API host refused its robots.txt: nothing asked of it"
    assert f["refused_elsewhere"] == {} and f["level"]["level"] == 0
    assert f["burst"]["steps"], "the burst ran"


def test_a_route_not_on_the_api_host_is_asked_on_the_site():
    """The API host named answers 404 for the route the page calls: the site itself is asked next."""
    extra = '<script>window.cfg={apiHost:"https://api2.shop.test"}</script>'
    site = FakeSite(home_extra=extra, dns={"api2.shop.test": {"addresses": ["8.8.4.4"]}})
    f, _, _ = scan(site, burst=False)
    probe = f["api"]["probe"]
    assert (probe["url"], probe["kind"]) == (f"{BASE}/api/catalog/products?limit=24", "products")
    assert [x["url"] for x in probe["others"]] == ["https://api2.shop.test/api/catalog/products?limit=24"]


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
    def test_what_the_pages_fetch(self, monkeypatch):
        monkeypatch.setattr(settings, "REPLAY_MOST", 10)  # so only the one-per-endpoint rule keeps it to once
        site, watcher = FakeSite(), FakeWatcher()
        f, text, _ = scan(site, burst=False, watch=True, watcher=watcher)
        assert watcher.urls == [f"{BASE}/", f["product"]["url"], f"{BASE}/category/?page=2"]
        assert f["requests"] == len(site.asked) + 3, "a page Chrome opens counts as a request"
        first = f["watch"]["pages"][0]["calls"]
        assert [c["kind"] for c in first] == ["products", "products", "html", "data"], "the product lists first"
        assert (first[0]["own"], first[3]["own"]) == (True, False)
        assert (
            "- **What the pages fetch:** 12 calls on 3 pages; GET /api/catalog/products?limit=24: a product list at"
            " `products` (24: id, sku, name, price, stock); paging total, page; works with httpx HTTP/2 alone,"
            " no cookie or token; GET /api/private/products?limit=24: a product list" in text
        )
        assert "with httpx HTTP/2 alone: 401 refused; the page sent x-api-key, cookie sid, cookie basket" in text, (
            "what the browser sent and the plain client did not"
        )
        assert first[2]["replay"]["works"], "the fragment too"
        assert [p for _, _, p in site.asked].count("/api/catalog/products?limit=24") == 1, "asked again once"
        assert "## What the pages fetch, in Chrome" in text and "(abc-dsn.algolia.net)" in text

    def test_no_cookie_or_token_value_is_kept_or_sent(self):
        site = FakeSite()
        f, text, _ = scan(site, burst=False, watch=True, watcher=FakeWatcher())
        for secret in ("secret-key-123", "abc123"):
            assert secret not in text and secret not in json.dumps(f, default=str), secret
        assert all("x-api-key" not in (headers or {}) for _, _, headers in site.sent), "replayed without the key"

    def test_what_is_not_asked_again(self):
        def call(url: str, sent: str = "") -> dict:
            method = "POST" if sent else "GET"
            return {
                "method": method,
                "url": url,
                "status": 200,
                "type": "application/json",
                "sent": sent,
                "body": LISTED,
            }

        extra = (
            call(f"{BASE}/graphql", '{"query": "mutation { addToCart(id: 1) }"}'),
            call("https://api.searchanise.com/getresults?q=x"),
            call(f"{BASE}/api/short/products"),
        )
        site = FakeSite(disallow="/api/private/")
        f, _, _ = scan(site, burst=False, watch=True, watcher=FakeWatcher(extra=extra))
        replays = {c["url"].removeprefix(BASE): c.get("replay") for c in f["watch"]["pages"][0]["calls"]}
        assert replays["/graphql"] == {"skipped": "a GraphQL mutation"}
        assert replays["/api/private/products?limit=24"] == {"skipped": "robots.txt disallows it"}
        assert replays["https://api.searchanise.com/getresults?q=x"] is None, "another host's API is not asked"
        short = replays["/api/short/products"]
        assert (short["works"], short["items"]) == (False, 3), "a shorter list for a stranger is no way in"
        assert not [p for _, _, p in site.asked if p.startswith(("/graphql", "/api/private/"))]

    def test_not_past_a_site_that_lets_no_client_in(self):
        class Wall(FakeSite):
            def answer(self, client, url, headers):
                return Answer(url, 403, {"cf-mitigated": "challenge", "cf-ray": "x"}, (), CHALLENGE.encode(), 0.01)

        watcher = FakeWatcher()
        f, text, _ = scan(Wall(), burst=False, watch=True, watcher=watcher)
        assert (f["watch"], watcher.urls) == ({"skipped": "no client let in"}, [])
        assert "- **What the pages fetch:** not watched (no client let in)" in text

    def test_the_page_given_though_robots_txt_disallows_it_and_no_other(self):
        """recon was given the page and read it: Chrome opens it too, and the report says robots.txt keeps
        crawlers off it; the pages recon picks itself stay where robots.txt allows."""
        watcher = FakeWatcher()
        f, text, _ = scan(FakeSite(disallow="/"), burst=False, watch=True, watcher=watcher)
        assert watcher.urls == [f"{BASE}/"]
        assert f["watch"]["given_disallowed"] == f"{BASE}/"
        assert f["robots"]["given_disallowed"] == {f"{BASE}/": "Disallow: /"}
        assert "(the page given among them, though robots.txt disallows it)" in text
        assert "- **robots.txt disallows the page given:** / (Disallow: /)." in text

    def test_chrome_missing_is_said(self):
        _, text, _ = scan(FakeSite(), burst=False, watch=True, watcher=FakeWatcher(fail=True))
        assert "Chrome could not run (RuntimeError: Chrome is not installed)" in text

    def test_on_by_default_and_off_with_no_watch(self):
        watcher = FakeWatcher()
        f, _, _ = scan(FakeSite(), burst=False, watcher=watcher)
        assert watcher.urls and f["watch"]["pages"], "watched without being asked to"
        watcher = FakeWatcher()
        f, text, _ = scan(FakeSite(), burst=False, watch=False, watcher=watcher)
        assert (f["watch"], watcher.urls) == ({"skipped": "--no-watch"}, [])
        assert "- **What the pages fetch:** not watched (--no-watch)" in text

    def test_chrome_not_there_is_a_note_not_an_error(self):
        f, text, _ = scan(FakeSite(), burst=False)  # scan()'s watcher: no Chrome on this machine
        assert f["watch"] == {"skipped": "Google Chrome is not installed"}
        assert "errors" not in f
        assert "- **What the pages fetch:** not watched (Google Chrome is not installed)" in text

    def test_a_list_the_api_step_asked_is_not_asked_again(self):
        """The home page's script names /api/catalog/products: asked once as a route found, and the watch's call
        to the same address takes that answer."""
        site = FakeSite()
        f, _, _ = scan(site, burst=False, watcher=FakeWatcher())
        probe = f["api"]["probe"]
        assert (probe["url"], probe["kind"], probe["items"]) == (
            f"{BASE}/api/catalog/products?limit=24",
            "products",
            24,
        )
        assert [p for _, _, p in site.asked].count("/api/catalog/products?limit=24") == 1
        replay = f["watch"]["pages"][0]["calls"][0]["replay"]
        assert (replay["works"], replay["items"]) == (True, 24)


@pytest.fixture(scope="module")
def run() -> tuple[dict, str, NuxtSite]:
    """One run against the Nuxt shop, shared by TestNuxtShop."""
    site = NuxtSite()
    f, text, _ = scan(site)
    return f, text, site


class TestNuxtShop:
    """A Nuxt 3 shop: Cloudflare in front, its data on an open API on another host."""

    def test_the_deeper_page_is_a_product_not_a_category(self, run):
        """30 category links with a long number outnumber the 8 product links: the products come first."""
        f, *_ = run
        assert f["page"].startswith(f"{BASE}/products/") and f["page_from"] == "a product link"
        assert (f["product"]["url"], f["product"]["kind"]) == (f["page"], "product")

    def test_the_sample_reads_products_a_listing_names(self, run):
        """8 product links on the home page, the rest from the listing met on the way: 10 product pages."""
        f, text, _ = run
        sample = f["sample"]
        assert (sample["read"], sample["listings"], sample["not_products"]) == (10, [], [])
        assert all("/products/" in r["url"] for r in sample["rows"])
        odd = sum(int(r["url"].split("/mpn-")[1].split("/")[0]) % 2 for r in sample["rows"])
        assert sample["coverage"]["mpn"] == 10 and sample["from_state"] == {"mpn": odd}, "odd pages: in the state only"
        assert sample["traps"] == [], "no 'a part number in the words but not in the data'"
        assert f"**Product sample:** 10 of 10 pages read; mpn 10/10 ({odd} from the page state)" in text

    def test_a_listing_met_in_the_sample_gives_its_products_next(self):
        """No listing met before the sample (the home page's /category is a tree): the first category read in it
        is left out, and its products are read in its place."""
        f, _, _ = scan(NuxtSite(tree=True), burst=False)
        sample = f["sample"]
        assert [r["probe"] for r in f["not_found"]["rows"]] == ["a made-up product", "a made-up path"]
        [listing] = sample["listings"]
        assert listing["url"].startswith(f"{BASE}/category/cat-")
        assert sample["read"] == 10 and all("/products/" in r["url"] for r in sample["rows"])
        assert any(int(r["url"].split("/mpn-")[1].split("/")[0]) >= 10 for r in sample["rows"]), "the listing's"

    def test_listings_and_a_makers_page_are_left_out_of_the_sample(self):
        """Past the products: a brand's listing and a maker's page with words for a part number and no product."""
        f, text, _ = scan(NuxtSite(), burst=False, products=20)
        sample = f["sample"]
        [listing], [maker] = sample["listings"], sample["not_products"]
        assert listing["url"].startswith(f"{BASE}/brands/") and listing["why"] == "a JSON-LD ItemList of 10 Products"
        assert maker == {
            "url": f"{BASE}/manufacturers/maker-0/16910.html",
            "why": "no product of its own, another kind of address",
        }, "the second maker's page is not asked: its family is passed"
        assert (sample["read"], sample["asked"], sample["traps"]) == (18, 20, [])
        assert "18 of 20 pages read (1 listing and 1 page with no product of its own left out)" in text

    def test_the_not_found_probe_makes_up_a_product(self, run):
        f, *_ = run
        made_up = f["not_found"]["rows"][0]
        assert made_up["url"].startswith(f"{BASE}/products/usb-accessories/") and made_up["url"].endswith(
            "/99999999.html"
        )

    def test_the_api_hosts(self, run):
        f, _, site = run
        public, internal = f["api"]["bases"]
        assert (public["url"], public["keys"], public["source"]) == (
            API,
            ["apiHost", "API_HOST"],
            "the Nuxt runtime config",
        )
        assert (public["dns"], public["canonical"]) == ("public", "api.shop.test.w.kunlungr.com")
        assert public["vendors"] == {
            "Alibaba Cloud WAF": ["cookie acw_tc", "cookie cdn_sec_tc"],
            "Alibaba Cloud (CDN)": ["server: Tengine", "CNAME api.shop.test.w.kunlungr.com"],
        }
        assert (internal["url"], internal["dns"]) == (INTERNAL, "none")
        assert site.resolved == ["api.shop.test", "api-noauth.backend.test"]
        assert not [p for _, _, p in site.asked if "api-noauth" in p], "an internal host is never asked"
        assert "Alibaba Cloud WAF" not in f["vendors"], "the API host's front is not the site's"
        assert f["level"]["level"] == 4, "the site's own: Cloudflare's __cf_bm"

    def test_routes_and_a_helper_in_the_bundles(self, run):
        f, *_ = run
        api = f["api"]
        routes = {r["route"]: (r["method"], r["kind"]) for r in api["routes"]}
        assert routes == {
            "/www-api/search/cate-search/get-search-result-v2": ("GET", "lists and search"),
            "/www-api/goods/spu-detail": ("GET", "detail"),
            "/www-api/goods/stock-info": ("POST", "stock and price"),
            "/www-api/cart/add": ("POST", "other"),
            "/catalog-api/nav-cate/get-cate-list": ("GET", "lists and search"),
            "/www-api/search/hot-words": ("GET", "lists and search"),
            "/api/_nuxt_icon/icons.json": ("GET", "other"),
        }, "a menu's link (/about/us) is no route"
        assert api["helpers"] == [{"name": "addAntiSpiderParams", "sets": ["v", "v_", "p"], "in": "Bx1api.js"}]
        assert api["bundles"]["read"] == 4, "the two the pages load, and the two chunks they name"

    def test_a_plain_client_gets_json_served_as_html(self, run):
        """The search answers a 200 with a message asking for a category or a search word: asked once more with
        the product page's part number, it gives its list."""
        f, _, site = run
        probe = f["api"]["probe"]
        route = f"{API}/www-api/search/cate-search/get-search-result-v2"
        held = f["product"]["jsonld"].get("mpn") or f["product"]["state"]["product"]["fields"]["mpn"]
        assert (probe["url"], probe["filled"]) == (f"{route}?keyword={held}", {"keyword": held})
        assert (probe["json"], probe["json_as"], probe["kind"], probe["path"], probe["items"]) == (
            True,
            "text/html",
            "products",
            "result.pageOfItems",
            25,
        )
        [bare] = probe["others"]
        assert (bare["url"], bare["error"], bare["message"]) == (route, True, "Either cate_id or keyword is required.")
        asked = [p for _, _, p in site.asked]
        assert asked.count(route) == 1 and asked.count(probe["url"]) == 1
        assert not [p for p in asked if "cart/add" in p or "stock-info" in p], "a POST route is never asked"
        assert f["refused_elsewhere"] == {}

    def test_an_error_message_is_said_to_be_one(self):
        """The search asks for a token recon has not: no value is filled in, and the verdict says it got an error
        message, not data; nor does it say the API answered without the helper's parameters."""
        f, text, _ = scan(NuxtSite(token=True), burst=False, products=0)
        probe = f["api"]["probe"]
        assert (probe["error"], probe["message"], probe.get("filled")) == (True, "token is required", None)
        assert "a plain client got JSON from a list route (an error message, not data: token is required)" in text
        assert "answered without them" not in text
        assert len(probe["others"]) == 2, "the other list routes, on the API host that answered"

    def test_a_part_number_searched_to_its_one_product(self):
        """The search gives the part number's one product: data, not a list, and the verdict says with what it
        was asked and what it said without it."""
        f, text, _ = scan(NuxtSite(exact=True), burst=False, products=0)
        probe = f["api"]["probe"]
        held = f["product"]["jsonld"].get("mpn") or f["product"]["state"]["product"]["fields"]["mpn"]
        assert (probe["kind"], probe["error"], probe["filled"]) == ("data", False, {"keyword": held})
        assert (
            f"a plain client got JSON from a list route (data, no product list, with keyword={held}; without it, an"
            " error message: Either cate_id or keyword is required.)" in text
        )
        assert "answered without them" not in text

    def test_the_page_state(self, run):
        f, *_ = run
        states = {s["page"]: s for s in f["api"]["state"]}
        listed = states["listing"]["lists"][0]
        assert listed["path"] == 'data["third-cate-/category/cat-0/070400.html"].pageOfItems'
        assert (listed["items"], listed["counts"], listed["mpn_key"]) == (
            25,
            {"resultTotal": 413, "pageSize": 25},
            "pro_sno",
        )
        held = states["product"]["product"]
        assert held["path"].endswith(".goodsDetail") and held["mpn_key"] == "pro_sno"

    def test_the_verdict(self, run):
        f, text, _ = run
        held = f["api"]["probe"]["filled"]["keyword"]
        assert (
            f"- **API:** `{API}` (Alibaba Cloud WAF, Alibaba Cloud (CDN) in front, not what the site has: its"
            " protection is its own); 1 internal, never asked; a plain client got JSON from a list route (a product"
            f" list of 25, with keyword={held}; without it, an error message: Either cate_id or keyword is required.)"
            in text
        )
        assert f"`keyword` filled in with {held}, which the run had" in text
        assert f"  - `{INTERNAL}`: `serverApiHost`, `SERVER_API_HOST` in the Nuxt runtime config; no public DNS" in text
        assert "`addAntiSpiderParams` (it sets v, v_, p), in Bx1api.js; the API answered without them" in text
        assert "- **Page state:** Nuxt 3 __NUXT_DATA__: the listing page's" in text
        assert "redirected: /sitemap-index.xml 301 -> /nuxt-sitemaps/sitemap-prod-index.xml 404" in text
        assert "## The site's own API, without a browser" in text

    def test_bundles_a_cdn_serves_are_read(self):
        """Nuxt's cdnURL: the bundles under /_nuxt/ on a static host; its robots.txt asked first, once."""
        site = NuxtSite(cdn=True)
        f, _, _ = scan(site, burst=False, products=0)
        bundles = f["api"]["bundles"]
        assert (bundles["read"], bundles["hosts"]) == (4, {"static.shop.test": "not there"})
        assert next(p for _, _, p in site.asked if p.startswith(CDN)) == f"{CDN}/robots.txt"
        assert [p for _, _, p in site.asked].count(f"{CDN}/robots.txt") == 1
        assert len(f["api"]["routes"]) == 7
        assert "static.shop.test" not in json.dumps(f["vendors"]), "another host's answers are not the site's"

    def test_bundles_on_internal_hosts_are_never_asked(self):
        """Scripts on localhost, a private address and the servers' own API host, each named a CDN by a runtime
        config, and one on a host of the site's domain that resolves to a private address: neither the file nor
        the host's robots.txt is asked. Another site's /_nuxt/ is not the shop's: not asked either."""
        head = (
            '<script src="http://localhost:3000/_nuxt/a.js"></script><script src="http://10.1.2.3/_nuxt/b.js">'
            f'</script><script src="{INTERNAL}/_nuxt/c.js"></script>'
            '<script src="https://assets.shop.test/_nuxt/d.js"></script>'
            '<script src="https://cdn.other.test/_nuxt/e.js"></script>'
            '<script>window.a={cdnURL:"http://localhost:3000"};window.b={cdnURL:"http://10.1.2.3"};'
            f'window.c={{cdnURL:"{INTERNAL}"}}</script>'
        )
        dns = {**API_DNS, "assets.shop.test": {"addresses": ["10.0.0.9"]}, "cdn.other.test": {"addresses": ["8.8.8.8"]}}
        site = NuxtSite(head=head, dns=dns)
        f, text, _ = scan(site, burst=False, products=0)
        bundles = f["api"]["bundles"]
        assert set(bundles["internal"]) == {"localhost", "10.1.2.3", "api-noauth.backend.test", "assets.shop.test"}
        hosts = ("localhost", "10.1.2.3", "api-noauth", "assets.shop.test", "other.test")
        assert not [p for _, _, p in site.asked if any(h in p for h in hosts)], "no robots.txt, no file"
        assert "localhost" not in site.resolved and "10.1.2.3" not in site.resolved, "internal by its name alone"
        assert site.resolved.count("api-noauth.backend.test") == 1, "looked up once, as an API base and a CDN"
        assert "cdn.other.test" not in site.resolved
        assert bundles["read"] == 4 and "on internal hosts not asked (" in text

    def test_routes_are_asked_on_the_shops_own_api_first(self):
        """A payment service's paymentApiUrl named before the shop's apiHost, and its /_nuxt/ script: its
        robots.txt is asked, as every public API host's is, and nothing more of it."""
        head = (
            '<script>window.pay={paymentApiUrl:"https://pay.vendor.test"}</script>'
            '<script src="https://pay.vendor.test/_nuxt/pay.js"></script>'
        )
        site = NuxtSite(head=head, dns={**API_DNS, "pay.vendor.test": {"addresses": ["8.8.4.4"]}})
        f, _, _ = scan(site, burst=False, products=0)
        assert [b["url"] for b in f["api"]["bases"]] == ["https://pay.vendor.test", API, INTERNAL]
        assert f["api"]["probe"]["url"].startswith(f"{API}/www-api/search/")
        assert [p for _, _, p in site.asked if "pay.vendor.test" in p] == ["https://pay.vendor.test/robots.txt"]

    def test_the_listing_read_is_one_that_lists(self):
        """No listing met before the API step: of the product page's category links, its own category (the
        deepest) is read and found to list products, not the top of the tree; the watch opens it too."""
        site, watcher = NuxtSite(tree=True), FakeWatcher()
        f, _, _ = scan(site, burst=False, products=0, watcher=watcher)
        listing = next(s for s in f["api"]["state"] if s["page"] == "listing")
        assert listing["url"] == f"{BASE}/category/usb-accessories/070403.html"
        assert listing["lists"][0]["counts"] == {"resultTotal": 413, "pageSize": 25}
        assert watcher.urls[2] == listing["url"]
        assert "/category/usb.html" not in [p for _, _, p in site.asked]

    def test_bundles_robots_txt_keeps_out_are_not_read(self):
        site = NuxtSite(disallow="/_nuxt/")
        f, _, _ = scan(site, burst=False, products=0)
        assert (f["api"]["bundles"]["read"], f["api"]["bundles"]["disallowed"]) == (0, 2)
        assert not [p for _, _, p in site.asked if p.startswith("/_nuxt/")]


def test_a_sitemap_behind_a_redirect_is_followed_and_named():
    """/sitemap-index.xml redirects into a folder, to a file not there; the same name in that folder is the index."""
    site = FakeSite(sitemap_moved=True)
    f, text, _ = scan(site, burst=False)
    moved = next(x for x in f["sitemap"]["files"] if x["url"] == f"{BASE}/sitemap-index.xml")
    assert moved["chain"] == [
        {"url": f"{BASE}/sitemap-index.xml", "status": 301},
        {"url": f"{BASE}/maps/sitemap-prod-index.xml", "status": 404},
    ]
    assert (f["sitemap"]["addresses"], f["sitemap"]["files_read"], f["sitemap"]["asked"]) == (40, 3, 8)
    assert [p for _, _, p in site.asked if "sitemap" in p][3:6] == [
        "/sitemap-index.xml",
        "/maps/sitemap-prod-index.xml",
        "/maps/sitemap-index.xml",
    ]
    assert "redirected: /sitemap-index.xml 301 -> /maps/sitemap-prod-index.xml 404" in text
    assert f["sitemap"]["files_left"] == 0, "the guesses not asked are no files named"


def test_a_sitemap_redirect_to_another_site_is_named_not_followed():
    class Away(FakeSite):
        def answer(self, client, url, headers):
            if url == f"{BASE}/sitemap.xml":
                return Answer(url, 301, {"location": "https://cdn.other.test/sitemap.xml"}, (), b"", 0.01)
            return super().answer(client, url, headers)

    site = Away()
    f, _, _ = scan(site, burst=False)
    [moved] = f["sitemap"]["files"]
    assert moved["chain"][-1] == {"url": "https://cdn.other.test/sitemap.xml", "status": None, "why": "another site"}
    assert not [p for _, _, p in site.asked if "other.test" in p]


def test_sitemap_guessed_when_robots_names_none():
    site = FakeSite(sitemap_at="/xmlsitemap.php")
    f, text, _ = scan(site, burst=False)
    assert (f["sitemap"]["addresses"], f["sitemap"]["files_read"], f["sitemap"]["asked"]) == (40, 3, 5)
    assert "40 addresses in 3 files read (5 addresses asked, guesses and redirects among them)" in text
    assert [p for _, _, p in site.asked if "sitemap" in p][:3] == [
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/xmlsitemap.php",
    ]

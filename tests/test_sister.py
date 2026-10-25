"""A shop on two hosts of one domain, as an electronics marketplace was seen to be: its search host sends its home
page to www, where its product pages and sitemaps are; a doT template's text sits in a link; a GeeTest overlay and
NetEase's captcha script are wired into its pages without firing; its robots.txt keeps crawlers off every address
with a query; its WAF refuses a guessed sitemap; its llms.txt is there. Then Alibaba Cloud's captcha page, and its
CDN refusing this machine's country."""

import asyncio
from typing import Any

from fakes import PRODUCT, FakeBrowser, FakeClient, FakeSite, FakeWatcher

from recon.classify import judge, region_block, vendors_of, wired_in
from recon.clients import Answer
from recon.probe import Recon
from recon.report import report

SEARCH, WWW = "https://search.twin.test", "https://www.twin.test"
GIVEN = f"{SEARCH}/?keyword=STM32F103C8T6"
WIRED = (
    '<!--搜索频控防抓服务--><script src="https://static.geetest.com/static/tools/gt.js"></script>'
    '<script>var gt_type = "search_crawl";</script>'
    '<script src="https://cstaticdun.126.net/load.min.js"></script><script>window.NECaptchaValidate = 1;</script>'
)
WWW_HOME = (
    "<html><head><title>Twin</title></head><body>"
    '<a href="/{{! firstPdfUrl}}">pdf</a>'
    + "".join(f'<a href="/detail/10003{n:05d}/PN{n}.html">p{n}</a>' for n in range(1, 31))
    + WIRED
    + "</body></html>"
)
SEARCH_PAGE = (
    "<html><head><title>STM32F103C8T6</title></head><body>"
    + "".join(f'<a href="{WWW}/detail/10003{n:05d}/PN{n}.html">p{n}</a>' for n in range(1, 13))
    + WIRED
    + "</body></html>"
)
ALIYUN_CAPTCHA = (
    b'<!doctype html><html><head><meta name="aliyun_waf_aa" content="1"><meta name="aliyun_waf_bb" content="2">'
    b"<title>\xe8\xae\xbf\xe9\x97\xae\xe9\xaa\x8c\xe8\xaf\x81</title></head>"
    b'<body><div id="aliyunCaptcha-sliding-slider"></div></body></html>'
)
WAF_405 = b"<html><head><title>405</title></head><body>errors.aliyun.com _waf_ request id</body></html>"


class TwinSite(FakeSite):
    """search.twin.test and www.twin.test, behind Alibaba Cloud; `region` refuses every request as its CDN refuses
    a country."""

    def __init__(self, region: bool = False, **kw: Any) -> None:
        super().__init__(**kw)
        self.region = region

    def answer(self, client: FakeClient, url: str, headers: dict) -> Answer:
        h = {"server": "Tengine", "eagleid": "x", "via": "ens-cache21.de5"}
        cookies = ("acw_tc",)
        if self.region:
            body = b"<html><head><title>403 Forbidden</title></head></html>"
            return Answer(url, 403, {**h, "x-tengine-error": "denied by region_block"}, cookies, body, 0.01)
        host, _, rest = url.removeprefix("https://").partition("/")
        path, _, query = ("/" + rest).partition("?")
        if path == "/robots.txt":
            return Answer(url, 200, h, cookies, b"User-agent: *\nDisallow: /*?*\n", 0.01)
        if host == "search.twin.test":
            if path == "/" and not query:
                return Answer(url, 302, {**h, "location": f"{WWW}/"}, cookies, b"", 0.01)
            if path == "/" and query.startswith("keyword="):
                return Answer(url, 200, {**h, "content-type": "text/html"}, cookies, SEARCH_PAGE.encode(), 0.01)
            return Answer(url, 404, h, cookies, b"<title>404</title>", 0.01)
        if path == "/":
            return Answer(url, 200, {**h, "content-type": "text/html"}, cookies, WWW_HOME.encode(), 0.01)
        if path == "/llms.txt":
            return Answer(url, 200, {**h, "content-type": "text/plain"}, cookies, b"# Twin parts\n> search", 0.01)
        if path == "/sitemap.xml.gz":
            return Answer(url, 405, {**h, "content-type": "text/html"}, cookies, WAF_405, 0.01)
        if path.startswith("/detail/"):
            n = int(path.split("/")[2][-5:])
            body = PRODUCT.format(name=f"Part {n}", n=n).encode()
            return Answer(url, 200, {**h, "content-type": "text/html"}, cookies, body, 0.01)
        return Answer(url, 404, h, cookies, b"<title>404</title>", 0.01)


def run(site: FakeSite, url: str, **kw: Any) -> tuple[dict, str]:
    """(findings, the report) of a whole run of recon on `url` of `site`."""

    def make(kind: str, ua: str | None = None, cookies: bool = False) -> FakeClient:
        return FakeClient(site, kind, ua, cookies)

    kw.setdefault("pause", 0)
    kw.setdefault("burst", False)
    kw.setdefault("watcher", FakeWatcher(missing=True))
    kw.setdefault("resolve", site.resolve)
    f = asyncio.run(Recon(url, make=make, browse=FakeBrowser(), **kw).run())
    return f, report(f)


def asked(site: FakeSite) -> list[str]:
    return [url for _, _, url in site.asked]


def test_a_home_page_sent_to_another_host_of_its_domain_is_followed_there():
    site = TwinSite()
    f, text = run(site, f"{SEARCH}/")
    assert "stopped" not in f, "one site on two hosts: not 'another site'"
    assert f["home"] == f"{WWW}/"
    assert f["home_redirect"] == f"302 to {WWW}/: followed, another host of the same site"
    assert f"{WWW}/robots.txt" in asked(site), "robots.txt read where the run went on"
    assert f["product"]["found"] and f["product"]["url"].startswith(f"{WWW}/detail/")
    assert f"- The home page redirects 302 to {WWW}/: followed, another host of the same site" in text


def test_a_template_s_text_is_no_link():
    site = TwinSite()
    f, _ = run(site, f"{SEARCH}/")
    assert "{{" not in (f["page"] or ""), "the deeper page is a real product"
    assert not any("{{" in u or "firstPdfUrl" in u for u in asked(site)), "nothing asked of /{{! firstPdfUrl}}"


def test_the_page_given_is_judged_by_robots_txt_and_watched_all_the_same():
    site, watcher = TwinSite(), FakeWatcher()
    f, text = run(site, GIVEN, watcher=watcher)
    assert f["robots"]["given_disallowed"] == {GIVEN: "Disallow: /*?*"}
    assert watcher.urls[0] == GIVEN, "Chrome opens the page given first"
    assert f["watch"]["given_disallowed"] == GIVEN
    assert "- **robots.txt disallows the page given:** /?keyword=STM32F103C8T6 (Disallow: /*?*)." in text


def test_product_links_on_another_host_of_the_site_are_named():
    f, text = run(TwinSite(), GIVEN)
    assert f["sister_products"] == {"www.twin.test": 12}
    assert "  - product links lead to another host of the same site: www.twin.test (12 links)" in text


def test_a_guessed_sitemap_its_waf_refuses_is_no_refusal_of_the_site():
    f, text = run(TwinSite(), f"{SEARCH}/")
    files = {s["url"]: s for s in f["sitemap"]["files"]}
    assert files[f"{WWW}/sitemap.xml.gz"]["verdict"] == "blocked", "said as it answered"
    assert "sitemaps" not in f["refused_elsewhere"]
    assert "refused in other steps" not in text


def test_captchas_wired_into_the_pages_are_named_though_none_fired():
    f, text = run(TwinSite(), f"{SEARCH}/")
    assert f["wired"]["GeeTest"][0] == "the home page"
    assert "NetEase Yidun" in f["wired"]
    assert f["level"]["level"] == 1, "a captcha wired in is no refusal: the level is what the run met"
    assert "- **Captchas and bot checks wired in:** GeeTest (the home page" in text


def test_llms_txt_is_read():
    f, text = run(TwinSite(), f"{SEARCH}/")
    assert f["llms"] == {"there": True, "status": 200, "bytes": 21, "first": "# Twin parts"}
    assert "- llms.txt: 200, 21 bytes, first line: # Twin parts" in text


def test_a_country_refused_by_the_cdn_is_said_with_what_to_do():
    f, text = run(TwinSite(region=True), f"{WWW}/")
    assert f["region_block"].startswith("X-Tengine-Error: denied by region_block, on ")
    assert "- **Region block:** the site refuses the country this machine is in" in text
    assert "run recon, and a scraper, from another" in text
    assert "given_disallowed" not in f["robots"], "a refused robots.txt names no rule of the site's"
    assert "robots.txt disallows the page given" not in text


def test_alibaba_s_captcha_page_is_a_challenge():
    a = Answer(f"{WWW}/api", 200, {"server": "Tengine", "content-type": "text/html"}, ("acw_tc",), ALIYUN_CAPTCHA)
    assert judge(a) == ("challenge", "Alibaba Cloud WAF")
    assert "its captcha page (aliyun_waf_aa)" in vendors_of([a])["Alibaba Cloud WAF"]


def test_a_region_block_is_alibaba_s_refusal():
    a = Answer(f"{WWW}/", 403, {"x-tengine-error": "denied by region_block"}, (), b"<title>403 Forbidden</title>")
    assert judge(a) == ("blocked", "Alibaba Cloud WAF")
    assert region_block([a, Answer(f"{WWW}/x", 200)]) == "X-Tengine-Error: denied by region_block, on 1 answers"
    assert region_block([Answer(f"{WWW}/x", 200)]) is None


def test_wired_in_names_each_service_once():
    assert wired_in(WIRED) == ["GeeTest", "NetEase Yidun"]
    assert wired_in("if (navigator.webdriver) { report() }") == ["a webdriver check"]
    assert wired_in("<script src='https://www.google.com/recaptcha/api.js'></script>") == ["reCAPTCHA"]
    assert wired_in("<p>no checks here</p>") == []

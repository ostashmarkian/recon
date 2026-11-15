"""The terms of use: the link to them, and what they say of a pace and of robots, crawlers and scraping."""

from fakes import BASE, FakeSite, scan

from recon.clients import Answer
from recon.terms import terms_links, terms_said

# ICKey's user agreement, §四, as its pages print it (2026-10-22)
AGREEMENT = (
    "<h3>四、禁止行为</h3><p>（1）违反本网站 robots.txt 或 llms.txt 协议的声明；</p>"
    "<p>（2）伪造 User-Agent 信息使自动化程序假冒普通浏览器用户；</p>"
    "<p>（3）超出合理速率限制进行高频请求，包括但不限于每秒超过 2 次请求，或使用代理池、分布式 IP；</p>"
    "<p>（4）以商业竞争、恶意比价、破坏商业秩序为目的批量抓取价格、库存、客户数据；</p>"
)
TERMS = (
    "<html><head><title>Terms of Use</title></head><body><h1>Terms of Use</h1>"
    "<p>You may browse the catalogue for your own purchases.</p>"
    "<p>You may not use any robot, spider, scraper or other automated means to access the site.</p>"
    "<p>Automated clients must not send more than 1 request per second.</p></body></html>"
)


def test_the_links_by_their_words_then_their_address():
    html = (
        '<a href="/privacy-policy/">Privacy</a><a href="/content/agr.html">用户协议</a>'
        '<a href="/legal/terms-of-sale/">x</a><a href="/cookie-terms/">Cookies</a>'
        '<a href="/{{! termsUrl}}">Terms</a><a href="/content/agr.html">再次</a>'
    )
    assert terms_links(html, "https://www.shop.test/") == [
        "https://www.shop.test/content/agr.html",
        "https://www.shop.test/legal/terms-of-sale/",
    ], "a privacy or cookie page is none, nor a template's text; each once"


def test_a_category_named_by_a_protocol_is_no_agreement():
    """协议 is a protocol too: an electronics shop's category of interface chips is not its terms."""
    html = (
        '<a href="https://search.shop.test/cate-search?cate_id=260114">通信协议</a>'
        '<a href="/content/agr.html">服务协议</a><a href="/legal.html">法律声明</a>'
    )
    assert terms_links(html, "https://www.shop.test/") == [
        "https://www.shop.test/content/agr.html",
        "https://www.shop.test/legal.html",
    ]


def test_a_pace_and_scraping_as_written():
    said = terms_said(AGREEMENT)
    assert said["rate"] == [
        "（3）超出合理速率限制进行高频请求，包括但不限于每秒超过 2 次请求，或使用代理池、分布式 IP；"
    ]
    assert said["bots_count"] == 3, "robots.txt, an automated program, bulk scraping"
    assert any("批量抓取" in q for q in said["bots"])
    english = terms_said(TERMS)
    assert english["rate"] == ["Automated clients must not send more than 1 request per second."]
    assert english["bots"] == [
        "You may not use any robot, spider, scraper or other automated means to access the site."
    ]


def test_a_long_sentence_is_quoted_around_what_it_says():
    sentence = "x" * 400 + " no scraping of this site " + "y" * 400
    q = terms_said(f"<p>{sentence}.</p>")["bots"][0]
    assert "scraping" in q and q.startswith("…") and q.endswith("…") and len(q) <= 242


class TermsSite(FakeSite):
    def answer(self, client, url, headers):
        if url.removeprefix(BASE) == "/terms-of-use/":
            return Answer(url, 200, {"server": "nginx"}, (), TERMS.encode(), 0.01)
        return super().answer(client, url, headers)


FOOTER = '<footer><a href="/terms-of-use/">Terms of Use</a><a href="/privacy/">Privacy policy</a></footer>'


def test_the_terms_in_the_report():
    site = TermsSite(home_extra=FOOTER)
    f, text, _ = scan(site, burst=False, products=0)
    [page] = f["terms"]["pages"]
    assert (page["url"], page["rate_count"], page["bots_count"]) == (f"{BASE}/terms-of-use/", 1, 1)
    assert "/privacy/" not in [p for _, _, p in site.asked]
    assert (
        "- **Terms:** /terms-of-use/: a pace, “Automated clients must not send more than 1 request per second.”;"
        " robots, crawlers or scraping in 1 sentence(s), “You may not use any robot" in text
    )
    assert "## Terms of use, as written" in text


def test_terms_robots_txt_disallows_are_not_read():
    site = TermsSite(home_extra=FOOTER, disallow="/terms-of-use/")
    f, text, _ = scan(site, burst=False, products=0)
    assert f["terms"]["pages"] == [{"url": f"{BASE}/terms-of-use/", "skipped": "robots.txt disallows it"}]
    assert "/terms-of-use/" not in [p for _, _, p in site.asked]
    assert "- **Terms:** /terms-of-use/: not read (robots.txt disallows it)" in text


class LegalHost(FakeSite):
    """Its terms on another host of its domain, whose robots.txt and terms page both moved."""

    def answer(self, client, url, headers):
        legal = "https://legal.shop.test"
        moved = {f"{legal}/robots.txt": f"{legal}/robots-2.txt", f"{legal}/tos": f"{legal}/terms-of-use"}
        if url in moved:
            return Answer(url, 301, {"location": moved[url]}, (), b"", 0.01)
        if url == f"{legal}/robots-2.txt":
            return Answer(url, 200, {}, (), b"User-agent: *\nDisallow: /private/\n", 0.01)
        if url == f"{legal}/terms-of-use":
            return Answer(url, 200, {}, (), TERMS.encode(), 0.01)
        return super().answer(client, url, headers)


LEGAL = '<a href="https://legal.shop.test/tos">Terms and conditions</a>'


def test_redirects_of_another_host_s_robots_txt_and_terms_are_followed():
    site = LegalHost(home_extra=LEGAL, dns={"legal.shop.test": {"addresses": ["93.184.216.34"]}})
    f, _, _ = scan(site, burst=False, products=0)
    [page] = f["terms"]["pages"]
    assert (page["url"], page["rate_count"]) == ("https://legal.shop.test/terms-of-use", 1)
    assert "legal.shop.test" in site.resolved, "looked up in DNS first"


def test_a_host_with_no_public_dns_is_never_asked():
    site = LegalHost(home_extra=LEGAL)
    f, text, _ = scan(site, burst=False, products=0)
    assert f["terms"]["pages"] == [
        {"url": "https://legal.shop.test/tos", "skipped": "its host has no public DNS: never asked"}
    ]
    assert not [p for _, _, p in site.asked if "legal.shop.test" in p], "not even its robots.txt"
    assert "- **Terms:** /tos: not read (its host has no public DNS: never asked)" in text


def test_a_refusal_of_the_site_s_own_terms_keeps_the_burst_off():
    class Refusing(TermsSite):
        def answer(self, client, url, headers):
            if url.endswith("/terms-of-use/"):
                return Answer(url, 403, {"server": "nginx"}, (), b"<title>Forbidden</title>", 0.01)
            return super().answer(client, url, headers)

    f, _, _ = scan(Refusing(home_extra=FOOTER), products=0)
    assert f["refused_elsewhere"] == {"terms": {"refused": 1}}
    assert "skipped" in f["burst"]


def test_no_link_is_said():
    f, text, _ = scan(FakeSite(), burst=False, products=0)
    assert f["terms"]["pages"] == [] and "- **Terms:** no link to terms of use on the home page" in text

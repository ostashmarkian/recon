"""judge() and vendors_of(): what an answer says, and what stands in front."""

import pytest
from fakes import CHALLENGE

from recon.classify import GUARDS, cname_vendor, judge, passes, vendors_of
from recon.clients import Answer

ANSWERS = [
    ("Cloudflare's challenge header", Answer("u", 403, {"cf-mitigated": "challenge"}), "challenge"),
    ("Cloudflare's challenge page", Answer("u", 503, {"server": "cloudflare"}, (), CHALLENGE.encode()), "challenge"),
    (
        "Cloudflare's script on a normal 200 is no challenge",
        Answer("u", 200, {"server": "cloudflare"}, (), b"<script src='/cdn-cgi/challenge-platform/x.js'>"),
        "ok",
    ),
    (
        "Cloudflare's block page (its AI-bot rule)",
        Answer("u", 403, {"server": "cloudflare"}, (), b"Your request was blocked."),
        "blocked",
    ),
    ("Akamai", Answer("u", 403, {"server": "AkamaiGHost"}, (), b"Access Denied"), "blocked"),
    (
        "Akamai's page, its markers written as HTML entities",
        Answer(
            "u",
            403,
            {"content-type": "text/html"},
            (),
            b"<TITLE>Access Denied</TITLE>Reference&#32;&#35;18&#46;7f0c<P>https&#58;&#47;&#47;errors&#46;edgesuite"
            b"&#46;net&#47;18</P>",
        ),
        "blocked",
    ),
    ("CloudFront WAF", Answer("u", 403, {"server": "CloudFront"}, (), b"Request blocked."), "blocked"),
    ("AWS WAF captcha", Answer("u", 202, {"x-amzn-waf-action": "captcha"}), "challenge"),
    ("DataDome", Answer("u", 403, {}, (), b"geo.captcha-delivery.com"), "challenge"),
    ("Imperva on a 200", Answer("u", 200, {}, (), b"<iframe src='/_Incapsula_Resource?x'>"), "challenge"),
    (
        "a block dressed as a 302 to an error403 page",
        Answer("u", 302, {"location": "/CustomError/error403.html"}),
        "blocked",
    ),
    ("a plain redirect", Answer("u", 301, {"location": "https://www.x/"}), "redirect"),
    ("429", Answer("u", 429, {"retry-after": "60"}), "limited"),
    ("plain 403", Answer("u", 403, {}, (), b"<title>Forbidden</title>"), "refused"),
    ("a connection closed with no answer", Answer("u", error="RemoteProtocolError: Server disconnected"), "dropped"),
    (
        "curl 92: an HTTP/2 stream reset",
        Answer("u", error="CurlError: curl: (92) HTTP/2 stream 1 was not closed"),
        "dropped",
    ),
    ("a timeout is no refusal", Answer("u", error="ReadTimeout: timed out"), "error"),
    ("404", Answer("u", 404), "gone"),
    ("400 is the client's error, not ok", Answer("u", 400), "client-error"),
    ("422 too", Answer("u", 422), "client-error"),
    ("408 is a lost answer", Answer("u", 408), "error"),
    ("a redirect to a product whose id holds 403", Answer("u", 301, {"location": "/product/14032/"}), "redirect"),
    ("a redirect on a host named ...block...", Answer("u", 302, {"location": "https://glassblock.test/x"}), "redirect"),
    ("a redirect to a captcha page", Answer("u", 302, {"location": "/captcha/?from=/"}), "blocked"),
    (
        "Imperva's script on a normal page",
        Answer("u", 200, {}, (), b"<script src='/_Incapsula_Resource?x'></script>" + b"<p>a shop page</p>" * 1000),
        "ok",
    ),
    ("x-datadome on a 404", Answer("u", 404, {"x-datadome": "protected"}), "gone"),
    ("Imperva's script on a small 404", Answer("u", 404, {}, (), b"<script src='/_Incapsula_Resource?x'>"), "gone"),
    ("524", Answer("u", 524), "server-error"),
    (
        "Myra's ban: a 503 to /myracloud-blocked/",
        Answer("u", 503, {"server": "myracloud", "location": "/myracloud-blocked/?r=1"}),
        "blocked",
    ),
    (
        "Myra's captcha",
        Answer("u", 503, {"server": "myracloud"}, (), b"<title>Security Check</title><a href='/myracloud-captcha/'>"),
        "challenge",
    ),
    (
        "a plain 503 from the shop behind Myra",
        Answer("u", 503, {"server": "myracloud"}, (), b"<title>Service Unavailable</title>"),
        "server-error",
    ),
]


@pytest.mark.parametrize(("answer", "verdict"), [pytest.param(a, v, id=name) for name, a, v in ANSWERS])
def test_judge(answer: Answer, verdict: str) -> None:
    assert judge(answer)[0] == verdict


def test_a_client_error_is_not_let_in() -> None:
    assert not passes("client-error")
    assert passes("gone") and passes("redirect")


def test_judge_names_retry_after() -> None:
    assert judge(Answer("u", 429, {"retry-after": "60"}))[1] == "Retry-After 60"


def test_myra_is_named_and_a_guard() -> None:
    """Myra lets the first requests in and bans the whole IP minutes later: in front, it is protection."""
    banned = Answer("u", 503, {"server": "myracloud", "location": "/myracloud-blocked/?r=1"})
    assert judge(banned) == ("blocked", "Myra Security")
    assert vendors_of([Answer("u", 200, {"server": "myracloud"})]) == {"Myra Security": ["server: myracloud"]}
    assert "Myra Security" in GUARDS


def test_vendors_of() -> None:
    seen = vendors_of(
        [
            Answer("u", 200, {"server": "cloudflare", "cf-ray": "x"}, ("__cf_bm",)),
            Answer("u", 200, {"x-amz-cf-id": "x"}, ("_abck",)),
            Answer("u", 200, {}, ("TS01a2b3c4",)),
            Answer("u", error="ReadTimeout"),
        ]
    )
    assert sorted(seen) == ["Akamai", "CloudFront (CDN)", "Cloudflare", "F5 BIG-IP ASM"]
    assert seen["Cloudflare"] == ["cf-ray", "server: cloudflare", "cookie __cf_bm"]
    assert "CloudFront (CDN)" not in GUARDS, "a CDN is not a guard"


def test_alibaba_cloud_in_front_of_an_api_host() -> None:
    """The WAF's cookies make it a guard; the CDN alone (Tengine with EagleId, ens-cache) is none."""
    seen = vendors_of([Answer("u", 200, {"server": "Tengine"}, ("acw_tc", "cdn_sec_tc"))])
    assert seen == {
        "Alibaba Cloud WAF": ["cookie acw_tc", "cookie cdn_sec_tc"],
        "Alibaba Cloud (CDN)": ["server: Tengine"],
    }
    edge = vendors_of([Answer("u", 200, {"server": "Tengine", "eagleid": "x", "via": "cache1.l2, ens-cache3"})])
    assert edge == {"Alibaba Cloud (CDN)": ["eagleid", "via: ens-cache", "server: Tengine"]}
    assert vendors_of([Answer("u", 200, {"server": "Tengine"})]) == {}, "Tengine alone is any nginx fork's"
    assert "Alibaba Cloud WAF" in GUARDS and "Alibaba Cloud (CDN)" not in GUARDS


def test_alibaba_cloud_challenge_and_block() -> None:
    challenge = (
        b"<html><script>var arg1='3E40C5';setTimeout(function(){document.cookie='acw_sc__v2='+x;"
        b"location.reload()},0)</script></html>"
    )
    page = Answer("u", 200, {"server": "Tengine"}, ("acw_tc",), challenge)
    assert judge(page) == ("challenge", "Alibaba Cloud WAF")
    assert "the acw_sc__v2 challenge" in vendors_of([page])["Alibaba Cloud WAF"]
    blocked = Answer("u", 405, {}, (), b"<html>... _waf_bd8ce2ce37 ... errors.aliyun.com ...</html>")
    assert judge(blocked) == ("blocked", "Alibaba Cloud WAF")
    big = Answer("u", 200, {}, (), b"acw_sc__v2" + b"<p>a page</p>" * 5_000)
    assert judge(big)[0] == "ok", "a page that only names the cookie is no challenge"


def test_who_a_cname_names() -> None:
    assert cname_vendor("api.shop.test.w.kunlungr.com") == (
        "Alibaba Cloud (CDN)",
        "CNAME api.shop.test.w.kunlungr.com",
    )
    assert cname_vendor("x.cdn.cloudflare.net.")[0] == "Cloudflare (CDN)"  # type: ignore[index]
    assert cname_vendor("dualstack.python.map.fastly.net")[0] == "Fastly (CDN)"  # type: ignore[index]
    assert cname_vendor("api.shop.test") is None and cname_vendor(None) is None

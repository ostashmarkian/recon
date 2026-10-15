"""judge() and vendors_of(): what an answer says, and what stands in front."""

import pytest
from fakes import CHALLENGE

from recon.classify import GUARDS, judge, vendors_of
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
    ("524", Answer("u", 524), "server-error"),
]


@pytest.mark.parametrize(("answer", "verdict"), [pytest.param(a, v, id=name) for name, a, v in ANSWERS])
def test_judge(answer: Answer, verdict: str) -> None:
    assert judge(answer)[0] == verdict


def test_judge_names_retry_after() -> None:
    assert judge(Answer("u", 429, {"retry-after": "60"}))[1] == "Retry-After 60"


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

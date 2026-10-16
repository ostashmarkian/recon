"""What an answer says - a verdict (ok, a refusal, no answer) and who gave
it - and which services stand in front of a site."""

import html as entities
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from .clients import Answer
from .pages import TITLE

REFUSALS = ("challenge", "blocked", "refused", "limited")


LOST = ("dropped", "error")


# An answer cut off rather than refused: the connection closed or reset
# (httpx's names, curl's codes 16, 35, 52, 55, 56, 92). Some nginx setups drop Scrapy so.
DROPS = (
    "RemoteProtocolError",
    "ReadError",
    "WriteError",
    "Server disconnected",
    "ConnectionTerminated",
    "StreamReset",
    "Connection reset",
    "curl: (16)",
    "curl: (35)",
    "curl: (52)",
    "curl: (55)",
    "curl: (56)",
    "curl: (92)",
)


# Services that refuse or challenge by themselves, and can shut an IP out:
# one in front counts as protection even when it let every probe through.
GUARDS = (
    "Cloudflare",
    "Akamai",
    "Imperva",
    "DataDome",
    "HUMAN (PerimeterX)",
    "Sucuri",
    "Kasada",
    "F5 BIG-IP ASM",
    "AWS WAF",
    "Vercel Firewall",
    "Myra Security",
)


F5_COOKIE = re.compile(r"TS[0-9a-f]{6,}$")


# A redirect that is a block: a path segment naming one, as /CustomError/error403.html or /captcha/?from=...
BLOCK_REDIRECT = re.compile(
    r"(?:^|[/_.?&=-])(?:error[-_]?)?(?:403|blocked|captcha|access[-_]?denied|forbidden|challenge)(?:[/_.?&=-]|$)",
    re.I,
)


def title_of(a: Answer) -> str:
    found = TITLE.search(a.head)
    return " ".join(found.group(1).split())[:80] if found else ""


def judge(a: Answer) -> tuple[str, str]:
    """(verdict, by whom or why): ok, redirect, gone, server-error, or a
    refusal - challenge, blocked, refused, limited - or no answer: dropped
    (cut off), error. A Cloudflare script on a 200 is not a challenge: the
    JS detections ride on normal pages."""
    if a.error or a.status is None:
        why = a.error or "no status"
        return ("dropped" if any(k in why for k in DROPS) else "error"), why.split(":", 1)[0]
    h, s = a.headers, a.status
    low = a.head.lower()
    server = h.get("server", "").lower()
    if h.get("cf-mitigated") == "challenge":
        return "challenge", "Cloudflare"
    if h.get("x-vercel-mitigated") == "challenge":
        return "challenge", "Vercel Firewall"
    action = h.get("x-amzn-waf-action")
    if action:
        return ("challenge" if action in ("captcha", "challenge") else "blocked"), "AWS WAF"
    if s != 200 and any(k.startswith("x-kpsdk") for k in h):
        return "challenge", "Kasada"
    if "captcha-delivery.com" in low or (s in (403, 429) and "x-datadome" in h):
        return "challenge", "DataDome"
    # Imperva puts its script on normal pages too: a challenge is a small page holding little but it
    if "incapsula incident" in low or ("_incapsula_resource" in low and len(a.body) < 10_000):
        return ("challenge" if s == 200 else "blocked"), "Imperva"
    if "px-captcha" in low or (s == 403 and "_pxhd" in a.cookies):
        return "challenge", "HUMAN (PerimeterX)"
    if "sucuri_cloudproxy_js" in low:
        return "challenge", "Sucuri"
    if "x-sucuri-block" in h or "sucuri website firewall" in low:
        return "blocked", "Sucuri"
    if s in (403, 429, 503):
        plain = entities.unescape(low)  # Akamai writes "Reference&#32;&#35;18..." and "errors&#46;edgesuite&#46;net"
        if any(k in low for k in ("<title>just a moment", "cf-chl", "cf_chl", "jschl")):
            return "challenge", "Cloudflare"
        if "cloudflare" in server and any(
            k in low for k in ("attention required", "you have been blocked", "request was blocked")
        ):
            return "blocked", "Cloudflare"
        if (
            "akamaighost" in server
            or "errors.edgesuite.net" in plain
            or ("access denied" in plain and "reference #" in plain)
        ):
            return "blocked", "Akamai"
        if ("cloudfront" in server or "x-amz-cf-id" in h) and "request blocked" in low:
            return "blocked", "AWS CloudFront"
        # Myra answers a ban on the whole IP with a 503 and its /myracloud-blocked/ or /myracloud-captcha/ page;
        # a plain 503 from the shop behind it is a server error
        if "myracloud" in server and ("myracloud-" in f"{low} {a.location.lower()}" or "security check" in low):
            return ("challenge" if "captcha" in low else "blocked"), "Myra Security"
        if any(k in low for k in ("captcha", "turnstile", "challenge-form")):
            return "challenge", "a captcha page"
    if s == 429:
        return "limited", "Retry-After " + h["retry-after"] if "retry-after" in h else ""
    if s in (401, 403, 406, 451):
        return "refused", title_of(a) or server
    if 300 <= s < 400:
        try:  # the path and query only: a host named "...block..." or a product /14032/ is no block
            parts = urlsplit(a.location)
            where = f"{parts.path}?{parts.query}"
        except ValueError:
            where = a.location
        if BLOCK_REDIRECT.search(where):
            return "blocked", f"a redirect to {a.location}"
        return "redirect", a.location
    if s in (404, 410):
        return "gone", ""
    if s == 408:
        return "error", "408 Request Timeout"
    if 400 <= s < 500:
        return "client-error", title_of(a) or server
    if s >= 500:
        return "server-error", ""
    return "ok", ""


def passes(verdict: str) -> bool:
    """Let in: an answer that is no refusal, no loss and no 4xx the client caused."""
    return verdict not in (*REFUSALS, *LOST, "client-error")


def vendors_of(answers: Iterable[Answer]) -> dict[str, list[str]]:
    """{service: [evidence]} from what every answer's headers, cookies and page show."""
    found: dict[str, list[str]] = {}

    def add(name: str, evidence: str) -> None:
        found.setdefault(name, [])
        if evidence not in found[name]:
            found[name].append(evidence)

    for a in answers:
        if a.error:
            continue
        h, server, via = a.headers, a.headers.get("server", "").lower(), a.headers.get("via", "").lower()
        cookies = set(a.cookies)
        if "cf-ray" in h:
            add("Cloudflare", "cf-ray")
        if server == "cloudflare":
            add("Cloudflare", "server: cloudflare")
        for name in ("__cf_bm", "cf_clearance"):
            if name in cookies:
                add("Cloudflare", f"cookie {name}")
        if "akamaighost" in server:
            add("Akamai", "server: AkamaiGHost")
        for name in (k for k in h if k.startswith("x-akamai") or k == "akamai-grn"):
            add("Akamai", f"header {name}")
        for name in ("_abck", "bm_sz", "ak_bmsc", "bm_mi", "bm_sv"):
            if name in cookies:
                add("Akamai", f"cookie {name} (Bot Manager)")
        if "x-iinfo" in h or h.get("x-cdn", "").lower() in ("imperva", "incapsula"):
            add("Imperva", "header")
        if any(c.startswith(("incap_ses_", "visid_incap_")) for c in cookies):
            add("Imperva", "cookie incap_*")
        if "x-datadome" in h or "datadome" in cookies:
            add("DataDome", "header or cookie")
        if any(c.startswith("_px") for c in cookies) or "perimeterx" in a.head.lower():
            add("HUMAN (PerimeterX)", "cookie _px* or script")
        if "x-sucuri-id" in h or "sucuri" in server:
            add("Sucuri", "header")
        if any(k.startswith("x-kpsdk") for k in h):
            add("Kasada", "x-kpsdk-* header")
        if any(F5_COOKIE.match(c) for c in cookies):
            add("F5 BIG-IP ASM", "cookie TS*")
        if "x-amzn-waf-action" in h or "aws-waf-token" in cookies:
            add("AWS WAF", "header or cookie")
        if "x-vercel-mitigated" in h:
            add("Vercel Firewall", "x-vercel-mitigated")
        if "myracloud" in server:
            add("Myra Security", "server: myracloud")
        if "x-amz-cf-id" in h or "cloudfront" in via:
            add("CloudFront (CDN)", "x-amz-cf-id or via")
        if h.get("x-served-by", "").startswith("cache-") or "fastly" in via or "x-fastly-request-id" in h:
            add("Fastly (CDN)", "x-served-by or via")
        if "x-vercel-id" in h:
            add("Vercel (CDN)", "x-vercel-id")
        if "x-azure-ref" in h:
            add("Azure Front Door (CDN)", "x-azure-ref")
        if "google" in via:
            add("Google (CDN)", "via")
        if "x-varnish" in h:
            add("Varnish (cache)", "x-varnish")
    return found

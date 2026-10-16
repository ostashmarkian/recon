"""What the findings add up to: the protection, the way in, the burst's
blockers, and what changed since an earlier report."""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import settings
from .classify import GUARDS, REFUSALS, judge, passes
from .clients import Answer

Findings = dict[str, Any]  # what Recon.run() found: the report's and the .json's matter


def percentile(values: Sequence[float], share: float) -> float | None:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 3) if ordered else None


def counts(answers: Iterable[Answer]) -> dict[str, int]:
    return dict(Counter(f"{a.status} {judge(a)[0]}" if a.status else judge(a)[0] for a in answers))


def summary(a: Answer) -> dict[str, Any]:
    verdict, why = judge(a)
    return {
        "status": a.status,
        "verdict": verdict,
        "why": why,
        "http": a.http,
        "seconds": round(a.seconds, 2),
        "server": a.headers.get("server"),
    }


LEVELS = (
    "none seen",
    "a service in front, nothing refused",
    "a filter by name",
    "a filter by fingerprint",
    "a challenge for every client",
    "nothing let in",
)


def client_name(kind: str) -> str:
    """What the report calls a client: "curl_cffi as Chrome" for curl-chrome."""
    return settings.CLIENT_NAMES.get(kind, kind)


def guards_named(f: Findings) -> list[str]:
    """The anti-bot services in front with what showed them: "Akamai Bot Manager (cookie ak_bmsc, cookie bm_mi)"."""
    named = []
    for vendor, evidence in (f.get("vendors") or {}).items():
        if vendor in GUARDS:
            product = " Bot Manager" if vendor == "Akamai" and any("Bot Manager" in e for e in evidence) else ""
            shown = ", ".join(e.replace(" (Bot Manager)", "") for e in evidence)
            named.append(f"{vendor}{product} ({shown})")
    return named


def browser_said(browser: dict[str, Any]) -> str:
    """What the real browser met, in a sentence; "" when none was tried."""
    if not browser or browser.get("error"):
        return ""
    said = " A real browser is " + ("let in" if browser.get("passed") else "refused too")
    if "cf_clearance" in browser.get("cookies", []):
        carried = browser.get("clearance_carried") or []
        to = [client_name(c["client"]) for c in carried if passes(c["verdict"])]
        said += " and gets cf_clearance" + (
            f"; the cookie lets {', '.join(to)} in" if to else ", but the cookie does not carry over to the clients"
        )
    return said + "."


def protection_level(f: Findings) -> dict[str, Any]:
    """How hard the site is to get into, 0 to 5, from what this run saw, in words; and what one run cannot see."""
    vendors = f.get("vendors") or {}
    rows = f.get("clients") or []
    let_in = f.get("let_in") or []
    turned = list(dict.fromkeys(r["client"] for r in rows if r["verdict"] in (*REFUSALS, "dropped")))
    browser = f.get("browser") or {}
    guards = guards_named(f)
    refusers = [w for w, _ in Counter(r["why"] for r in rows if r["verdict"] in REFUSALS and r["why"]).most_common()]
    who = ", ".join(refusers) or "; ".join(guards) or "The site"
    if not let_in:
        level = 4 if browser.get("passed") else 5
    elif turned:
        level = 3
    elif f.get("ua_filter"):
        level = 2
    elif vendors:
        level = 1
    else:
        level = 0

    if level == 0:
        said = "Nothing in front, nothing refused."
    elif level == 1:
        said = f"{'; '.join(guards) or ', '.join(vendors)} in front; every client and User-Agent let in."
    elif level == 2:
        said = (
            f"{'; '.join(guards) or 'The site'} refuses User-Agents by name ({f['ua_filter']}); "
            f"all {len(let_in)} clients with a browser User-Agent are let in, no challenge seen."
        )
    elif level == 3:
        verdicts = sorted(
            {r["verdict"] for r in rows if r["client"] in turned and r["verdict"] in (*REFUSALS, "dropped")}
        )
        said = (
            f"{who} turns away {', '.join(client_name(k) for k in turned)} ({', '.join(verdicts)}) "
            f"with a browser User-Agent; let in: {', '.join(client_name(k) for k in let_in)}."
        )
        if all(k.startswith("httpx") for k in turned) and any(k.startswith("curl-") for k in let_in):
            said += " Python's own TLS is what is turned away: the TLS fingerprint decides."
            if "httpx-h1-pha" in let_in and "httpx-h2-pha" in turned:
                said += " httpx with PHA passes over HTTP/1.1 only, so the HTTP/2 fingerprint counts too."
        said += browser_said(browser)
    elif level == 4:
        said = f"{who} challenges every client, a browser User-Agent or not." + browser_said(browser)
    else:
        if browser.get("error"):
            tail = f" The browser could not run ({browser['error']})."
        elif browser:
            tail = " A real browser is refused too."
        else:
            tail = " The refusals were no challenges, so no browser was tried."
        said = f"{who} lets no client in." + tail

    if guards or level >= 2:
        unseen = "limits over a long session, behaviour scoring, the IP's reputation"
    elif (f.get("burst") or {}).get("steps") and not (f.get("burst") or {}).get("stop"):
        unseen = "a limiter that allows a larger burst than recon's"
    else:
        unseen = "limits past the pace recon kept"
    return {"level": level, "label": LEVELS[level], "said": said, "unseen": unseen}


def protection(f: Findings) -> list[str]:
    """Why the shop counts as protected; [] when nothing was found."""
    why = []
    guards = [v for v in f.get("vendors") or {} if v in GUARDS]
    if guards:
        why.append("in front: " + ", ".join(guards))
    turned: dict[str, list[str]] = {}
    for r in f.get("clients", []):
        if r["verdict"] in (*REFUSALS, "dropped"):
            turned.setdefault(f"{client_name(r['client'])} {r['verdict']}", []).append(urlsplit(r["page"]).path or "/")
    if turned:
        why.append("clients turned away: " + "; ".join(f"{k} on {', '.join(v)}" for k, v in turned.items()))
    if not f.get("let_in"):
        why.append("no client let in")
    if f.get("session", {}).get("refused"):
        why.append(f"refused in the session test ({f['session']['refused']})")
    elsewhere = f.get("refused_elsewhere") or {}
    if elsewhere:
        why.append(
            "refused in other steps: "
            + "; ".join(f"{step} ({', '.join(f'{n} {v}' for v, n in got.items())})" for step, got in elsewhere.items())
        )
    if (f.get("robots") or {}).get("state") == "unreadable":
        why.append("robots.txt could not be read: everything counts as disallowed")
    return why


def ua_filter(f: Findings) -> str | None:
    """The User-Agents turned away by name, "refused GPTBot, ClaudeBot; dropped Scrapy"; None for none.
    Not protection here: the burst sends a browser's."""
    names: dict[str, list[str]] = {}
    for r in f.get("uas", []):
        if r["verdict"] in (*REFUSALS, "dropped"):
            names.setdefault(r["verdict"], []).append(r["ua"])
    return "; ".join(f"{v} {', '.join(n)}" for v, n in names.items()) or None


def burst_blockers(f: Findings) -> list[str]:
    """Why no burst: protection, or robots.txt asking for a Crawl-delay."""
    why = protection(f)
    delay = (f.get("robots") or {}).get("crawl_delay")
    if delay:
        why.append(f"robots.txt asks Crawl-delay {delay}")
    return why


def not_found_findings(rows: list[dict[str, Any]]) -> list[str]:
    """What the not-found probes say, in the words a scraper's guard needs."""
    said, by = [], {r["probe"]: r for r in rows}
    for name in ("a made-up product", "a made-up path"):
        r = by.get(name)
        if not r:
            continue
        if r["verdict"] == "ok":
            said.append(
                f'{name} answers 200 ("{r["title"]}", {r["bytes"]:,} bytes): a soft 404,'
                " tell such a page by what it holds"
            )
        elif r["verdict"] == "redirect":
            said.append(f"{name} redirects to {r['location']}")
        else:
            said.append(f"{name}: {r['status'] or '-'} {r['verdict']}")
    real, far = by.get("a listing page"), by.get(f"its page {settings.FAR_PAGE}")
    if real and far:
        if far["verdict"] == "ok" and real["verdict"] == "ok":
            alike = real["title"] == far["title"] and abs(real["bytes"] - far["bytes"]) <= 0.05 * max(real["bytes"], 1)
            said.append(
                f"page {settings.FAR_PAGE} answers 200 "
                + (
                    "like the real page (a wrap or a clamp): end a walk by what a page holds"
                    if alike
                    else f"({far['bytes']:,} bytes against {real['bytes']:,}): see what it holds"
                )
            )
        else:
            said.append(f"page {settings.FAR_PAGE}: {far['status'] or '-'} {far['verdict']}")
    return said


def present(f: Findings) -> list[str]:
    """The product fields a report found, for comparing two reports."""
    p = f.get("product") or {}
    return sorted(
        [f"JSON-LD {k}" for k in p.get("jsonld") or {}]
        + [f"microdata {k}" for k in p.get("microdata") or {}]
        + [f"label {k}" for k in p.get("labels") or {}]
    )


def compare(prev: Findings, f: Findings) -> list[str]:
    """What changed since an earlier report of the same shop, in what both hold."""
    changes = []

    def show(value: Any) -> str:
        if isinstance(value, list):
            return "; ".join(map(str, value)) or "none"
        return "none" if value in (None, "", {}) else str(value)

    def note(label: str, before: Any, now: Any, key: str | None = None) -> None:
        if key and key not in prev:  # an older report, made before recon read this
            return
        if (before or None) != (now or None):
            changes.append(f"{label}: {show(before)} -> {show(now)}")

    # the pages a client was turned away on name the deeper page, which another run may pick otherwise
    note(
        "protection",
        [re.sub(r" on [^;]+", "", p) for p in prev.get("protection") or []],
        [re.sub(r" on [^;]+", "", p) for p in f.get("protection") or []],
    )
    note(
        "protection level",
        (prev.get("level") or {}).get("level"),
        (f.get("level") or {}).get("level"),
        "level",
    )
    note("in front", sorted(prev.get("vendors") or {}), sorted(f.get("vendors") or {}))
    note("clients let in", prev.get("let_in"), f.get("let_in"))
    note("way in", prev.get("way_in"), f.get("way_in"))
    note("User-Agent filter", prev.get("ua_filter"), f.get("ua_filter"), "ua_filter")
    note("platform", [p["name"] for p in prev.get("platforms") or []], [p["name"] for p in f.get("platforms") or []])
    note("session lock", (prev.get("session") or {}).get("lock"), (f.get("session") or {}).get("lock"))
    note("product data", present(prev), present(f), "product")
    note(
        "not-found pages",
        (prev.get("not_found") or {}).get("findings"),
        (f.get("not_found") or {}).get("findings"),
        "not_found",
    )
    note("burst", (prev.get("burst") or {}).get("stop"), (f.get("burst") or {}).get("stop"))
    note(
        "product sample traps", (prev.get("sample") or {}).get("traps"), (f.get("sample") or {}).get("traps"), "sample"
    )
    note(
        "cache",
        sorted((prev.get("freshness") or {}).get("cache") or {}),
        sorted((f.get("freshness") or {}).get("cache") or {}),
        "freshness",
    )
    before = (prev.get("sitemap") or {}).get("addresses") or 0
    now = (f.get("sitemap") or {}).get("addresses") or 0
    if before != now and (not before or abs(now - before) > 0.05 * before):
        changes.append(f"sitemap: {before:,} -> {now:,} addresses")
    return changes


def previous_report(folder: Path | str, host: str) -> Path | None:
    """The newest report of `host` in `folder` (its .json), or None."""
    found = sorted(Path(folder).glob(f"{host}-*.json")) if Path(folder).is_dir() else []
    return found[-1] if found else None


def way_in(f: Findings) -> str:
    """The cheapest client the shop lets in, and how it must ask."""
    let_in = f.get("let_in") or []
    if let_in:
        kind = let_in[0]
        ua = "its own User-Agent" if kind.startswith("curl-") else "a browser User-Agent"
        lock = (f.get("session") or {}).get("lock")
        cookies = "" if lock is None else ", no cookies (a session lock)" if lock else ", cookies or none alike"
        return f"{client_name(kind)}, {ua}{cookies}"
    browser = f.get("browser") or {}
    carried = [c["client"] for c in browser.get("clearance_carried", []) if passes(c["verdict"])]
    if carried:
        return f"{client_name(carried[0])} with the browser's cf_clearance and its User-Agent, renewed on a challenge"
    if browser.get("passed"):
        return "only a real browser: no client let in, its cookie carried to none"
    return "none found: no client let in" + ("" if browser else ", and no browser tried")

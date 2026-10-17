"""The findings as a Markdown report."""

from typing import Any
from urllib.parse import urlsplit

from . import settings
from .findings import Findings, client_name
from .sample import SAMPLE_FIELDS


def for_humans(seconds: float) -> str:
    for size, unit in ((86_400, "d"), (3_600, "h"), (60, "min")):
        if seconds >= size:
            return f"{seconds / size:.1f} {unit}"
    return f"{seconds} s"


# ---------------------------------------------------------------- the report
def cell(r: dict[str, Any]) -> str:
    if r["status"] is None:
        return f"{r['verdict']} ({r['why']})"
    said = f" ({r['why']})" if r["why"] and r["verdict"] not in ("redirect",) else ""
    return f"{r['status']} {r['verdict']}{said}, {r['http']} {r['seconds']:.2f}s"


def sample_line(s: dict[str, Any]) -> str:
    if s.get("skipped"):
        return f"not read ({s['skipped']})"
    n = s["read"]
    if not n:
        return f"none of the {s['asked']} product links answered a page"
    cover = ", ".join(f"{k} {s['coverage'][k]}/{n}" for k in ("mpn", "sku", "gtin", "price") if s["coverage"].get(k))
    said = [f"{n} of {s['asked']} pages read", cover or "no structured product data"]
    if s["currencies"]:
        said.append("currency " + ", ".join(s["currencies"]))
    if s["vat_included"]:
        said.append("VAT included: " + ", ".join(f"{k} on {v}" for k, v in s["vat_included"].items()))
    said.append(f"a stock number on {s['stock_numbers']}")
    if s["ladder"]:
        said.append(f"a price ladder hint on {s['ladder']}")
    return "; ".join(said) + (f"; {len(s['traps'])} trap(s):" if s["traps"] else "; no trap seen")


def freshness_line(fr: dict[str, Any]) -> str:
    if not fr.get("pages"):
        return "no page read"
    said = []
    if fr["cache"]:
        said.append("cache " + ", ".join(f"{k} {v}/{fr['pages']}" for k, v in fr["cache"].items()))
    if fr["age_max"] is not None:
        said.append(
            f"Age up to {for_humans(fr['age_max'])}"
            + (" - stock and prices may be that old" if fr["age_max"] > settings.STALE else "")
        )
    if fr["last_modified_days"] is not None:
        said.append(f"Last-Modified up to {fr['last_modified_days']} d ago")
    if fr["cache_control"]:
        said.append(f"Cache-Control `{fr['cache_control']}`")
    return "; ".join(said) or f"no cache headers on {fr['pages']} pages"


def product_line(p: dict[str, Any]) -> str:
    """The product data in one line: what a parts buyer needs, and what is missing."""
    if not p.get("url"):
        partial = p.get("partial")
        return f"none on the {len(p.get('tried') or [])} page(s) tried (name one with --page)" + (
            f"; words for {', '.join(partial['labels'])} on {partial['url']}" if partial else ""
        )
    said = []
    ld = p.get("jsonld") or {}
    if ld:
        wanted = ("mpn", "sku", "gtin", "brand", "price", "currency", "availability")
        said.append(
            "JSON-LD "
            + ", ".join(f"{k} `{ld[k]}`" for k in wanted if k in ld)
            + (f", VAT included: {ld['vat_included']}" if "vat_included" in ld else "")
            + (
                "; no " + ", ".join(k for k in ("mpn", "gtin", "price") if k not in ld)
                if any(k not in ld for k in ("mpn", "gtin", "price"))
                else ""
            )
        )
    if p.get("microdata"):
        said.append("microdata " + ", ".join(p["microdata"]))
    if p.get("labels"):
        said.append("words for " + ", ".join(p["labels"]))
    return "; ".join(said) or "none"


def report(f: Findings) -> str:
    host = urlsplit(f["home"]).netloc
    out = [f"# recon: {host}", "", f"{f['began']}, {f['requests']} requests, {f['seconds']} s. Home: {f['home']}", ""]
    vendors = f.get("vendors") or {}
    session, burst = f.get("session") or {}, f.get("burst") or {}

    out += ["## Verdict", ""]
    if f.get("stopped"):
        rb = f.get("robots") or {}
        out += [f"- **Stopped:** {f['stopped']}"]
        out += [f"- robots.txt: {rb.get('url')}, {rb.get('state')}"] if rb else []
        return "\n".join(out) + "\n\n"
    level = f.get("level") or {}
    if level:
        n = level.get("level")
        grade = f"level {n} of 5, {level['label']}" if n is not None else level["label"]
        out.append(f"- **Protection: {grade}.** {level['said']}")
        if f["protection"]:
            out.append("  - seen: " + "; ".join(f["protection"]))
        out.append(f"  - not seen in one run: {level['unseen']}")
    else:
        out.append("- **Protection:** " + ("none found" if not f["protection"] else "; ".join(f["protection"])))
    if f.get("ua_filter") and f["ua_filter"] not in level.get("said", ""):  # said above in the level
        out.append(f"- **User-Agent filter:** {f['ua_filter']} (not protection here: the burst sends a browser's)")
    out.append(f"- **Way in:** {f['way_in']}")
    if session.get("skipped"):
        out.append(f"- **Session lock:** not measured ({session['skipped']})")
    elif "lock" in session:
        jar, none = session["with one jar"]["per_s"], session["with no cookies"]["per_s"]
        out.append(
            f"- **Session lock:** {'yes' if session['lock'] else 'no'}: {jar}/s with one cookie jar,"
            f" {none}/s with none, {settings.SESSION_AT_ONCE} at a time"
        )
    long = f.get("long") or {}
    if long.get("skipped"):
        out.append(f"- **Long session:** not run ({long['skipped']})")
    elif long:
        low, high = long["pause"]
        how = f"{client_name(long['client'])}, one cookie jar, a request every {low:g}-{high:g} s"
        stop = long.get("refused") or long.get("lost")
        if stop:
            out.append(
                f"- **Long session:** {'refused' if long.get('refused') else 'answers lost'} at request {stop['at']},"
                f" {stop['minutes']} min in: {cell(stop)} ({how})"
            )
        else:
            out.append(f"- **Long session:** {long['asked']} requests over {long['minutes']} min, none refused ({how})")
    if burst.get("skipped"):
        out.append(
            "- **Burst:** skipped ("
            + ("for what is seen above" if burst["skipped"] == f["protection"] else "; ".join(burst["skipped"]))
            + ")"
        )
    elif burst:
        top = max(burst["steps"], key=lambda s: s["per_s"], default={"per_s": 0})
        if burst["stop"]:
            after = burst.get("after") or {}
            out.append(
                f"- **Burst:** stopped after {burst['asked']} requests: {burst['stop']}; "
                f"{settings.RECOVER} s later the home page: {cell(after) if after else '-'}"
            )
        else:
            out.append(
                f"- **Burst:** no limit seen in {burst['asked']} requests, up to "
                f"{burst['steps'][-1]['at_once']} at a time and {top['per_s']}/s"
                " (a limiter allowing a larger burst would not show)"
            )
    out.append(f"- **Product data:** {product_line(f.get('product') or {})}")
    sample = f.get("sample") or {}
    out.append(f"- **Product sample:** {sample_line(sample)}")
    for trap in sample.get("traps") or []:
        out.append(f"  - {trap}")
    out.append(f"- **Freshness:** {freshness_line(f.get('freshness') or {})}")
    for name, seen in (f.get("rendering") or {}).items():
        if seen["drawn"]:
            out.append(
                f"- **Rendering:** the {name} page's HTML holds {seen['text']} characters of text"
                + (" and an empty app root" if seen["empty_root"] else "")
                + ": drawn by JavaScript, its data likely from an API"
            )
    if f.get("pause", settings.PAUSE) > settings.PAUSE:
        out.append(f"- **Pace:** one request every {f['pause']:g} s (robots.txt's Crawl-delay or --pause)")
    nf = f.get("not_found") or {}
    out.append("- **Not-found pages:** " + (nf.get("skipped") or "; ".join(nf.get("findings") or []) or "-"))
    src = f.get("sources") or {}
    said = [
        f"search by {', '.join(src['search'])}" if src.get("search") else "",
        f"page data: {', '.join(src['blobs'])}" if src.get("blobs") else "",
        f"{len(src['endpoints'])} API paths in the pages" if src.get("endpoints") else "",
    ]
    out.append("- **Catalogue sources:** " + ("; ".join(s for s in said if s) or "none seen in the pages"))
    plats = f.get("platforms") or []
    out.append(
        "- **Platform:** "
        + (", ".join(p["name"] + (f" ([[{p['note']}]])" if p["note"] else "") for p in plats) or "not recognised")
        + ("; stack " + ", ".join(s["name"] for s in f.get("stacks", [])) if f.get("stacks") else "")
    )
    sm = f.get("sitemap") or {}
    out.append(
        f"- **Sitemap:** {sm.get('addresses', 0):,} addresses in {sm.get('files_read', 0)} files read"
        + (f", {sm['files_left']} left unread" if sm.get("files_left") else "")
        + (f", lastmod {sm['lastmod'][0]} to {sm['lastmod'][1]}" if sm.get("lastmod") else "")
    )
    for api in f.get("apis", []):
        if api["url"] is None:
            out.append(f"- **API** {api['platform']}: {api['says']}")
        else:
            out.append(f"- **API** {api['platform']}: {cell(api)}" + (f", {api['says']}" if api["says"] else ""))
    if f.get("rate_headers"):
        out.append("- **Rate-limit headers:** " + ", ".join(f"{k}: {v}" for k, v in f["rate_headers"].items()))
    notes = f.get("notes")
    if notes:
        main = notes["note"]
        held = ", ".join(f"{k}: {v}" for k, v in (main or {}).items() if k != "note")
        out.append(
            "- **Notes:** "
            + (f"[[{main['note']}]]" + (f" ({held})" if held else "") + ", " if main else "")
            + f"{notes['mentions']} notes name {notes['domain']}"
        )
    out.append("")

    if "changes" in f:
        out += [f"## Since the report of {f['compared_with']['began']}", ""]
        out += [f"- {c}" for c in f["changes"]] or ["- nothing changed in what both reports hold"]
        out.append("")

    pages = list(dict.fromkeys(r["page"] for r in f.get("clients", [])))
    if pages:
        names = ["/" if p == f["home"] else urlsplit(p).path for p in pages]
        out += [
            "## Clients, with a browser User-Agent",
            "",
            "| client | " + " | ".join(f"`{n}`" for n in names) + " |",
            "|---|" + "---|" * len(pages),
        ]
        for kind in dict.fromkeys(r["client"] for r in f["clients"]):
            row = {r["page"]: r for r in f["clients"] if r["client"] == kind}
            out.append(f"| {client_name(kind)} | " + " | ".join(cell(row[p]) if p in row else "" for p in pages) + " |")
        out += [
            "",
            "PHA: httpx with `post_handshake_auth`, Python's other TLS ClientHello. curl_cffi: libcurl sending"
            " a browser's TLS and HTTP/2 fingerprint, with that browser's own User-Agent.",
            "",
            f"Deeper page ({f['page_from']}): {f['page']}",
            "",
        ]

    if f.get("uas"):
        out += [
            f"## User-Agents, through {client_name(f['uas_through'])}, on the home page",
            "",
            "| User-Agent | answer |",
            "|---|---|",
        ]
        out += [f"| {r['ua']} | {cell(r)} |" for r in f["uas"]]
        out.append("")

    b = f.get("browser")
    if b:
        out += ["## Browser (Chrome through patchright, headless)", ""]
        if b.get("error"):
            out.append(f"Not run on {b['url']}: {b['error']}")
        else:
            out.append(
                f"On {b['url']}: first answer {b['status']}, challenged: {b['challenged']}, "
                f'passed: {b["passed"]} (title "{b["title"]}") in {b["seconds"]} s; '
                f"cookies: {', '.join(b['cookies']) or 'none'}"
            )
            for c in b["clearance_carried"]:
                out.append(f"- its cf_clearance + User-Agent on {client_name(c['client'])}: {cell(c)}")
        out.append("")

    if session and not session.get("skipped"):
        out += ["## Session", "", f"Cookies set: {', '.join(session['cookies_set'])}.", ""]
        for mode in ("with one jar", "with no cookies"):
            if mode in session:
                s = session[mode]
                out.append(f"- {mode}: {s['per_s']}/s, p50 {s['p50']}s, {s['answers']}")
        out.append("")

    if burst.get("steps"):
        out += [
            f"## Burst, {client_name(burst['client'])} over {burst['http']}",
            "",
            "| at a time | asked | answered | per s | p50 s | p95 s | answers |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in burst["steps"]:
            out.append(
                f"| {s['at_once']} | {s['asked']} | {s['answered']} | {s['per_s']} | {s['p50']:.2f} | "
                f"{s['p95']:.2f} | {s['answers']} |"
                if s["p50"] is not None
                else f"| {s['at_once']} | {s['asked']} | {s['answered']} | {s['per_s']} | - | - | {s['answers']} |"
            )
        out.append("")

    p = f.get("product") or {}
    if p.get("url"):
        out += ["## Product page", "", p["url"], ""]
        for name, values in (("JSON-LD Product", p["jsonld"]), ("microdata", p["microdata"]), ("meta", p["meta"])):
            if values:
                out.append(f"- {name}: " + ", ".join(f"{k} `{v}`" for k, v in values.items()))
        for name, seen in p["labels"].items():
            out.append(f"- the page's words, {name}: " + " | ".join(f"`{s}`" for s in seen))
        out.append("")

    if sample.get("rows"):
        out += [
            f"## Product sample, {sample['read']} pages",
            "",
            "| field | " + " | ".join(SAMPLE_FIELDS) + " |",
            "|---|" + "---|" * len(SAMPLE_FIELDS),
            "| pages | " + " | ".join(f"{sample['coverage'][k]}/{sample['read']}" for k in SAMPLE_FIELDS) + " |",
            "",
            "| page | mpn | sku | price | stock | ladder |",
            "|---|---|---|---|---|---|",
        ]
        for r in sample["rows"]:
            price = " ".join(x for x in (r["price"], r["currency"]) if x) or "-"
            out.append(
                f"| {urlsplit(r['url']).path} | {r['mpn'] or '-'} | {r['sku'] or '-'} | {price} | "
                f"{r['stock'] or '-'} | {'yes' if r['ladder'] else '-'} |"
            )
        out.append("")

    if nf.get("rows"):
        out += ["## Not-found pages", "", "| probe | address | answer | title | bytes |", "|---|---|---|---|---|"]
        for r in nf["rows"]:
            answer = cell(r) + (f" to {r['location']}" if r["verdict"] == "redirect" else "")
            out.append(f"| {r['probe']} | {r['url']} | {answer} | {r['title']} | {r['bytes']:,} |")
        out.append("")

    if any(src.get(k) for k in ("search", "blobs", "endpoints")):
        out += ["## Catalogue sources", ""]
        for name, hit in (src.get("search") or {}).items():
            out.append(f"- {name}: `{hit}` in a page")
        for name in src.get("blobs") or []:
            out.append(f"- {name} in a page")
        if src.get("endpoints"):
            out.append("- API paths: " + ", ".join(f"`{e}`" for e in src["endpoints"]))
        out.append("")

    if f.get("errors"):
        out += ["## Errors", "", "Steps that broke; the report holds what the others found.", ""]
        out += [f"- {e['step']}: {e['error']}" for e in f["errors"]]
        out.append("")

    home = f.get("home_answer") or {}
    out += ["## Site", ""]
    if f.get("home_redirect"):
        out.append(f"- The home page redirects {f['home_redirect']}")
    out.append(f"- Home: {cell(home)}" if home else "- Home: -")
    out.append("- In front: " + ("; ".join(f"{v} ({', '.join(e)})" for v, e in vendors.items()) or "nothing seen"))
    for p in plats:
        out.append(f"- {p['name']}: {', '.join(p['evidence'])}")
    for s in f.get("stacks", []):
        out.append(f"- {s['name']}: {', '.join(s['evidence'])}")
    if f.get("generator"):
        out.append(f"- generator: {f['generator']}")
    rb = f.get("robots") or {}
    out.append(
        f"- robots.txt: {rb.get('status')} {rb.get('verdict')}, {rb.get('state', 'read')}"
        + (f" at {rb['url']}" if rb.get("url") and not str(rb["url"]).endswith(f"{host}/robots.txt") else "")
        + f", {rb.get('disallow', 0)} Disallow lines"
        + (f", Crawl-delay {rb['crawl_delay']}" if rb.get("crawl_delay") else "")
        + (f", sitemaps: {', '.join(rb['sitemaps'][:5])}" if rb.get("sitemaps") else ", no sitemap named")
    )
    for s in sm.get("files", [])[:10]:
        out.append(
            f"  - {s['url']}: {s['status']}"
            + (f" {s['kind']}, {s['addresses']:,}" if "kind" in s else f" {s['verdict']}")
        )
    out.append(f"- Pages in the pool: {f.get('pool', 0)}")
    return "\n".join(out) + "\n"

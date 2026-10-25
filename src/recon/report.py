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
    listings, others = s.get("listings") or [], s.get("not_products") or []
    parts = [f"{len(listings)} listing{'s' if len(listings) > 1 else ''}"] if listings else []
    if others:
        many = len(others) > 1
        parts.append(f"{len(others)} page{'s' if many else ''} with no product of {'their' if many else 'its'} own")
    left = f" ({' and '.join(parts)} left out)" if parts else ""
    if not n:
        return f"none of the {s['asked']} product links answered a product page{left}"
    held = s.get("from_state") or {}
    cover = ", ".join(
        f"{k} {s['coverage'][k]}/{n}" + (f" ({held[k]} from the page state)" if held.get(k) else "")
        for k in ("mpn", "sku", "gtin", "price")
        if s["coverage"].get(k)
    )
    said = [f"{n} of {s['asked']} pages read{left}", cover or "no structured product data"]
    if s["currencies"]:
        said.append("currency " + ", ".join(s["currencies"]))
    if s["vat_included"]:
        said.append("VAT included: " + ", ".join(f"{k} on {v}" for k, v in s["vat_included"].items()))
    said.append(f"a stock number on {s['stock_numbers']}")
    if s["ladder"]:
        said.append(f"a price ladder hint on {s['ladder']}")
    return "; ".join(said) + (f"; {len(s['traps'])} trap(s):" if s["traps"] else "; no trap seen")


def what_call(c: dict[str, Any]) -> str:
    """What one call a page made holds, in a few words: "a product list at items (24: id, sku, price, stock),
    paging total, page"."""
    if c["kind"] in ("products", "list"):
        said = (
            f"{'a product list' if c['kind'] == 'products' else 'a list'} at `{c['path']}` ({c['items']}: "
            + ", ".join(c["keys"][:8])
            + ")"
        )
    elif c["kind"] == "html":
        said = f"an HTML fragment, {c['links']} links, {c['product_links']} to products"
    elif c["kind"] == "data":
        said = "data, no list"
    else:
        said = f"{c['type'] or 'no type'}"
    if c.get("json_as"):
        said += f" (JSON served as {c['json_as']})"
    if c.get("paging"):
        said += "; paging " + ", ".join(c["paging"])
    if c.get("operation"):
        said += f"; GraphQL {c['operation']}"
    replay = c.get("replay") or {}
    if replay.get("skipped"):
        said += f"; not asked again ({replay['skipped']})"
    elif replay.get("works"):
        said += f"; works with {client_name(replay['client'])} alone, no cookie or token"
    elif replay:
        got = f", {replay['kind']}" if replay["verdict"] == "ok" else ""
        said += f"; with {client_name(replay['client'])} alone: {replay['status'] or '-'} {replay['verdict']}{got}"
    if c.get("needs") and replay and not replay.get("works"):
        said += "; the page sent " + ", ".join(c["needs"][:6])
    return said


def watch_line(w: dict[str, Any]) -> str:
    """The verdict's line on what the pages fetch."""
    if w.get("skipped"):
        return f"not watched ({w['skipped']})"
    if w.get("error"):
        return f"Chrome could not run ({w['error']})"
    calls = [c for p in w.get("pages") or [] for c in p["calls"]]
    if not calls:
        return f"no XHR or fetch on the {len(w.get('pages') or [])} pages opened"
    best = [c for c in calls if c["kind"] == "products"] or [
        c for c in calls if c["kind"] == "html" and c.get("product_links", 0) >= 3
    ]
    lead = "; ".join(f"{c['method']} {short_url(c['url'])}: {what_call(c)}" for c in best[:2])
    given = " (the page given among them, though robots.txt disallows it)" if w.get("given_disallowed") else ""
    return f"{len(calls)} calls on {len(w['pages'])} pages{given}" + (
        f"; {lead}" if lead else "; none of them a product list"
    )


def short_url(url: str, most: int = 90) -> str:
    parts = urlsplit(url)
    shown = parts.path + (f"?{parts.query}" if parts.query else "")
    return (shown if len(shown) <= most else shown[: most - 1] + "…") or "/"


def chain_said(chain: list[dict[str, Any]]) -> str:
    """A redirect chain: "/sitemap-index.xml 301 -> /maps/sitemap-prod-index.xml 404"."""
    return " -> ".join(f"{short_url(c['url'])} {c['status'] or c.get('why')}" for c in chain)


def host_said(b: dict[str, Any]) -> str:
    """What an API base's host is: the site's own, internal and never asked, or public with what answered."""
    dns = b.get("dns")
    if dns == "the site's":
        return "the site's own host"
    if dns in ("none", "internal"):
        why = "no public DNS" if dns == "none" else "a private address" if b.get("addresses") else "an internal name"
        return f"{why}: the servers' own, never asked"
    if dns != "public":
        return "not looked at"
    said = ["public DNS" + (f", CNAME {b['canonical']}" if b.get("canonical") else "")]
    asked = b.get("asked") or {}
    if asked:
        said.append(
            f"its robots.txt {asked.get('status') or '-'} {asked.get('verdict')}"
            + (f", server {asked['server']}" if asked.get("server") else "")
            + (f", cookies {', '.join(asked['cookies'])}" if asked.get("cookies") else "")
        )
    vendors = b.get("vendors") or {}
    said.append(
        "in front: " + "; ".join(f"{v} ({', '.join(e)})" for v, e in vendors.items())
        if vendors
        else "nothing seen in front"
    )
    return "; ".join(said)


def routes_line(api: dict[str, Any]) -> str:
    """The routes the pages' scripts name, grouped by what they look for."""
    routes = api.get("routes") or []
    b = api.get("bundles") or {}
    said = f"{len(routes)} API routes in the pages' scripts and {b.get('read', 0)} JS bundles read"
    if b.get("named", 0) > b.get("read", 0):
        said += f" of {b['named']} named"
    if b.get("hosts"):
        said += f" (from {', '.join(b['hosts'])} too)"
    if b.get("internal"):
        said += f"; {sum(b['internal'].values())} on internal hosts not asked ({', '.join(b['internal'])})"
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in routes:
        groups.setdefault(r["kind"], []).append(r)
    for kind in ("lists and search", "detail", "stock and price"):
        found = groups.get(kind) or []
        if found:
            said += f"; {kind}: " + ", ".join(f"{r['method']} `{r['route']}`" for r in found[:4])
            said += f" and {len(found) - 4} more" if len(found) > 4 else ""
    if groups.get("other"):
        said += f"; {len(groups['other'])} other"
    return said


def probe_line(probe: dict[str, Any]) -> str:
    """What one list route of the API gave a plain client."""
    if probe.get("skipped"):
        return f"not asked without the browser ({probe['skipped']})" + (f": {probe['url']}" if probe.get("url") else "")
    got = f"{probe['status'] or '-'} {probe['verdict']}"
    if probe.get("json"):
        what = "JSON" + (f" served as {probe['json_as']}" if probe.get("json_as") else "")
        if probe.get("kind") in ("products", "list"):
            what += f", {'a product list' if probe['kind'] == 'products' else 'a list'} at `{probe['path']}`"
            what += f" ({probe['items']} items)"
        if probe.get("error"):
            what += ", an error message, not data"
        if probe.get("said"):
            what += f", it says {probe['said']}"
    else:
        what = f"no JSON ({probe.get('type') or 'no type'})"
    who = f"{client_name(probe['client'])}, no cookie or token"
    filled = probe.get("filled") or {}
    if filled:
        who += "; " + ", ".join(f"`{k}` filled in with {v}" for k, v in filled.items()) + ", which the run had"
    return f"a plain client ({who}) got from GET {probe['url']}: {got}, {what}"


def state_line(api: dict[str, Any]) -> str | None:
    """Where the pages' state holds products, and the counts beside them: a listing's list first, then the product
    a product page is about (a list there is related products, said in the section below)."""
    parts = []
    order = ("listing", "product", "home")
    for s in sorted(api.get("state") or [], key=lambda s: order.index(s["page"]) if s["page"] in order else 3):
        bits = []
        for x in [x for x in s["lists"] if x["counts"] or not s.get("product")][:2]:
            counts = ", ".join(f"{k} {v}" for k, v in x["counts"].items())
            bits.append(
                f"`{x['path']}` ({x['items']} products"
                + (f"; {counts}" if counts else "")
                + (f"; part number in `{x['mpn_key']}`" if x.get("mpn_key") else "")
                + ")"
            )
        if s.get("product"):
            held = s["product"]
            bits.append(
                f"product at `{held['path']}` (part number `{held['fields'].get('mpn')}` in `{held['mpn_key']}`)"
            )
        parts.append(f"the {s['page']} page's " + "; ".join(bits))
    if not parts:
        return None
    formats = ", ".join(dict.fromkeys(s["format"] for s in api["state"]))
    return f"{formats}: " + "; ".join(parts)


def api_lines(f: Findings) -> list[str]:
    """The verdict's lines on the site's own API: its bases, routes, what a plain client got, its page state."""
    api = f.get("api") or {}
    if not api:
        return []
    bases = api.get("bases") or []
    site = set(f.get("vendors") or {})
    probe = api.get("probe") or {}
    head, below = [], []
    for b in bases:
        other = list(b.get("vendors") or {})
        if b.get("dns") == "public":
            front = f"{', '.join(other)} in front" if other else "nothing seen in front"
            if set(other) != site:
                front += ", not what the site has: its protection is its own"
            head.append(f"`{b['url']}` ({front})")
        elif b.get("dns") == "the site's":
            head.append(f"`{b['url']}` (the site's own host)")
        below.append(f"  - `{b['url']}`: `{'`, `'.join(b['keys'])}` in {b['source']}; {host_said(b)}")
    internal = [b for b in bases if b.get("dns") in ("none", "internal")]
    if internal:
        head.append(f"{len(internal)} internal, never asked")
    if probe.get("json"):
        if probe.get("kind") == "products":
            what = f"a product list of {probe['items']}"
        elif probe.get("error"):
            what = f"an error message, not data: {probe['message']}"
        else:
            what = "data, no product list"
        filled = probe.get("filled") or {}
        others = probe.get("others") or []
        bare = next((x for x in others if x.get("error") and x.get("route") == probe.get("route")), None)
        if filled:  # asked once more with a value the run had: what it got, and what it got without
            what += ", with " + ", ".join(f"{k}={v}" for k, v in filled.items())
            what += f"; without it, an error message: {bare['message']}" if bare else ""
        head.append(f"a plain client got JSON from a list route ({what})")
    elif probe and not probe.get("skipped"):
        head.append(f"a plain client got no JSON from a list route ({probe['status'] or '-'} {probe['verdict']})")
    if api.get("routes"):
        head.append(f"{len(api['routes'])} routes in its scripts")
    lines = ["- **API:** " + ("; ".join(head) if head else "no API base or route found in the pages")]
    lines += below
    if api.get("skipped"):
        lines.append(f"  - not looked further ({api['skipped']})")
    if api.get("routes") or api.get("bundles"):
        lines.append(f"  - {routes_line(api)}")
    # the API answered without the helper's parameters only when it gave a product list
    answered = "; the API answered without them" if probe.get("kind") == "products" else ""
    for h in api.get("helpers") or []:
        sets = f" (it sets {', '.join(h['sets'])})" if h["sets"] else ""
        lines.append(f"  - a helper adds parameters to the calls: `{h['name']}`{sets}, in {h['in']}{answered}")
    if probe:
        lines.append(f"  - {probe_line(probe)}")
    state = state_line(api)
    if state:
        lines.append(f"- **Page state:** {state}")
    return lines


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
    passed = p.get("listings") or []
    listings = (
        f"; {len(passed)} listing page(s) passed ({passed[0]['why']}: {short_url(passed[0]['url'])})" if passed else ""
    )
    if not p.get("url"):
        partial = p.get("partial")
        return (
            f"none on the {len(p.get('tried') or [])} page(s) tried (name one with --page)"
            + (f"; words for {', '.join(partial['labels'])} on {partial['url']}" if partial else "")
            + listings
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
    held = (p.get("state") or {}).get("product")
    if held:
        said.append(
            f"page state `{held['path']}`: "
            + ", ".join(
                f"{k} `{v}` (`{held['mpn_key']}`)" if k == "mpn" else f"{k} `{v}`" for k, v in held["fields"].items()
            )
        )
    return "; ".join(said or ["none"]) + listings


def api_section(api: dict[str, Any]) -> list[str]:
    """The site's own API in full: its bases and their hosts, the routes, the page state, the call asked."""
    if not (api.get("bases") or api.get("routes") or api.get("state") or api.get("probe")):
        return []
    out = ["## The site's own API, without a browser", ""]
    if api.get("bases"):
        out += ["| base | keys | named in | its host |", "|---|---|---|---|"]
        for b in api["bases"]:
            out.append(f"| {b['url']} | {', '.join(b['keys'])} | {b['source']} | {host_said(b)} |")
        out.append("")
    b = api.get("bundles") or {}
    if b:
        out.append(
            f"JS bundles: {b['read']} read of {b['named']} named, {b['bytes']:,} bytes"
            + (f"; {b['disallowed']} disallowed by robots.txt" if b.get("disallowed") else "")
            + "".join(f"; served from {h} too, its robots.txt {state}" for h, state in (b.get("hosts") or {}).items())
            + "".join(f"; {n} on {h}, an internal host, not asked" for h, n in (b.get("internal") or {}).items())
            + "."
        )
        out.append("")
    routes = api.get("routes") or []
    if routes:
        out += ["| route | method | for | in |", "|---|---|---|---|"]
        order = ("lists and search", "detail", "stock and price", "other")
        for r in sorted(routes, key=lambda r: order.index(r["kind"]))[:60]:
            out.append(f"| `{r['route']}` | {r['method']} | {r['kind']} | {r['in']} |")
        out.append("")
    for h in api.get("helpers") or []:
        out.append(f"- helper `{h['name']}` in {h['in']}" + (f": sets {', '.join(h['sets'])}" if h["sets"] else ""))
    for s in api.get("state") or []:
        out.append(f"- {s['format']} of the {s['page']} page ({short_url(s['url'])}):")
        for x in s["lists"]:
            counts = ", ".join(f"{k} {v}" for k, v in x["counts"].items())
            out.append(
                f"  - `{x['path']}`: {x['items']} items, keys {', '.join(x['keys'][:10])}"
                + (f"; beside it {counts}" if counts else "")
            )
        if s.get("product"):
            held = s["product"]
            out.append(
                f"  - the product at `{held['path']}`: "
                + ", ".join(f"{k} `{v}`" for k, v in held["fields"].items())
                + f" (part number in `{held['mpn_key']}`)"
            )
    probe = api.get("probe")
    if probe:
        out.append(f"- {probe_line(probe)}")
        for x in probe.get("others") or []:
            got = f"JSON, {x['kind']}" + (f" of {x['items']}" if x.get("items") else "") if x["json"] else "no JSON"
            got += f", an error message: {x['message']}" if x.get("error") else ""
            out.append(f"  - also asked: GET {x['url']}: {x['status'] or '-'} {x['verdict']}, {got}")
    out.append("")
    return out


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
    if f.get("region_block"):
        out.append(
            f"- **Region block:** the site refuses the country this machine is in ({f['region_block']}): run recon,"
            " and a scraper, from another"
        )
    given = (f.get("robots") or {}).get("given_disallowed") or {}
    if given:
        out.append(
            "- **robots.txt disallows the page given:** "
            + "; ".join(f"{short_url(u)} ({rule})" for u, rule in given.items())
            + ". recon reads and watches it as asked; a crawler is asked to stay off it, and a scraper of it goes"
            " against the site's word"
        )
    if f.get("wired"):
        out.append(
            "- **Captchas and bot checks wired in:** "
            + "; ".join(f"{name} ({', '.join(where[:3])})" for name, where in f["wired"].items())
            + ". The pages load them whether or not they fire: a faster or longer run may meet them"
        )
    out += api_lines(f)
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
        link = long.get("link") or []
        neutral = ", ".join(urlsplit(u).hostname or u for u in settings.NEUTRAL_HOSTS)
        if long.get("cut"):
            cut = link[-1]
            line = (
                f"- **Long session:** cut short at request {cut['at']}, {cut['minutes']} min in: this machine's link"
                f" failed ({cut['why'] or 'no answer'}, and none from {neutral} either) and did not come back within"
                f" the session, so the site is not judged past it ({how})"
            )
        elif stop:
            line = (
                f"- **Long session:** {'refused' if long.get('refused') else 'answers lost'} at request {stop['at']},"
                f" {stop['minutes']} min in: {cell(stop)} ({how})"
            )
        else:
            line = f"- **Long session:** {long['asked']} requests over {long['minutes']} min, none refused ({how})"
        for o in [o for o in link if o.get("back")]:
            line += (
                f"; this machine's link failed at request {o['at']}, {o['minutes']} min in ({o['why'] or 'no answer'},"
                f" and none from {neutral} either): not the site, the session went on {o['waited']} min later"
            )
        out.append(line)
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
    if f.get("sister_products"):
        hosts = ", ".join(f"{h} ({n} links)" for h, n in f["sister_products"].items())
        out.append(
            f"  - product links lead to another host of the same site: {hosts}; run recon on it for its product pages"
            " and sitemaps"
        )
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
    if f.get("watch"):
        out.append(f"- **What the pages fetch:** {watch_line(f['watch'])}")
    plats = f.get("platforms") or []
    out.append(
        "- **Platform:** "
        + (", ".join(p["name"] + (f" ([[{p['note']}]])" if p["note"] else "") for p in plats) or "not recognised")
        + ("; stack " + ", ".join(s["name"] for s in f.get("stacks", [])) if f.get("stacks") else "")
    )
    sm = f.get("sitemap") or {}
    moved = [s for s in sm.get("files", []) if s.get("chain")]
    out.append(
        f"- **Sitemap:** {sm.get('addresses', 0):,} addresses in {sm.get('files_read', 0)}"
        + (" file read" if sm.get("files_read") == 1 else " files read")
        + (
            f" ({sm['asked']} addresses asked, guesses and redirects among them)"
            if sm.get("asked", 0) > sm.get("files_read", 0)
            else ""
        )
        + (f"; {sm['files_left']:,} more files named, not read" if sm.get("files_left") else "")
        + (f", lastmod {sm['lastmod'][0]} to {sm['lastmod'][1]}" if sm.get("lastmod") else "")
        + "".join(f"; redirected: {chain_said(s['chain'])}" for s in moved[:3])
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
        in_state = (p.get("state") or {}).get("product")
        if in_state:
            out.append(
                f"- its state ({p['state']['format']}), at `{in_state['path']}`: "
                + ", ".join(f"{k} `{v}`" for k, v in in_state["fields"].items())
                + f"; the part number's key `{in_state['mpn_key']}`"
            )
        out.append("")

    if sample.get("rows") or sample.get("listings") or sample.get("not_products"):
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
        for x in sample.get("listings") or []:
            out.append(f"- left out, a listing ({x['why']}): {urlsplit(x['url']).path}")
        for x in sample.get("not_products") or []:
            out.append(f"- left out, {x['why']}: {urlsplit(x['url']).path}")
        out += [""] if sample.get("listings") or sample.get("not_products") else []

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

    out += api_section(f.get("api") or {})

    watched = (f.get("watch") or {}).get("pages") or []
    if watched:
        out += [
            "## What the pages fetch, in Chrome",
            "",
            "Each page loaded until its network went quiet, then scrolled once. Analytics and ads are left out.",
            "",
        ]
        for page in watched:
            out.append(f'**{short_url(page["url"])}** ({page["status"] or "-"}, "{page["title"]}"):')
            out.append("")
            if not page["calls"]:
                out += ["- no XHR or fetch", ""]
                continue
            out += ["| call | answer | what |", "|---|---|---|"]
            for c in page["calls"][:20]:
                where = "" if c["own"] else f" ({urlsplit(c['url']).hostname})"
                out.append(
                    f"| {c['method']} `{short_url(c['url'], 70)}`{where} | {c['status']} {c['type']}, "
                    f"{c['bytes']:,} bytes | {what_call(c)} |"
                )
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
            + (f" ({chain_said(s['chain'])})" if s.get("chain") else "")
        )
    llms = f.get("llms") or {}
    if llms.get("there"):
        out.append(f"- llms.txt: {llms['status']}, {llms['bytes']:,} bytes, first line: {llms['first']}")
    elif llms:
        out.append("- llms.txt: " + (llms.get("skipped") or f"not there ({llms.get('status')} {llms.get('verdict')})"))
    out.append(f"- Pages in the pool: {f.get('pool', 0)}")
    return "\n".join(out) + "\n"

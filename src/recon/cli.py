"""The recon command."""

import argparse
import asyncio
import io
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__, settings
from .findings import compare, previous_report
from .probe import Recon
from .report import report

log = logging.getLogger(__name__)


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="recon", description="Look a website over before you scrape it.")
    p.add_argument("url", help="the site's home page")
    p.add_argument("--page", help="the deeper page to probe (default: a product from the sitemap or the home page)")
    p.add_argument("--browser", action="store_true", help="open Chrome even when no client was challenged")
    p.add_argument("--no-burst", action="store_true", help="no burst, even when no protection was found")
    p.add_argument(
        "--out", type=Path, default=settings.REPORTS, help=f"where the report goes (default {settings.REPORTS})"
    )
    p.add_argument("--compare", type=Path, help="an earlier report's .json (default: the newest of this host in --out)")
    p.add_argument(
        "--products",
        type=int,
        default=settings.SAMPLE_PRODUCTS,
        help=f"product pages read for the data checks (default {settings.SAMPLE_PRODUCTS}, 0 for none)",
    )
    p.add_argument(
        "--pause", type=float, help=f"s between requests (default {settings.PAUSE}, or robots.txt's Crawl-delay)"
    )
    p.add_argument(
        "--notes", type=Path, help=f"a folder of Markdown notes to look the site up in (or ${settings.NOTES_ENV})"
    )
    p.add_argument(
        "--no-watch",
        dest="watch",
        action="store_false",
        help="do not open the home page, the product page and a listing in Chrome to list the JSON and HTML "
        "fragments they fetch (done by default where patchright and Chrome are there)",
    )
    # the watch is on by default: --watch is kept for old command lines, and does nothing
    p.add_argument("--watch", dest="watch", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(watch=True)
    p.add_argument(
        "--long",
        nargs="?",
        type=float,
        const=settings.LONG_MINUTES,
        metavar="MIN",
        help=f"also one session over MIN minutes (default {settings.LONG_MINUTES:g}), a request every "
        f"{settings.LONG_PAUSE[0]:g}-{settings.LONG_PAUSE[1]:g} s: does a bot manager turn it away later?",
    )
    p.add_argument("--version", action="version", version=f"recon {__version__}")
    args = p.parse_args(argv)
    if args.long is not None and args.long <= 0:
        p.error("--long: minutes must be more than 0")
    return args


def stem_of(home: str) -> str:
    """A report's file name from the site's host: letters, digits, dots and dashes only, no port, no userinfo.
    The host comes from the site's own redirects, so it is never used as it is."""
    try:
        host = urlsplit(home).hostname or ""
    except ValueError:
        host = ""
    return re.sub(r"[^a-z0-9.-]", "_", host.lower()).strip("._")[:100] or "site"


def write(path: Path, text: str) -> None:
    """`text` as UTF-8; what UTF-8 cannot hold (a lone surrogate from a page's JSON-LD) is replaced."""
    path.write_text(text, encoding="utf-8", errors="replace")


def changes_since(earlier: dict[str, Any], findings: dict[str, Any]) -> list[str] | None:
    """compare(), or None when the earlier report is of another shape."""
    try:
        return compare(earlier, findings)
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        log.warning("the earlier report could not be compared (%s: %s)", type(e).__name__, e)
        return None


def load_report(path: Path) -> dict[str, Any] | None:
    """An earlier report's findings, or None when the file is not one."""
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    earlier = None
    if args.compare:  # checked before the run, not after minutes of it
        earlier = load_report(args.compare)
        if earlier is None:
            print(f"recon: --compare {args.compare}: not a recon report (.json)", file=sys.stderr)
            return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)
    for noisy in ("httpx", "httpcore", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    recon = Recon(
        args.url,
        page=args.page,
        browser=args.browser,
        burst=not args.no_burst,
        pause=args.pause,
        notes=args.notes or os.environ.get(settings.NOTES_ENV),
        products=args.products,
        long=args.long,
        watch=args.watch,
    )
    findings = asyncio.run(recon.run())
    host = stem_of(findings["home"])
    source = args.compare or previous_report(args.out, host)
    if earlier is None and source:
        earlier = load_report(Path(source))
        if earlier is None:
            log.warning("%s is not a recon report: no comparison", source)
    if earlier is not None and source:
        changes = changes_since(earlier, findings)
        if changes is not None:
            findings["compared_with"] = {"file": Path(source).name, "began": earlier.get("began")}
            findings["changes"] = changes
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{host}-{datetime.now():%Y-%m-%d-%H%M%S}"  # to the second: a second run in the same minute is kept too
    # the .json first: if the report itself broke, the findings are on disk all the same
    write(args.out / f"{stem}.json", json.dumps(findings, indent=1, ensure_ascii=False, default=str))
    text = report(findings)
    write(args.out / f"{stem}.md", text)
    if isinstance(sys.stdout, io.TextIOWrapper):  # a Windows console is cp1251 or the like
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    log.info("report: %s", args.out / f"{stem}.md")
    return 0

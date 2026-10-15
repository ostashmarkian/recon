"""The recon command."""

import argparse
import asyncio
import io
import json
import logging
import os
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
    p.add_argument("--version", action="version", version=f"recon {__version__}")
    return p.parse_args(argv)


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
    )
    findings = asyncio.run(recon.run())
    host = urlsplit(findings["home"]).netloc
    source = args.compare or previous_report(args.out, host)
    if earlier is None and source:
        earlier = load_report(Path(source))
        if earlier is None:
            log.warning("%s is not a recon report: no comparison", source)
    if earlier is not None and source:
        findings["compared_with"] = {"file": Path(source).name, "began": earlier.get("began")}
        findings["changes"] = compare(earlier, findings)
    text = report(findings)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{host}-{datetime.now():%Y-%m-%d-%H%M}"
    (args.out / f"{stem}.md").write_text(text, encoding="utf-8")
    (args.out / f"{stem}.json").write_text(
        json.dumps(findings, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
    )
    if isinstance(sys.stdout, io.TextIOWrapper):  # a Windows console is cp1251 or the like
        sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    log.info("report: %s", args.out / f"{stem}.md")
    return 0

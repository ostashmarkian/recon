"""A folder of Markdown notes (an Obsidian vault, say): what it holds on a site."""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def read_notes(root: str | Path | None) -> list[tuple[Path, str]]:
    """(path, text) of every Markdown note in `root` and below, hidden folders
    (.obsidian, .git) left out; [] without one."""
    if not root or not Path(root).is_dir():
        return []
    root, found = Path(root), []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            found.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return found


def notes_on(host: str, notes: Sequence[tuple[Path, str]]) -> dict[str, Any] | None:
    """What the notes hold on the site: the one whose front matter says
    `domain: <it>` (with its `status` and `scraper`, if it has them), and how
    many name the domain; None without notes."""
    if not notes:
        return None
    domain = host.lower().removeprefix("www.")
    main, mentions = None, 0
    for path, text in notes:
        if domain not in text.lower():
            continue
        mentions += 1
        if re.search(rf"^domain:\s*(?:www\.)?{re.escape(domain)}\s*$", text, re.M | re.I):
            said = {k: re.search(rf"^{k}:\s*(\S+)", text, re.M) for k in ("status", "scraper")}
            main = {"note": path.stem, **{k: m.group(1) for k, m in said.items() if m}}
    return {"domain": domain, "note": main, "mentions": mentions}

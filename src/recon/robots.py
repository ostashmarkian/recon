"""robots.txt as RFC 9309 reads it, the same on every Python version.

Groups by User-agent, the group for "*" (recon has no product token of its
own); Allow and Disallow with "*" and "$"; the longest match wins, Allow on a
tie; comments, indentation and a UTF-8 BOM ignored. Crawl-delay and Sitemap,
which the RFC leaves to crawlers, are read too.

A robots.txt that could not be read (a 5xx, a refusal, no answer) means
"disallow everything", as the RFC asks; one that is not there (a 4xx) means
"allow everything".
"""

import math
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote, urlsplit


@dataclass
class Robots:
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern), the group for "*"
    crawl_delay: float | None = None  # seconds; math.inf when it asks for "inf"
    crawl_delay_said: str | None = None  # as written
    sitemaps: list[str] = field(default_factory=list)
    disallow_all: bool = False  # it could not be read

    def allows(self, url: str) -> bool:
        """Whether a crawler may fetch `url`: the longest matching rule decides, Allow on a tie."""
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        path = unquote((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        longest, allowed = -1, True
        for allow, pattern in self.rules:
            if not pattern or not matches(pattern, path):
                continue
            if len(pattern) > longest or (len(pattern) == longest and allow):
                longest, allowed = len(pattern), allow
        return allowed

    @property
    def disallows(self) -> int:
        return sum(1 for allow, pattern in self.rules if not allow and pattern)


@lru_cache(maxsize=4096)
def pattern_parts(pattern: str) -> tuple[tuple[str, ...], bool]:
    """A robots.txt path pattern as (its literal parts between the "*"s, whether a final "$" ends it)."""
    pattern = unquote(pattern)
    end = pattern.endswith("$")
    return tuple((pattern[:-1] if end else pattern).split("*")), end


def matches(pattern: str, path: str) -> bool:
    """Whether `path` starts as `pattern` asks: "*" any run of characters, a final "$" the end.
    Each part is placed leftmost after the one before, which is the best place for it, so nothing
    is tried twice: a "/*a*a*a*a*b" against a long path stays linear, where a regex backtracks."""
    parts, end = pattern_parts(pattern)
    first, *rest = parts
    if not path.startswith(first):
        return False
    at = len(first)
    if not rest:
        return not end or at == len(path)
    *middle, last = rest
    for part in middle:
        found = path.find(part, at)
        if found < 0:
            return False
        at = found + len(part)
    if end:
        return path.endswith(last) and len(path) - len(last) >= at
    return path.find(last, at) >= 0


def delay_of(value: str) -> float | None:
    """A Crawl-delay value in seconds; None when it is not a number a crawler can keep."""
    try:
        seconds = float(value.split()[0]) if value.split() else math.nan
    except ValueError:
        return None
    if math.isnan(seconds) or seconds < 0:
        return None
    return seconds


def parse(text: str) -> Robots:
    """The rules for "*" in a robots.txt file."""
    groups: list[tuple[list[str], list[tuple[bool, str]], list[str]]] = []  # (agents, rules, crawl-delays)
    loose_delays: list[str] = []  # a Crawl-delay written before any User-agent
    sitemaps: list[str] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    delays: list[str] = []
    in_rules = False
    for raw in text.lstrip("﻿").splitlines():
        line = raw.split("#", 1)[0].strip()
        key, colon, value = line.partition(":")
        if not colon:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "sitemap":
            sitemaps.append(value)
        elif key == "user-agent":
            if in_rules:  # a new group starts
                groups.append((agents, rules, delays))
                agents, rules, delays, in_rules = [], [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents:
            rules.append((key == "allow", value))
            in_rules = True
        elif key == "crawl-delay":
            (delays if agents else loose_delays).append(value)
            in_rules = in_rules or bool(agents)
    if agents:
        groups.append((agents, rules, delays))

    chosen_rules: list[tuple[bool, str]] = []
    chosen_delays: list[str] = []
    for group_agents, group_rules, group_delays in groups:
        if "*" in group_agents:  # several "*" groups are one
            chosen_rules += group_rules
            chosen_delays += group_delays
    said = next(iter(chosen_delays or loose_delays), None)
    return Robots(
        rules=chosen_rules,
        crawl_delay=delay_of(said) if said is not None else None,
        crawl_delay_said=said,
        sitemaps=sitemaps,
    )

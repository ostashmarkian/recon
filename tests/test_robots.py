"""robots.txt as RFC 9309 reads it."""

import math
import time

from recon.robots import Robots, matches, parse


def test_crawl_delay_indented_spaced_and_commented() -> None:
    robots = parse("User-agent: *\n    Crawl-delay : 10 # be nice\nDisallow: /x\n")
    assert (robots.crawl_delay, robots.crawl_delay_said) == (10.0, "10")


def test_a_bom_does_not_hide_the_first_group() -> None:
    robots = parse("﻿User-agent: *\nDisallow: /private\n")
    assert not robots.allows("https://s.test/private/x")
    assert robots.allows("https://s.test/public")


def test_wildcards_and_the_end_anchor() -> None:
    robots = parse("User-agent: *\nDisallow: /*add-to-cart=*\nDisallow: /*.pdf$\n")
    assert not robots.allows("https://s.test/shop/?add-to-cart=12")
    assert not robots.allows("https://s.test/a/b.pdf")
    assert robots.allows("https://s.test/a/b.pdf?x=1")


def test_star_and_end_anchor_cases() -> None:
    for pattern, path, hit in [
        ("/a*b", "/axxb/c", True),
        ("/a*b$", "/axxb", True),
        ("/a*b$", "/axxbc", False),
        ("/*", "/x", True),
        ("*", "/x", True),
        ("/x$", "/x", True),
        ("/x$", "/xy", False),
        ("/a*b*c", "/acb", False),
        ("/a*b*c", "/abbc", True),
        ("/fish*.php", "/fishheads/catfish.php?p=1", True),
    ]:
        assert matches(pattern, path) is hit, (pattern, path)


def test_a_pattern_of_many_stars_is_matched_without_backtracking() -> None:
    robots = parse("User-agent: *\nDisallow: /*a*a*a*a*a*a*a*a*a*a*b\n")
    began = time.monotonic()
    assert robots.allows("https://s.test/" + "a" * 20_000), "no b: allowed"
    assert time.monotonic() - began < 1
    assert not robots.allows("https://s.test/" + "a" * 20 + "b")


def test_the_longest_match_wins_and_allow_wins_a_tie() -> None:
    robots = parse("User-agent: *\nAllow: /\nDisallow: /search\nAllow: /search/about\n")
    assert robots.allows("https://s.test/")
    assert not robots.allows("https://s.test/search?q=1")
    assert robots.allows("https://s.test/search/about")
    assert parse("User-agent: *\nDisallow: /x\nAllow: /x\n").allows("https://s.test/x")


def test_only_the_star_groups_count_and_they_merge() -> None:
    robots = parse("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\n")
    assert robots.allows("https://s.test/c")
    assert not robots.allows("https://s.test/a")
    assert not robots.allows("https://s.test/b")


def test_delays_a_crawler_cannot_keep() -> None:
    for said in ("abc", "-1", "nan", ""):
        assert parse(f"User-agent: *\nCrawl-delay: {said}\n").crawl_delay is None, said
    assert math.isinf(parse("User-agent: *\nCrawl-delay: inf\n").crawl_delay or 0)
    assert parse("Crawl-delay: 5\nUser-agent: *\nDisallow:\n").crawl_delay == 5, "one written before any group"


def test_percent_encoding_and_comments() -> None:
    robots = parse("User-agent: *\nDisallow: /a%20b # spaces\nSitemap: https://s.test/sitemap.xml # the main one\n")
    assert not robots.allows("https://s.test/a%20b")
    assert robots.sitemaps == ["https://s.test/sitemap.xml"]
    assert robots.disallows == 1


def test_an_unreadable_robots_txt_disallows_everything() -> None:
    assert not Robots(disallow_all=True).allows("https://s.test/")
    assert Robots().allows("https://s.test/anything"), "none there: everything allowed"


def test_the_rule_that_keeps_an_address_out_is_named() -> None:
    robots = parse("User-agent: *\nDisallow: /*?*\nAllow: /search?open\n")
    assert robots.rule_for("https://s.test/?keyword=STM32") == "Disallow: /*?*"
    assert robots.rule_for("https://s.test/search?open=1") is None, "the longer Allow wins"
    assert robots.rule_for("https://s.test/cate-search") is None
    assert Robots(disallow_all=True).rule_for("https://s.test/") == "everything (robots.txt could not be read)"

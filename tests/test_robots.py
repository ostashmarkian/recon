"""robots.txt as RFC 9309 reads it."""

import math

from recon.robots import Robots, parse


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

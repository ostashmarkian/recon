"""Hostile or broken content: recon stays fast, bounded and on its feet."""

import asyncio
import gzip
import time
from pathlib import Path

import pytest
from fakes import BASE, FakeSite, scan

from recon import settings
from recon.cli import stem_of
from recon.clients import Answer
from recon.pages import drawn, gunzip, product_data, read_sitemap, visible_text
from recon.probe import Recon, fetch_within

MB = 1_000_000


@pytest.mark.parametrize(
    "body",
    [
        "<" * MB,
        "<script" * (MB // 7),
        "<script type=application/ld+json " * (MB // 34),
        "<style>" * (MB // 7),
        "<meta property='og:type' " * (MB // 25),
        '<span itemprop="sku"' * (MB // 20),
        '<script type="application/ld+json">{' * (MB // 37),
    ],
    ids=[
        "many <",
        "unclosed scripts",
        "unclosed JSON-LD script tags",
        "unclosed styles",
        "unclosed metas",
        "unclosed itemprops",
        "unclosed JSON-LD",
    ],
)
def test_a_hostile_page_is_read_in_linear_time(body: str) -> None:
    page = Answer("u", 200, {}, (), body.encode())
    began = time.monotonic()
    product_data(page)
    drawn(page)
    assert time.monotonic() - began < 3.0


def test_visible_text_drops_scripts_and_styles() -> None:
    assert visible_text("<p>a</p><script>var x = '<b>';</script><style>p{}</style><p>b &amp; c</p>") == "a b & c"
    assert visible_text("<p>kept</p><script>never closed") == "kept"


def test_a_gzip_bomb_in_a_sitemap(monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = gzip.compress(b"<urlset>" + b" " * 5_000_000 + b"</urlset>")
    with pytest.raises(ValueError, match="unpacked"):
        gunzip(bomb, 100_000)
    monkeypatch.setattr(settings, "SITEMAP_MOST", 100_000)
    with pytest.raises(ValueError):
        read_sitemap(bomb)


@pytest.mark.parametrize(
    ("home", "stem"),
    [
        ("https://shop.test/", "shop.test"),
        ("https://shop.test:8443/", "shop.test"),
        ("https://user:pw@shop.test/", "shop.test"),
        ("https://evil.test\\..\\..\\pwned/", "evil.test_.._.._pwned"),
        ("https://[shop-domain]/x", "site"),
    ],
)
def test_the_report_file_name_is_safe(home: str, stem: str, tmp_path: Path) -> None:
    assert stem_of(home) == stem
    assert (tmp_path / f"{stem_of(home)}-2026.md").resolve().parent == tmp_path.resolve()


def test_a_request_past_its_deadline_is_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "REQUEST_MOST", 0.05)

    class Slow:
        async def fetch(self, url: str, headers=None, data=None) -> Answer:
            await asyncio.sleep(5)
            return Answer(url, 200)

        async def aclose(self) -> None:
            pass

    answer = asyncio.run(fetch_within(Slow(), "https://slow.test/"))
    assert answer.error == "TimeoutError: no answer within 0.05 s"


def test_answers_are_kept_light() -> None:
    recon = Recon(BASE)
    recon.seen = []
    recon.keep(Answer("u", 200, {"server": "x"}, ("sid",), b"x" * (3 * settings.HEAD)))
    assert len(recon.seen[0].body) == settings.HEAD
    assert (recon.seen[0].headers, recon.seen[0].cookies) == ({"server": "x"}, ("sid",))


def test_a_sitemap_bomb_in_a_run_is_an_unreadable_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SITEMAP_MOST", 1_000)
    f, _, _ = scan(FakeSite(), burst=False)
    unreadable = [x for x in f["sitemap"]["files"] if str(x.get("verdict", "")).startswith("unreadable")]
    assert [x["url"] for x in unreadable] == [f"{BASE}/sitemap-2.xml.gz"]

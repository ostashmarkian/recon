"""How far an API's product list goes, the same list asked again at the end, and the size an answer gives: a shop
whose API pages 2,000 products, 50 at most a page, and stops in one of several ways past row 500."""

import json
from urllib.parse import parse_qsl

import pytest
from fakes import BASE, FakeSite, FakeWatcher, NuxtSite, scan

from recon import settings
from recon.calls import count_of, digest, list_at, paging_of, walk, with_paging
from recon.clients import Answer


def row(n: int) -> dict:
    return {"id": n, "sku": f"S-{n}", "name": f"Part {n}", "price": "1.50", "stock": 4}


def page_of(start: int, size: int, total: int = 2000) -> bytes:
    return json.dumps({"products": [row(n) for n in range(start, start + size)], "total": total}).encode()


class WindowSite(FakeSite):
    """Its product API pages TOTAL products, CAP at most a page, and past row WINDOW, by `mode`: "window" an empty
    list with its total, "error" a 400 with a message, "clamp" the window's last page again, "wrap" the first page,
    "open" rows to the end, "refuse" a 429 past page 1. From its `silent_after`-th list request on, an empty list
    and total 0 with a marker header. GET /api/catalog/products takes ?page and ?limit; POST /api/search a JSON body
    {"page": {"current", "size"}}."""

    TOTAL, CAP, WINDOW = 2000, 50, 500

    def __init__(self, mode: str = "window", silent_after: int | None = None, refuse_page: int | None = None, **kw):
        super().__init__(**kw)
        self.mode, self.silent_after, self.lists = mode, silent_after, 0
        self.refuse_page = refuse_page  # one page answered 429

    def answer(self, client, url, headers):
        path, _, query = (url.removeprefix(BASE) or "/").partition("?")
        if path not in ("/api/catalog/products", "/api/search"):
            return super().answer(client, url, headers)
        self.lists += 1
        j = {"server": "nginx", "content-type": "application/json"}
        if self.silent_after is not None and self.lists > self.silent_after:
            body = json.dumps({"products": [], "total": 0}).encode()
            return Answer(url, 200, {**j, "x-tag-upstream": "empty_header_tag"}, (), body, 0.01)
        if path == "/api/search":
            sent = json.loads(self.data or b"{}")["page"]
            at, size = int(sent["current"]), int(sent["size"])
        else:
            asked = dict(parse_qsl(query))
            at, size = int(asked.get("page", 1)), int(asked.get("limit", 24))
        size = min(size, self.CAP)
        if self.mode == "deaf":  # the page parameter is never read
            at = 1
        if (self.mode == "refuse" and at > 1) or at == self.refuse_page:
            return Answer(url, 429, {**j, "retry-after": "60"}, (), b"", 0.01)
        start, end = (at - 1) * size, self.TOTAL if self.mode == "open" else self.WINDOW
        if start >= end:
            if self.mode == "error":
                return Answer(url, 400, j, (), b'{"msg": "Result window is too large"}', 0.01)
            if self.mode == "clamp":
                start = (-(-self.WINDOW // size) - 1) * size
            elif self.mode == "wrap":
                start = 0
        rows = [row(n) for n in range(start, min(start + size, end))]
        return Answer(url, 200, j, (), json.dumps({"products": rows, "total": self.TOTAL}).encode(), 0.01)


PAGED = {
    "method": "GET",
    "url": f"{BASE}/api/catalog/products?limit=24&page=1",
    "status": 200,
    "type": "application/json",
    "sent": "",
    "body": page_of(0, 24),
}


def run(site: WindowSite, extra: tuple[dict, ...] = (PAGED,)) -> tuple[dict, str]:
    f, text, _ = scan(site, burst=False, products=0, watcher=FakeWatcher(extra=extra))
    return f, text


class TestHowFarThePagesGo:
    def test_a_page_cap_and_a_window(self):
        f, text = run(WindowSite())
        lim = f["limits"]
        assert lim["url"] == PAGED["url"], "the call that pages, not the one only sized"
        assert lim["keys"] == {"size": "limit", "page": "page"}
        assert (lim["size"]["asked"], lim["size"]["got"]) == (200, 50)
        pages = lim["pages"]
        assert (pages["kind"], pages["good"], pages["bad"], pages["rows"]) == ("stops", 21, 22, 504)
        assert len(lim["asks"]) <= settings.LIMIT_ASKS
        assert (
            "- **API limits:** GET `shop.test/api/catalog/products` (limit=24, page=1: 24 items, its total 2,000);"
            " limit=200 gave 50: a page holds 50 at most; page=21 gives items, page=22 no items (its total 2,000):"
            " about 504 rows reachable by paging of the 2,000 its total names, counting page=1 as the first" in text
        )
        assert (
            "## API limits, GET shop.test/api/catalog/products" in text and "| limit=200 | 50 items | 2,000 |" in text
        )

    def test_an_error_past_the_window(self):
        f, text = run(WindowSite("error"))
        pages = f["limits"]["pages"]
        assert (pages["kind"], pages["good"], pages["bad"]) == ("stops", 21, 22)
        assert pages["then"]["status"] == 400 and pages["then"]["message"] == "Result window is too large"
        assert "page=22 400 client-error" in text

    def test_a_clamp(self):
        """Past the window every page gives the window's last page: the page before the last is the same."""
        f, text = run(WindowSite("clamp"))
        pages = f["limits"]["pages"]
        assert (pages["kind"], pages["good"], pages["bad"]) == ("repeats", 20, 21)
        assert "from page=21 on, the pages give the same rows as page=84 (a clamp)" in text

    def test_a_wrap(self):
        f, text = run(WindowSite("wrap"))
        assert f["limits"]["pages"]["kind"] == "wraps"
        assert "page=84, the last its total names, gives the rows of page=1 (a wrap)" in text

    def test_rows_to_the_end(self):
        f, text = run(WindowSite("open"))
        assert f["limits"]["pages"]["kind"] == "to the end"
        assert "page=84, the last its total names, gives items: the pages go to the end" in text

    def test_no_request_past_a_refusal(self):
        site = WindowSite("refuse")
        f, text = run(site)
        lim = f["limits"]
        assert lim["stopped"] == "refused: 429 limited"
        assert lim["pages"]["kind"] == "not asked"
        assert [a["asked"] for a in lim["asks"]] == [{}, {"limit": 200}, {"page": 2}], "nothing after the 429"
        assert "stopped: refused: 429 limited" in text

    def test_a_page_parameter_that_changes_nothing(self):
        f, text = run(WindowSite("deaf"))
        assert f["limits"]["pages"]["kind"] == "ignored"
        assert "page=2 gives the same rows as the first page: sent, page changes nothing" in text
        assert "wrap" not in text

    def test_no_clamp_said_or_denied_when_the_page_before_the_last_is_not_read(self):
        f, text = run(WindowSite("clamp", refuse_page=83))
        assert f["limits"]["pages"]["kind"] == "end unchecked"
        assert "the page before it was not asked, so a clamp is not ruled out" in text
        assert "go to the end" not in text

    def test_a_refusal_on_the_site_s_own_api_keeps_the_burst_off(self):
        f, _, _ = scan(WindowSite("refuse"), products=0, watcher=FakeWatcher(extra=(PAGED,)))
        assert f["refused_elsewhere"] == {"limits": {"limited": 1}}
        assert "skipped" in f["burst"] and f["level"]["level"] == 1

    def test_calls_that_may_change_the_site_are_never_paged(self):
        """Other calls of an endpoint that works go through the same checks as any call asked again."""
        unsafe = {**PAGED, "url": f"{BASE}/api/catalog/products?limit=24&page=1&action=add"}
        mutation = {
            **PAGED,
            "method": "POST",
            "url": f"{BASE}/api/catalog/products?op=AddToCart",
            "sent": '{"query": "mutation AddToCart { add(id: 1) }", "variables": {"page": 1}}',
        }
        site = WindowSite()
        f, _ = run(site, (unsafe, mutation, PAGED))
        assert f["limits"]["url"] == PAGED["url"]
        assert not [p for _, _, p in site.asked if "action=add" in p or "AddToCart" in p]

    def test_a_post_with_a_json_body(self):
        """The list the page posts, its page in a JSON body one level down, rewritten with each value's type."""
        search = {
            "method": "POST",
            "url": f"{BASE}/api/search",
            "status": 200,
            "type": "application/json",
            "sent": json.dumps({"q": "x", "page": {"current": "1", "size": 24}}),
            "body": page_of(0, 24),
        }
        site = WindowSite()
        f, _ = run(site, (search,))
        lim = f["limits"]
        assert (lim["method"], lim["keys"]) == ("POST", {"page": "page.current", "size": "page.size"})
        assert (lim["pages"]["good"], lim["pages"]["bad"]) == (21, 22)
        assert site.posts.count("/api/search") >= 5

    def test_robots_txt_keeps_it_off(self):
        site = WindowSite(disallow="/api/catalog/products?limit=200")
        f, _ = run(site)
        assert f["limits"]["stopped"] == "robots.txt disallows the address"
        assert not [p for _, _, p in site.asked if "limit=200" in p]

    def test_a_list_only_sized(self):
        """The API step's list names a page size and no page: its size is measured, its pages are not."""
        f, _, _ = scan(WindowSite(), burst=False, products=0)
        lim = f["limits"]
        assert (lim["url"], lim["size"]["got"], "pages" in lim) == (f"{BASE}/api/catalog/products?limit=24", 50, False)

    def test_a_list_with_no_paging_is_said(self):
        f, text, _ = scan(NuxtSite(), burst=False, products=0)
        said = "the product list's call names no page or page size, nor does its answer"
        assert f["limits"]["skipped"] == said and f"- **API limits:** not measured ({said})" in text


class TestAskedAgain:
    def test_the_same_items_at_the_end(self):
        f, text = run(WindowSite("open"))
        again = f["again"]
        assert (again["silent"], again["refused"], again["now"]["items"]) == (False, False, 24)
        assert "- **Asked again:** asked again at the end of the run" in text and ": 24 items (at first 24)" in text

    def test_a_silent_refusal(self, monkeypatch):
        """The API step's list (1), its page size (2), then nothing until the end of the run: an empty list with a
        200 there is a refusal a scraper must catch by its count. It is protection: no burst runs."""
        monkeypatch.setattr(settings, "LIMIT_ASKS", 1)
        f, text, _ = scan(WindowSite("open", silent_after=2), products=0)
        again = f["again"]
        assert (again["silent"], again["first"]["items"], again["now"]["total"]) == (True, 24, 0)
        assert again["headers"] == {"x-tag-upstream": "empty_header_tag"}
        assert f["level"]["level"] == 1 and f["level"]["label"] == "a silent refusal"
        assert "skipped" in f["burst"], "a silent refusal keeps the burst off"
        assert "gave no items with a 200 (at first 24): a silent refusal; new in its answer:" in text
        assert "`x-tag-upstream: empty_header_tag`" in text


class TestSize:
    def test_the_largest_count_an_answer_gave(self):
        f, text = run(WindowSite())
        assert f["size"]["total"] == 2000
        assert "- **Size:** 2,000, the largest count an answer gave (GET " in text


class TestCalls:
    def test_count_of(self):
        assert [count_of(v) for v in (413, "413", {"value": 413}, True, -1, "4.1", None)] == [
            413,
            413,
            413,
            None,
            None,
            None,
            None,
        ]

    def test_the_total_by_its_key(self):
        """The shallowest total; a bare "count" only when no other key gives one."""
        assert walk({"count": 24, "result": {"resultTotal": 413, "items": [row(1), row(2)]}})[2] == 413
        assert walk({"count": 24, "items": [row(1), row(2)]})[2] == 24
        assert walk({"hits": {"total": {"value": 9}, "hits": [row(1), row(2)]}})[2] == 9

    def test_list_at_a_path(self):
        data = {"result": {"pageOfItems": [row(1)]}, "groups": [{"rows": [row(2), row(3)]}]}
        assert list_at(data, "result.pageOfItems") == [row(1)], "one item: no list for json_shape, a list here"
        assert list_at(data, "groups[].rows") == [row(2), row(3)]
        assert list_at({"result": {"pageOfItems": []}}, "result.pageOfItems") == []
        assert list_at({"result": None}, "result.pageOfItems") is None
        assert list_at([row(1), row(2)], "(the answer)") == [row(1), row(2)]
        assert digest([row(1)]) == digest([row(1)]) != digest([row(2)])

    @pytest.mark.parametrize(
        ("call", "changes", "want"),
        [
            (
                {"method": "GET", "url": "https://a.test/x?keyword=a%20b&page=2&page_size=50&p=3"},
                {("page_size",): 200},
                "https://a.test/x?keyword=a%20b&page=2&page_size=200&p=3",
            ),
            (
                {"method": "POST", "url": "https://a.test/x", "sent": "cate_id=1&page=1&params%5Ba%5D=x"},
                {("page",): 11},
                "cate_id=1&page=11&params%5Ba%5D=x",
            ),
            (
                {"method": "POST", "url": "https://a.test/x", "sent": '{"from": 0, "size": "20"}'},
                {("size",): 40},
                '{"from": 0, "size": "40"}',
            ),
        ],
    )
    def test_paging_rewritten_and_nothing_else(self, call, changes, want):
        got = with_paging(call, changes)
        assert (got["url"] if call["method"] == "GET" else got["sent"]) == want

    def test_which_parameters_page(self):
        """`p` is no page: a signing helper sets it (addAntiSpiderParams)."""
        call = {"method": "GET", "url": "https://a.test/x?p=3&pn=2&rows=10&start=20"}
        assert paging_of(call) == {"page": (("pn",), 2), "size": (("rows",), 10), "offset": (("start",), 20)}
        assert paging_of({"method": "POST", "url": "https://a.test/x", "sent": "[1, 2]"}) == {}


class TestPagingNamedByTheAnswer:
    """A Nuxt shop's search, as unikeyic.com's: a part number gives its one product, so the category is asked; the
    call sends no page, but the answer names page and pageSize, and they work when sent; the pages stop at 50,
    the later ones giving page 50 again: 1,250 rows of the 10,000 its total names."""

    def test_the_category_then_the_page_and_its_size_from_the_answer(self):
        f, text, _ = scan(NuxtSite(exact=True, paged=True), burst=False, products=0)
        probe = f["api"]["probe"]
        assert (probe["kind"], list(probe["filled"])) == ("products", ["cate_id"]), "the category after the one product"
        lim = f["limits"]
        assert lim["from_answer"] == {"page": "page", "size": "pageSize"}
        assert [a["asked"] for a in lim["asks"][:2]] == [{"page": 2}, {"pageSize": 12}], "each checked by sending it"
        assert (lim["size"]["got"], lim["pages"]["kind"], lim["pages"]["bad"], lim["pages"]["rows"]) == (
            200,
            "repeats",
            50,
            1250,
        )
        assert "`page`, `pageSize` named by its answer, not sent by the call: sent, they change the page" in text
        assert "from page=50 on, the pages give the same rows as page=400 (a clamp): about 1,250 rows" in text

    def test_keys_the_answer_names_that_change_nothing_are_not_kept(self):
        class Deaf(NuxtSite):
            def api_answer(self, url):  # page and pageSize named, never read
                return super().api_answer(url.split("&page")[0])

        f, text, _ = scan(Deaf(paged=True), burst=False, products=0)
        lim = f["limits"]
        assert lim["skipped"] == (
            "the product list's call sends no page or page size; its answer names `page`, `pageSize`, but sent, they"
            " did not change the page"
        )
        assert "pages" not in lim and "size" not in lim
        assert "- **API limits:** not measured (the product list's call sends no page or page size;" in text

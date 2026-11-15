"""The watch's click on a listing's next page, and an answer that never ends."""

from fakes import BASE, LISTED, FakeSite, FakeWatcher, scan

from recon.calls import call_record
from recon.report import what_call

NEXT_PAGE = {
    "method": "POST",
    "url": f"{BASE}/api/catalog/page",
    "status": 200,
    "type": "application/json",
    "sent": '{"page": 2}',
    "body": LISTED,
}


def test_the_listing_s_next_page_is_clicked_and_what_it_fetches_is_marked():
    watcher = FakeWatcher(after_click=(NEXT_PAGE,))
    f, text, _ = scan(FakeSite(), burst=False, products=0, watcher=watcher)
    listing = f"{BASE}/category/?page=2"
    assert watcher.clicked == [listing], "the listing only"
    page = next(p for p in f["watch"]["pages"] if p["url"] == listing)
    assert page["clicked"]["control"] == "a[rel~='next']"
    after = [c for c in page["calls"] if c.get("after_click")]
    assert [c["url"] for c in after] == [NEXT_PAGE["url"]] and after[0]["kind"] == "products"
    assert "the listing's next page clicked (a[rel~='next']), 1 calls after it" in text
    assert "POST `/api/catalog/page` (after the click)" in text
    assert "Its next-page control clicked: `a[rel~='next']`" in text


def test_no_control_to_click_is_said():
    f, text, _ = scan(FakeSite(), burst=False, products=0, watcher=FakeWatcher())
    page = next(p for p in f["watch"]["pages"] if p.get("clicked"))
    assert page["clicked"] == {"control": None}
    assert "no next-page control found on the listing to click" in text


def test_an_answer_still_open_is_said_not_read():
    call = {"method": "GET", "url": f"{BASE}/api/events", "status": 200, "type": "text/event-stream", "sent": ""}
    record = call_record({**call, "body": b"", "unfinished": True}, "shop.test")
    assert record["unfinished"] and "an answer still open after 10 s (a stream or a long poll)" in what_call(record)

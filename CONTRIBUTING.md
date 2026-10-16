# Contributing

Thanks for looking. The code is the package in `src/recon/` (the README's
Architecture section maps its modules); the tests are in `tests/`.

## Set up

```
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,browser]"   # .venv/bin/python on Linux and macOS
```

## Before a pull request

```
pytest
ruff check src tests && ruff format --check src tests
mypy
```

All pass, offline: the tests never touch the network. They run the real `Recon`
against `FakeSite` (`tests/fakes.py`). A new test must fail when the code it
guards is broken: break the code on purpose once and watch the test fail.

## Easy places to add something

- **A platform:** a line in `PLATFORMS` (`platforms.py`), with the markers its
  pages show (`html`, `header`, `cookie` or `robots`). If it has an open API, add
  it to `api_request()` and `api_says()`.
- **An anti-bot service:** its refusal in `judge()`, its headers or cookies in
  `vendors_of()` (`classify.py`), and its name in `GUARDS` if it can shut an IP out.
- **A search service:** a line in `SEARCH_SERVICES` (`pages.py`).
- **A language:** words for a part number, maker, VAT or stock in `LABELS`
  (`pages.py`); quantity-discount words in `LADDER_WORDS` (`sample.py`).
- **A robots.txt rule:** `robots.py` follows RFC 9309; a case it reads wrong
  is a test in `tests/test_robots.py` first.
- **A tunable:** `settings.py`; code reads it as `settings.NAME`, so tests can
  monkeypatch it.

Please include one sample of what you saw: the header, the cookie, the page text.

## What recon will not do

recon solves no captchas, logs in nowhere, and runs no concurrent test against a
site that asks for a Crawl-delay or sits behind an anti-bot service. Pull
requests that change that will not be merged.

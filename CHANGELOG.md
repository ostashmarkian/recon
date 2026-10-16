# Changelog

## Unreleased: the first update after 1.0.0

- The verdict opens with a protection level from 0 (none seen) to 5 (nothing let in): who refused, what got
  through, whether a real browser's cookie carries over, and what one run cannot see.
- Akamai Bot Manager named from its cookies (`ak_bmsc`, `bm_mi`, `bm_sv`); Akamai's block page recognised with its
  markers written as HTML entities (before, it showed as a plain refusal).
- Clients named in plain words in the report (`curl_cffi as Chrome`, `httpx HTTP/2 + PHA`), with a legend; the
  curl User-Agent is `curl CLI`, so it is not mistaken for curl_cffi.
- The User-Agent filter line is not repeated when the protection level already says it.
- 88 tests.

## 1.0.0 - 2026-10-15

The first release.

**Protection and the way in**
- 7 HTTP clients: httpx over HTTP/1.1 and HTTP/2, each also with
  `post_handshake_auth`; curl_cffi as Chrome, Safari and Firefox.
- 13 User-Agents through the first client let in. A filter of User-Agents by
  name is reported, not counted as protection.
- 10 anti-bot services and common CDNs recognised from headers, cookies and
  challenge pages.
- Google Chrome via patchright when a client is challenged: is Chrome let in,
  and does its `cf_clearance` carry over to the other clients.

**Pace**
- A session-lock test: one cookie jar against none.
- A burst of 1 to 16 requests at a time, only when nothing protects the site
  and robots.txt asks for no Crawl-delay. It stops at the first sign of
  strain, and checks 30 s later that the site has let go.
- robots.txt's Crawl-delay paces the requests and turns off the concurrent
  tests.

**Platform and catalogue**
- 25 platforms recognised. Their open APIs are asked for the catalogue count
  and a product's SKU and MPN (WooCommerce, Shopify, Magento, BigCommerce,
  OpenCart, Zoho).
- Sitemaps read, plain or gzipped, or found at the usual paths when robots.txt
  names none.
- Search services, page-data blobs and the API paths the pages call.

**Data quality**
- schema.org Product in JSON-LD and microdata, product meta tags, and the
  page's words for part number, maker, VAT and stock.
- A sample of 10 product pages, flagging:
  - an MPN that equals the SKU, or that is a GTIN, Excel notation or a placeholder;
  - one MPN on several products;
  - the same or a capped stock on every page;
  - price ladders, and VAT in or out of the price.
- Soft 404s and listings that wrap back to page 1; stale caches; pages drawn
  by JavaScript.

**Reports**
- Markdown and JSON per run, compared with the previous report of the same host.
- `--notes DIR`: the site and its platform looked up in a folder of Markdown notes.

**Engineering**
- A typed package in `src/recon/`. Every network call goes through one
  `Client` protocol, and every tunable lives in `settings`.
- 85 pytest tests against a stand-in shop, with no network.
- ruff and mypy clean. CI runs on Linux and Windows, Python 3.12 to 3.14.

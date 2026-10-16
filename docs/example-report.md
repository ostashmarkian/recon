<!-- A real recon report (1.0.0). The shop's name, its product ids, part numbers, maker and
     analytics id are replaced; every verdict, count and timing is as recon found it. -->

# recon: shop.example

2026-10-15T18:00:00+03:00, 85 requests, 72.1 s. Home: https://shop.example/

## Verdict

- **Protection: level 3 of 5, a filter by fingerprint.** Cloudflare turns away httpx HTTP/2, httpx HTTP/1.1, httpx HTTP/2 + PHA (challenge) with a browser User-Agent; let in: httpx HTTP/1.1 + PHA, curl_cffi as Chrome, curl_cffi as Safari, curl_cffi as Firefox. Python's own TLS is what is turned away: the TLS fingerprint decides. httpx with PHA passes over HTTP/1.1 only, so the HTTP/2 fingerprint counts too. A real browser is let in and gets cf_clearance, but the cookie does not carry over to the clients.
  - seen: in front: Cloudflare; clients turned away: httpx HTTP/2 challenge on /, /1000000001; httpx HTTP/1.1 challenge on /, /1000000001; httpx HTTP/2 + PHA challenge on /, /1000000001
  - not seen in one run: limits over a long session, behaviour scoring, the IP's reputation
- **User-Agent filter:** challenge HeadlessChrome, empty, python-requests, python-httpx, Python-urllib, curl CLI, Wget, Scrapy, AhrefsBot; blocked GPTBot, ClaudeBot, Bytespider (not protection here: the burst sends a browser's)
- **Way in:** httpx HTTP/1.1 + PHA, a browser User-Agent, no cookies (a session lock)
- **Session lock:** yes: 1.98/s with one cookie jar, 6.3/s with none, 4 at a time
- **Burst:** skipped (protection found)
- **Product data:** JSON-LD mpn `PN-0001-A`, sku `1000000001`, brand `ACME COMPONENTS`, price `19.9800`, currency `USD`, availability `InStock`; no gtin; words for part number, maker, stock
- **Product sample:** 10 of 10 pages read; mpn 10/10, sku 10/10, price 10/10; currency USD; a stock number on 0; no trap seen
- **Freshness:** cache DYNAMIC 11/11; Cache-Control `private`
- **Not-found pages:** a made-up product redirects to /Errors/GenericError; a made-up path redirects to /Errors/GenericError
- **Catalogue sources:** none seen in the pages
- **Platform:** not recognised; stack ASP.NET
- **Sitemap:** 195,151 addresses in 8 files read, lastmod 2025-01-13 to 2026-01-13

## Clients, with a browser User-Agent

| client | `/` | `/1000000001` | `/robots.txt` |
|---|---|---|---|
| httpx HTTP/2 | 403 challenge (Cloudflare), h2 0.23s | 403 challenge (Cloudflare), h2 0.04s | 200 ok, h2 0.61s |
| httpx HTTP/1.1 | 403 challenge (Cloudflare), h1 0.11s | 403 challenge (Cloudflare), h1 0.13s | 200 ok, h1 0.26s |
| httpx HTTP/2 + PHA | 403 challenge (Cloudflare), h2 0.14s | 403 challenge (Cloudflare), h2 0.04s | 200 ok, h2 0.18s |
| httpx HTTP/1.1 + PHA | 200 ok, h1 0.74s | 200 ok, h1 0.25s | 200 ok, h1 0.19s |
| curl_cffi as Chrome | 200 ok, h2 0.74s | 200 ok, h2 0.32s | 200 ok, h2 0.05s |
| curl_cffi as Safari | 200 ok, h2 0.78s | 200 ok, h2 0.23s | 200 ok, h2 0.06s |
| curl_cffi as Firefox | 200 ok, h2 0.35s | 200 ok, h2 0.22s | 200 ok, h2 0.05s |

PHA: httpx with `post_handshake_auth`, Python's other TLS ClientHello. curl_cffi: libcurl sending a browser's TLS and HTTP/2 fingerprint, with that browser's own User-Agent.

Deeper page (a product link): https://shop.example/1000000001

## User-Agents, through httpx HTTP/1.1 + PHA, on the home page

| User-Agent | answer |
|---|---|
| Chrome | 200 ok, h1 0.74s |
| HeadlessChrome | 403 challenge (Cloudflare), h1 0.62s |
| empty | 403 challenge (Cloudflare), h1 0.12s |
| python-requests | 403 challenge (Cloudflare), h1 0.12s |
| python-httpx | 403 challenge (Cloudflare), h1 0.12s |
| Python-urllib | 403 challenge (Cloudflare), h1 0.12s |
| curl CLI | 403 challenge (Cloudflare), h1 0.11s |
| Wget | 403 challenge (Cloudflare), h1 0.13s |
| Scrapy | 403 challenge (Cloudflare), h1 0.25s |
| GPTBot | 403 blocked (Cloudflare), h1 0.11s |
| ClaudeBot | 403 blocked (Cloudflare), h1 0.12s |
| Bytespider | 403 blocked (Cloudflare), h1 0.12s |
| AhrefsBot | 403 challenge (Cloudflare), h1 0.11s |

## Browser (Chrome through patchright, headless)

On https://shop.example/: first answer 200, challenged: False, passed: True (title "Shop.example") in 1.6 s; cookies: ARRAffinity, Shop.customer, _ga, _ga_XXXXXXXXXX, cf_clearance
- its cf_clearance + User-Agent on httpx HTTP/2: 403 challenge (Cloudflare), h2 0.11s
- its cf_clearance + User-Agent on httpx HTTP/1.1: 403 challenge (Cloudflare), h1 0.12s
- its cf_clearance + User-Agent on httpx HTTP/2 + PHA: 403 challenge (Cloudflare), h2 0.23s

## Session

Cookies set: ARRAffinity, ASP.NET_SessionId, Shop.customer, Shop.viewed.items.

- with one jar: 1.98/s, p50 1.604s, {'200 ok': 11, '302 redirect': 1}
- with no cookies: 6.3/s, p50 0.524s, {'200 ok': 11, '302 redirect': 1}

## Product page

https://shop.example/1000000001

- JSON-LD Product: name `PN-0001-A`, sku `1000000001`, mpn `PN-0001-A`, brand `ACME COMPONENTS`, price `19.9800`, currency `USD`, availability `InStock`
- meta: og:type `product`
- the page's words, part number: `Part Number: PN-0001-A Manufacturer: Acme Components`
- the page's words, maker: `Manufacturer: Acme Components Item ID: 1000000001 Acme `
- the page's words, stock: `IN STOCK — SHIPS TODAY Acme Components PN-0` | `in stock) Quantity: Questions about this part? Ask us a`

## Product sample, 10 pages

| field | mpn | sku | gtin | brand | price | currency | availability | inventory |
|---|---|---|---|---|---|---|---|---|
| pages | 10/10 | 10/10 | 0/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0/10 |

| page | mpn | sku | price | stock | ladder |
|---|---|---|---|---|---|
| /1000000001 | PN-0001-A | 1000000001 | 19.9800 USD | - | - |
| /1000000002 | PN-0002-A | 1000000002 | 186.3400 USD | - | - |
| /1000000003 | PN-0003-A | 1000000003 | 1.5000 USD | - | - |
| /1000000004 | PN-0004-A | 1000000004 | 2.9900 USD | - | - |
| /1000000005 | PN-0005-A | 1000000005 | 0.9000 USD | - | - |
| /1000000006 | PN-0006-A | 1000000006 | 55.0000 USD | - | - |
| /1000000007 | PN-0007-A | 1000000007 | 26.6200 USD | - | - |
| /1000000008 | PN-0008-A | 1000000008 | 23.9600 USD | - | - |
| /1000000009 | PN-0009-A | 1000000009 | 19.9800 USD | - | - |
| /1000000010 | PN-0010-A | 1000000010 | 19.8000 USD | - | - |

## Not-found pages

| probe | address | answer | title | bytes |
|---|---|---|---|---|
| a made-up product | https://shop.example/9999999999 | 302 redirect, h1 0.36s to /Errors/GenericError | Object moved | 498 |
| a made-up path | https://shop.example/recon-x7q2-no-such-page/ | 302 redirect, h1 0.61s to /Errors/GenericError | Object moved | 498 |

## Site

- Home: 200 ok, h2 0.82s
- In front: Cloudflare (cf-ray, server: cloudflare)
- ASP.NET: header x-aspnet-version, header x-powered-by: asp.net
- robots.txt: 200 ok, 3 Disallow lines, no sitemap named
  - https://shop.example/sitemap.xml: 200 index, 7
  - https://shop.example/sitemap1.xml.gz: 200 urls, 34
  - https://shop.example/sitemap2.xml.gz: 200 urls, 772
  - https://shop.example/sitemap3.xml.gz: 200 urls, 39,996
  - https://shop.example/sitemap4.xml.gz: 200 urls, 39,992
  - https://shop.example/sitemap5.xml.gz: 200 urls, 39,992
  - https://shop.example/sitemap6.xml.gz: 200 urls, 39,992
  - https://shop.example/sitemap7.xml.gz: 200 urls, 34,373
- Pages in the pool: 4949


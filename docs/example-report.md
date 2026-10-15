<!-- A real recon report (1.0.0). The shop's name, its product ids, part numbers, maker and
     analytics id are replaced; every verdict, count and timing is as recon found it. -->

# recon: shop.example

2026-10-15T18:00:00+03:00, 85 requests, 61.6 s. Home: https://shop.example/

## Verdict

- **Protection:** in front: Cloudflare; clients turned away: httpx-h2 challenge on /, /1000000001; httpx-h1 challenge on /, /1000000001; httpx-h2-pha challenge on /, /1000000001
- **User-Agent filter:** challenge HeadlessChrome, empty, python-requests, python-httpx, Python-urllib, curl, Wget, Scrapy, AhrefsBot; blocked GPTBot, ClaudeBot, Bytespider (not protection here: the burst sends a browser's)
- **Way in:** httpx-h1-pha, a browser User-Agent, no cookies (a session lock)
- **Session lock:** yes: 2.3/s with one cookie jar, 5.15/s with none, 4 at a time
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
| httpx-h2 | 403 challenge (Cloudflare), h2 0.24s | 403 challenge (Cloudflare), h2 0.07s | 200 ok, h2 0.21s |
| httpx-h1 | 403 challenge (Cloudflare), h1 0.13s | 403 challenge (Cloudflare), h1 0.12s | 200 ok, h1 0.25s |
| httpx-h2-pha | 403 challenge (Cloudflare), h2 0.16s | 403 challenge (Cloudflare), h2 0.03s | 200 ok, h2 0.19s |
| httpx-h1-pha | 200 ok, h1 0.81s | 200 ok, h1 0.24s | 200 ok, h1 0.20s |
| curl-chrome | 200 ok, h2 0.31s | 200 ok, h2 0.26s | 200 ok, h2 0.19s |
| curl-safari | 200 ok, h2 0.33s | 200 ok, h2 0.26s | 200 ok, h2 0.20s |
| curl-firefox | 200 ok, h2 0.88s | 200 ok, h2 0.24s | 200 ok, h2 0.18s |

Deeper page (a product link): https://shop.example/1000000001

## User-Agents, through httpx-h1-pha, on the home page

| User-Agent | answer |
|---|---|
| Chrome | 200 ok, h1 0.30s |
| HeadlessChrome | 403 challenge (Cloudflare), h1 0.13s |
| empty | 403 challenge (Cloudflare), h1 0.11s |
| python-requests | 403 challenge (Cloudflare), h1 0.11s |
| python-httpx | 403 challenge (Cloudflare), h1 0.12s |
| Python-urllib | 403 challenge (Cloudflare), h1 0.15s |
| curl | 403 challenge (Cloudflare), h1 0.18s |
| Wget | 403 challenge (Cloudflare), h1 0.18s |
| Scrapy | 403 challenge (Cloudflare), h1 0.22s |
| GPTBot | 403 blocked (Cloudflare), h1 0.17s |
| ClaudeBot | 403 blocked (Cloudflare), h1 0.12s |
| Bytespider | 403 blocked (Cloudflare), h1 0.12s |
| AhrefsBot | 403 challenge (Cloudflare), h1 0.10s |

## Browser (Chrome through patchright, headless)

On https://shop.example/: first answer 200, challenged: False, passed: True (title "Shop.example") in 1.6 s; cookies: ARRAffinity, Shop.customer, _ga, _ga_XXXXXXXXXX, cf_clearance
- its cf_clearance + User-Agent on httpx-h2: 403 challenge (Cloudflare), h2 0.15s
- its cf_clearance + User-Agent on httpx-h1: 403 challenge (Cloudflare), h1 0.13s
- its cf_clearance + User-Agent on httpx-h2-pha: 403 challenge (Cloudflare), h2 0.16s

## Session

Cookies set: ARRAffinity, ASP.NET_SessionId, Shop.customer, Shop.viewed.items.

- with one jar: 2.3/s, p50 1.525s, {'200 ok': 11, '302 redirect': 1}
- with no cookies: 5.15/s, p50 0.498s, {'200 ok': 11, '302 redirect': 1}

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
| a made-up path | https://shop.example/recon-x7q2-no-such-page/ | 302 redirect, h1 0.50s to /Errors/GenericError | Object moved | 498 |

## Site

- Home: 200 ok, h2 0.33s
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
- Pages in the pool: 4948


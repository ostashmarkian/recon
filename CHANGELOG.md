# Changelog

## Unreleased

- **A new scale.** The top of the old one, "nothing let in, not even a browser",
  was only an unreachable site. Now:
  - 4 is a bot manager in front: a service that scores each client over its
    session, so a short run is let in and a long one can be turned away. It is
    recognised by its bot product's markers: Akamai's Bot Manager cookies,
    Cloudflare's `__cf_bm`, DataDome, HUMAN, Kasada, Myra. A WAF that acts on its
    owner's rules stays at what was seen, and the verdict says that this holds
    until the rules change;
  - 5 is a challenge for every client, where only a real browser gets in;
  - a site that lets not even a browser in is "closed", and one where no client
    got an answer is "not judged". Neither is on the scale.
- **`--long [MIN]`:** one cookie jar walks the pages robots.txt allows for MIN
  minutes (15), a request every 5 to 10 s, and stops at the first refusal. The
  report says at which request and minute, and the level takes it in: a 429 is
  a rate limit, any other refusal is level 4. Its refusal keeps the burst off.
  It runs behind protection too, since it is slower than the rest.
- **Sitemaps read depth first.** An index's files are read next, four of each
  picked from end to end, product files first. Indexes of indexes no longer
  spend the whole budget of 30 files on indexes: a run had read 30 and found 0
  addresses. Addresses are kept from all over each file, and the report says
  how many files were named but not read.
- **Product pages looked for a family at a time.** Addresses of one shape
  (`/product/123/`) are a family. The tries take one of each in turn, so a
  shop's marketing pages under `/products/` no longer use up every try, and
  the sitemap's other pages are tried after the product links. A product
  address that redirects on the site is followed once. The sample is drawn
  from the found product's family first.
- **`--watch`: what the pages fetch.** Chrome opens the home page, the product
  page and a listing, each until its network is quiet and once scrolled, and
  the report lists every XHR and fetch call with what its answer holds:
  - a product list: where it sits, how many items, their keys, and which of
    ids, names, prices and stock they carry;
  - the paging keys;
  - an HTML fragment of product links;
  - a GraphQL operation.

  Analytics and ads are left out. The catalogue's own API usually shows only
  here, since a page's scripts call it. It runs only where a plain client was
  let in, and only on pages robots.txt allows.
- 192 tests.

## 1.1.0 - 2026-10-17

- The verdict opens with a protection level from 0 (none seen) to 5 (nothing let in): who refused, what got
  through, whether a real browser's cookie carries over, and what one run cannot see.
- Akamai Bot Manager named from its cookies (`ak_bmsc`, `bm_mi`, `bm_sv`); Akamai's block page recognised with its
  markers written as HTML entities (before, it showed as a plain refusal).
- Clients named in plain words in the report (`curl_cffi as Chrome`, `httpx HTTP/2 + PHA`), with a legend; the
  curl User-Agent is `curl CLI`, so it is not mistaken for curl_cffi.
- The User-Agent filter line is not repeated when the protection level already says it.

From an audit (2026-10-16):

- **Politeness.** robots.txt is read by recon's own RFC 9309 parser, the same on every
  Python. It honours comments, indentation, a BOM, `*` and `$`, and the longest
  match; redirects are followed. A robots.txt that cannot be read disallows
  everything. A Crawl-delay is read wherever its line sits; over 60 s, the run
  stops after robots.txt. Cart and checkout links, including those in a query
  string, are left out. A refusal in any step keeps the burst off. Platform
  APIs, guessed sitemaps and not-found probes are asked only where robots.txt
  allows.
- **Safety of the tool:**
  - bodies are read up to a limit, decoded, so a compression bomb is cut;
  - a gzipped sitemap unpacks to a limit;
  - each request has one deadline;
  - parsing hostile HTML is linear: 1 MB of unclosed tags takes under a second;
  - the report's file name keeps only safe characters of the host, so a redirect
    can no longer move the report out of `--out`;
  - findings keep light copies of the answers.
- **Robustness.** Each step runs isolated: a failure goes into an Errors section
  and the other steps go on. An unparseable address, deep JSON-LD, zone-less
  Last-Modified dates, a lone surrogate and a foreign `--compare` file no
  longer break the run.
- **Verdicts:**
  - a home-page redirect to a captcha is not followed, and one to another
    site stops the run, naming the address to run recon on;
  - other 4xx are `client-error`, not `ok`, and 408 is a lost answer;
  - a block redirect is judged by its path only;
  - Imperva's script on a normal page and `x-datadome` on a 404 are not
    challenges;
  - robots.txt is never a main page;
  - the level is consistent with `let_in` and names services only;
  - `&amp;` in sitemaps is decoded, and links come from `<a href>` only;
  - comparisons ignore byte counts and timings.
- The real httpx and curl_cffi clients are tested against a local server, and the
  concurrency limits and the only POST are tested.

From what scrapers met on real shops:

- **The burst stops when pages shrink.** A server can fail quietly under load and
  still answer 200: a 644-byte database error in place of a product page was seen.
  Two answers in a step under half the smallest page of the first step (one at a
  time) stop it, once one of them, read alone, is twice as big. A page that small
  by itself lowers that floor instead.
- **Myra Security** is recognised (`Server: myracloud`, its `/myracloud-blocked/` and
  `/myracloud-captcha/` pages) and counts as protection. It lets the first requests
  in and bans the whole IP minutes later, so the burst stays off behind it.

From an independent review against 1.0.0 (local scenarios and four live shops):

- **The protection level reads only what was seen:**
  - a client turned away is one refused or cut off; one with no answer in time is
    named as such and is no "filter by fingerprint";
  - a 4xx on the deeper page is that page's own, not a refusal, so it no longer
    reads "nothing let in";
  - when no client got an answer at all, the level says it could not judge;
  - a rate limit is a 429, or a refusal with several requests at a time; other
    refusals met one at a time are named with their step, with no level raised.
- A run stopped early (a Crawl-delay over the limit, a home page on another site)
  carries no level and no way in.
- Imperva's script on a small 404 is no block.
- JSON-LD is read from the whole page, not only its first megabyte: big pages
  carry it at their end.
- robots.txt patterns are matched without backtracking: a pattern of many `*`
  stalled a run for four minutes.
- More links that change a site's state are left out: `?remove_item=`, `?buy=`,
  `/order/add`, and a cart in Czech, Polish, German, French, Spanish, Italian,
  Dutch and Russian.
- Report names carry the second, so a second run in the same minute no longer
  overwrites the first.
- 166 tests.

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

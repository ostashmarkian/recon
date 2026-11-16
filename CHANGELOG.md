# Changelog

## Unreleased

From building scrapers for two electronics marketplaces on one Alibaba Cloud API, where the page size, the depth
of the pages, the terms' pace and a silent refusal were all found by hand:

- **API limits.** The product list a plain client got from the API (one the pages fetch, a POST among them, or one
  the API step asked) is asked with a page of 200 items: how many a page holds at most (a `page_size` of 100 had
  come back as 50, unsaid). Then with the last page its total names: rows to the end, none, an error, or one page
  again (the page before the last the same: a clamp; the first page's rows: a wrap). Where they stop or repeat,
  the pages between are halved, by ratio while far apart, to the last page that gives its own rows, and the
  verdict says how many rows paging reaches of the total (a window of 500 rows on one shop, 1,250 on the other).
  The page, the offset and the page size are found in a query, a form body or a JSON body one level deep, and
  rewritten there alone, each value of the type it had; `p` is no page (a signing helper sets it). A call that
  sends neither, as one shop's search by category, is tried with the page and the size its answer names
  (`"page": 1, "pageSize": 25`), each kept only when sending it changes the answer: the next page other rows,
  half the size half the items. The next page is asked first: when it gives the first page's rows, the page
  parameter changes nothing, and no wrap or clamp is said. A verdict says only what was asked: the last page giving
  items with the page before it unread is "a clamp not ruled out", not "to the end". Only a call that passes the
  replay's checks is paged (no route that may change the site's state, no GraphQL mutation, no internal host,
  robots.txt). 15 requests at most, one at a time; a refusal ends them, and one on the site's own pages keeps the
  burst off.
- **A part number's search that gives its one product** is asked once more with a listing's category id, within
  the same four requests: the search had answered "data, no product list", and the list stayed unread.
- **The same list asked again at the end of the run.** One shop's API, after a sample at 5 requests a second,
  answered new sessions with `total 0`, a 200 and `x-tag-upstream: empty_header_tag`: a silent refusal that read
  as an empty category. Now an empty list where the first answer held items is said, with the headers new in
  the answer; it counts as protection (no burst runs) and lifts a level 0 to 1, "a silent refusal".
- **Size.** The largest count an answer gave (a list's `total`, `resultTotal`, `num_found` and the like, a count
  beside a product list in the page's state), and the call that gave it. JSON answers now carry their total.
- **Terms of use.** The pages the home page links as its terms (by the link's words in several languages, or its
  address; not a privacy or cookie page), two at most where robots.txt allows, on the site or another host of its
  domain, its host looked up in DNS first (one with no public DNS is never asked). Their sentences on a pace (`每秒超过 2 次请求`, "1 request per second") and on robots, crawlers and
  scraping are quoted as written, and counted; the home page's own words too.
- **The watch clicks a listing's next page once,** by its markup (`rel=next`, an aria label, common pagination
  classes) or its words (`下一页`, Next, ›, Далі, Weiter, ...), never one leading to a cart or an account, and
  marks the calls after the click: a list paged by a script shows only then.
- **The watch can no longer hang.** On one shop the run waited 45 minutes for the body of an answer that never
  ended. Now a page has a bounded time, a body 10 s (60 s for a page's calls in all), and an answer still open is
  named as a stream or a long poll.
- **A monitoring endpoint is no API base.** Alibaba Cloud's real-user monitoring, named `endpoint` in an inline
  script (`*.log.aliyuncs.com/rum/`), was reported as one; Sensors Data, Baidu, CNZZ and GrowingIO are left out
  with it.
- **VAT in Chinese words:** `含增值税`, `含税`, `不含税`, `未税`.
- **Another host's robots.txt is followed through its redirects,** as RFC 9309 asks: an `http://` link's robots.txt
  that moved to `https://` had counted as unreadable, so the host as wholly disallowed. The routes line says how
  many JS bundles robots.txt kept out (all 29 of one shop's).

From the two runs after the above, on the same marketplace and on a single-page app:

- **A JS file the site does not give is not counted as read.** On the app, all 12 bundles answered 464 with no
  body, and the report said "12 read of 12 named" and "0 API routes", as if the code named none. Now the files
  not given are counted by their answer, and the verdict says the routes the site's JS names are not known. A
  host none of whose files was given is left after 3 in a row (9 requests fewer on the app).
- **A bundle is asked as Chrome asks a script:** `Accept: */*` rather than a page's, and the page that loads it
  as the Referer (its origin alone on another host, Chrome's default). Some static hosts give a file only to
  their own site's pages.
- **A page whose network never goes quiet is still read, scrolled and clicked.** The watch waited for the
  network to go quiet as part of loading the page; on the marketplace, whose pages poll, that wait timed out on
  both pages, and the scroll, the title and the next-page click never came. The report then gave the page's
  status as `-`, its title as `TimeoutError`, and said "no next-page control found", though none was looked for.
  Now the page is loaded to its DOM, given what is left of its 30 s to go quiet, and read as it stands; the
  report says which pages never went quiet. A page that breaks keeps the status its own answer had, and its
  click is said to be untried. Checked in Chrome on a local page that polls every 300 ms: before, `-`,
  `TimeoutError` and no click; now 200, its title, and page 2's list after the click.
- **协议 alone is no agreement.** It is a protocol too, and the marketplace's category of protocol chips was
  taken for its terms. Only a user's, a service's, a site's agreement (`用户协议`, `服务协议` and the like)
  counts now, and `法律声明` with them.
- **No more sitemaps guessed once every address gets one page.** The app answered all six guesses with its
  `index.html`; now the guess that gets the home page, or the page the guess before it got, is the last.
- **Where the time went:** each step's requests and seconds, in a table at the end of the report and in the
  JSON (`timing`). A run of 332 s showed only its total.
- The tests run across all cores (`pytest -n auto`, pytest-xdist in the `dev` extra, in CI too): 30 s, not
  3 min 48 s. The linear-time tests of hostile pages count CPU seconds, not the clock's, since a test across all
  cores waits its turn for one. The watch itself is tested now, against a stand-in for patchright.
- **Tencent EdgeOne is named** (`Server: TencentEdgeOne`, `EO-LOG-UUID`), as a CDN: on the marketplace it
  answered the http:// redirect, while the block its https:// page gave plain curl was Alibaba Cloud WAF's.
- 342 tests.

## 1.2.2 - 2026-10-25

From a run on an electronics marketplace on two hosts of one domain, behind Alibaba Cloud, whose scraper was then
built from routes recon had not found:

- **A redirect to another host of the same domain is followed.** The search host sent its home page to www, and
  recon stopped as at "another site"; four runs ended after one request. Now search.shop.com to www.shop.com is
  one site: the run goes on there, and the report says so.
- **A template's text is no link.** The first link was `/{{! firstPdfUrl}}`, a doT template left unrendered, and
  the deeper page, the clients' table, the not-found probe and the watch all asked it and met 404s. Hrefs holding
  `{{`, `{%`, `${`, `<%` are left out; a deeper page that did not answer is not watched.
- **The page given is watched, and judged by robots.txt.** Its robots.txt was `Disallow: /*?*`, so the watch had
  left out the search page it was given, the one page whose calls showed the API. The page given is now opened in
  Chrome whatever robots.txt says of it (recon read it already), and the verdict says when robots.txt disallows
  it, with the rule. The pages recon picks itself, and the calls asked again, still keep to robots.txt.
- **Product links on another host of the domain are named**, with the advice to run recon there for its product
  pages and sitemaps.
- **A guessed sitemap the site refuses is no refusal of the site.** A 405 on `/sitemap.xml.gz` had shown as
  "refused in other steps: sitemaps (1 blocked)".
- **Captchas and bot checks wired into the pages are named** though none fired: a GeeTest overlay
  (`gt_type=search_crawl`), NetEase Yidun, Alibaba Cloud's captcha, reCAPTCHA, hCaptcha, Turnstile, Arkose,
  FingerprintJS and webdriver checks, in the pages and the JS bundles. The level stays what the run met.
- **`/llms.txt` is read**: there or not, its size and first line.
- **Alibaba Cloud's captcha page is a challenge** (`aliyun_waf_aa` in its head, a slider to drag), as its
  `acw_sc__v2` page was; it had passed as a page. **A country refused by its CDN is said**
  (`X-Tengine-Error: denied by region_block`), with the advice to run from another: from such a country every
  client is turned away and the site looks closed.

## 1.2.1 - 2026-10-22

From a run on a Nuxt 3 shop behind Cloudflare whose data sits on an open JSON API on another host:

- **A listing is not a product page.** The run had sampled ten category pages as products: each carries a JSON-LD
  ItemList of ten Products, and recon read the first item as the page's own, then reported "mpn 0/10" and a false
  trap. A page that lists products is now told apart: an ItemList of Products, three or more Products side by
  side, a product list in its state with its counts beside it, a page number in its address or "Page 2 of" in
  its title. A listing is passed by the product step, left out of the sample (more links are read in its
  place, the products it links to first, and the rest of its family is skipped), and the not-found probe makes
  up a product, not a category. Once the product page is known, a page of another family that holds no product
  of its own (a maker's page) is left out of the sample too: on the shop it had kept the false trap alive.
  Links with a product's own word (`/product/`, `/products/`, `/p/`, `/item/`, `/dp/`) are tried before those with
  only a long number, and those under a listing's word (`/category/`, `/brands/`) last, so the deeper page is a
  product.
- **The API is looked for on every run, without a browser.** Before, only `--watch` looked, and a listing drawn
  on the server showed no XHR at all. Now each run reads:
  - the API bases the pages' runtime config names: Nuxt 3's `window.__NUXT__.config`, Nuxt 2's state,
    Next.js's `__NEXT_DATA__`, and `apiHost`, `API_URL`, `baseURL` style keys in inline scripts;
  - each API host in DNS. One with no public DNS, or a private address, is internal: named, and never asked.
    A public one is asked once, for its robots.txt, and the report names its server, its cookies, its CNAME and
    what stands in front of it, per host: an API host can sit behind another service than the site;
  - the JS bundles the home page, the product page and a listing load, and the chunks they name (30 files at
    most, 40 MB in all, each read up to 5 MB, paced as every request): the site's own only, on its host, on
    another host of its domain, or on the CDN its runtime config names (Nuxt's `cdnURL`, Next's
    `assetPrefix`), whose robots.txt is asked first, once. Another site's `/_nuxt/` is not read. A host is
    looked up in DNS before anything is asked of it: one with no public DNS, a private address or a name like
    `localhost` is named and never asked, not even its robots.txt. The API routes they name, with their
    methods, grouped as lists and search, detail, stock and price; and a helper that adds parameters to the
    calls, such as `addAntiSpiderParams`, with the parameters it sets, assigned or merged in
    (`Object.assign(e,{v:t,p:n})`, a spread). A name that only holds the word, as an analytics library's
    `checkIsAddSign`, is no helper;
  - the pages' state: Nuxt 3's `__NUXT_DATA__` (devalue, its wrappers, Sets, Maps and Dates read), Next.js's
    `__NEXT_DATA__` and `window.__INITIAL_STATE__`. The report gives each product list's key path, its size and
    the counts beside it (`resultTotal`, `pageSize`), and the product a product page is about. The listing read
    for it, and opened by the watch, is a page found to list products: one met on the way, else the product
    page's category links, its own (the deepest) first, two asked at most. The top of a category tree, with a
    few featured products and no counts, is not taken for one;
  - list or search routes, asked by GET with the plain client let in, no cookie or token, four requests at
    most, until one gives a product list: only routes the code calls by GET, with nothing to fill in, and none
    whose words name a change of state or a visitor's own data (`add`, `delete`, `cart`, `wish`, `user` and
    the like); those that name products first. They are asked on the site's own API base first (one on its
    domain, then one an `apiHost`, `API_URL` or `baseURL` style key names; a payment service's
    `paymentApiUrl` comes after), then on the other bases and the site itself until one answers other than
    404. A JSON answer that says the call failed is reported as an error message, not as data; one that says
    what it lacks (`Either cate_id or keyword is required`) is asked once more with a value the run has: the
    product page's part number as its search word, else the last number of a category page's address as its
    category id.

  The verdict opens with it, after the way in: the API base, what is in front of its host, the internal hosts,
  whether a plain client got a product list, data or an error message (with the value filled in, and what came
  back without it), and the routes; then the page state. A
  helper's parameters are said to be unneeded only when a product list came back without them. The section
  "The site's own API, without a browser" holds the rest.
- **The API's refusals are its own.** An API route's 401 (a key it wants) and a refusal by an API host or a
  CDN are reported with the API and do not keep the burst off: the burst rests on the site's own pages.
- **The watch runs by default** where patchright and Chrome are there; where they are not, the report says
  which is missing and the run goes on. `--no-watch` turns it off; `--watch` is still accepted and does
  nothing. A list the API step asked already is not asked again by the watch's replay, and an API host's own
  robots.txt decides what is asked of it.
- **A part number the page state holds counts.** The product data and the sample read the product in the
  page's state too (a part-number key such as `mpn`, `partNumber`, `pro_sno`, `std_pro_sno`), so "a part number
  in the page's words but not in its data" is no longer said of pages whose state holds it. The sample says how
  many pages had a field from the state only. The state's stock is a stock's own count (`stock`, `stock_num`),
  not a flag before it (`in_stock: 1`) or an order's step (`moq`, `mult`).
- **JSON is read from the body, not its Content-Type:** an API serving JSON as `text/html` is read as JSON
  (a BOM and an anti-XSSI prefix are skipped too), and the report says what type it came as.
- **Sitemaps:** `/sitemap-index.xml`, `/wp-sitemap.xml` and `/sitemap.xml.gz` are guessed too. Redirects on the
  site are followed (five at most, where robots.txt allows) and the chain is reported with its final status;
  a redirect to another site is named and not followed. A guess that moved into a folder and is not there is
  tried once more by its own name in that folder. Guesses not asked no longer count as files named. "Files read"
  counts the files that answered; the addresses asked, guesses and redirects among them, are said beside it.
- **`--long` tells the local link from the site.** At an answer lost, two neutral hosts are asked
  (`NEUTRAL_HOSTS`: Cloudflare's trace and Google's 204). When neither answers, this machine's link failed,
  not the site: the session waits 30 s at a time until one answers, within its minutes, and goes on; the
  report names the outage instead of "answers lost". A link that stays down cuts the session short, and the
  level says it is inconclusive.
- **Alibaba Cloud** is recognised: its WAF by the cookies `acw_tc`, `acw_sc__v2` and `cdn_sec_tc`, its
  `acw_sc__v2` JavaScript challenge (a challenge) and its 405 block page (blocked); its CDN by `EagleId`,
  `Via: ens-cache`, `Ali-Swift-*` headers, `Server: Tengine` beside them, and a `*.kunlun*.com` CNAME. The WAF
  counts as a guard, so no burst runs behind it: its cookies mean a security layer that bans an IP by its rate
  (CC protection) and serves the challenge. The CDN alone is no guard, as CloudFront and Fastly are not;
  `Server: Tengine` alone is any nginx fork's and names nothing.
- 275 tests.

## 1.2.0 - 2026-10-19

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
- **Does the API work without the browser?** Each product list the site's own
  API answered is asked once more with the plain client the site lets in, with
  no cookie and no token: three endpoints at most, each once, only where
  robots.txt allows. Calls that may change the site's state and GraphQL
  mutations are never asked. The report says whether the list came back as
  long. When it did not, the report says what the page sent beyond a browser's
  usual headers: `authorization`, `x-csrf-token`, `x-requested-with`, its
  cookies. It gives their names, never their values.
- 198 tests.

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

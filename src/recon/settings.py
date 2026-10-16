"""Every tunable of recon in one place: the clients and User-Agents it tries,
its pace, the sizes it reads, and the limits of the session test and the burst."""

from pathlib import Path

REPORTS = Path("recon-reports")  # in the working directory


NOTES_ENV = "RECON_NOTES"  # a folder of Markdown notes, when --notes is not given


CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


# The first one let in on every page is the way in, so the plainest come first.
# What the report calls each client: PHA is post_handshake_auth, Python's other TLS ClientHello;
# curl_cffi is libcurl sending a browser's TLS and HTTP/2 fingerprint
CLIENT_NAMES = {
    "httpx-h2": "httpx HTTP/2",
    "httpx-h1": "httpx HTTP/1.1",
    "httpx-h2-pha": "httpx HTTP/2 + PHA",
    "httpx-h1-pha": "httpx HTTP/1.1 + PHA",
    "curl-chrome": "curl_cffi as Chrome",
    "curl-safari": "curl_cffi as Safari",
    "curl-firefox": "curl_cffi as Firefox",
}
CLIENTS = (
    "httpx-h2",
    "httpx-h1",
    "httpx-h2-pha",
    "httpx-h1-pha",
    "curl-chrome",
    "curl-safari",
    "curl-firefox",
)


UAS = {
    "Chrome": CHROME_UA,
    "HeadlessChrome": CHROME_UA.replace("Chrome/", "HeadlessChrome/"),
    "empty": "",
    "python-requests": "python-requests/2.32.3",
    "python-httpx": "python-httpx/0.28.1",
    "Python-urllib": "Python-urllib/3.12",
    "curl CLI": "curl/8.9.1",
    "Wget": "Wget/1.24.5",
    "Scrapy": "Scrapy/2.11.2 (+https://scrapy.org)",
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "ClaudeBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0;"
    " +claudebot@anthropic.com)",
    "Bytespider": "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)",
    "AhrefsBot": "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
}


PAUSE = 0.5  # s between two requests outside the session test and the burst


TIMEOUT = 30


BODY_KEPT = 60_000_000  # bytes of an answer kept: a sitemap file may hold 50 MB


HEAD = 1_000_000  # bytes of a page read for markers and data; the parsing over it is linear
REQUEST_MOST = 90  # s for one request in all: httpx's timeout counts per read, and a server can trickle
SITEMAP_MOST = 60_000_000  # bytes a gzipped sitemap may unpack to (the protocol allows 50 MB)


REDIRECTS = 5


SITEMAP_FILES = 30
SITEMAP_FAILS_MOST = 5  # sitemap files in a row that do not answer: the rest are not asked
CRAWL_DELAY_MOST = 60.0  # s: robots.txt asking for more stops the run (unless --pause names a pace)


# where a sitemap is looked for when robots.txt names none: BigCommerce keeps it at /xmlsitemap.php
SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/xmlsitemap.php")


SAMPLE_URLS = 5000  # page addresses kept from the sitemaps


BROWSER_WAIT = 45  # s for the browser's page to stop being a challenge


BROWSER_SETTLE = 5  # s for cf_clearance once the real page shows


SESSION_PAGES = 12


SESSION_AT_ONCE = 4


LOCK_SHARE = 0.6  # with the jar under this share of the rate without it: a lock


STEPS = ((1, 20), (2, 30), (4, 50), (8, 100), (16, 150))  # (at a time, requests)


H1_MOST = 8


LOST_MAX = 2


SLOW_FACTOR = 3.0


SLOW_FLOOR = 1.0  # s: a slower median that is still under it is no slowdown


FAILED_SHARE = 0.1


# A 200 under this share of the smallest page of the first step (one at a time) has shrunk: a server failing
# quietly under load, as a PHP warning of 644 bytes in place of a 16 KB product page. SHRUNK_MAX of them in a
# step, and up to as many read alone, one at a time, to tell them from pages that small anyway
SHRUNK_SHARE = 0.5
SHRUNK_MAX = 2


RECOVER = 30


PRODUCT_TRIES = 2  # more product links read when the deeper page shows no product data


SAMPLE_PRODUCTS = 10  # product pages read for the data checks (--products)


STALE = 86_400  # s: a page older than this from a cache shows stock and prices that old


NONCE = "recon-x7q2"  # in made-up addresses


FAR_PAGE = 9999

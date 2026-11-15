"""A site's terms of use: the links its pages name as its terms, and the sentences there that speak of robots,
crawlers and scraping or of a pace in requests a second, quoted as written."""

import re
from typing import Any

from . import settings
from .pages import TAG, join, visible_text

# a link to the terms by its words or its address, in the shops' languages; a privacy or cookie page is not one.
# 协议 alone is a protocol as well as an agreement, and an electronics shop's categories are named by protocols
# (通信协议, 接口协议): only a user's, a service's or a site's agreement is its terms
TERMS_WORDS = re.compile(
    r"terms|conditions|agreement|\btos\b|nutzungsbedingungen|gesch[äa]ftsbedingungen|\bagb\b|\bcgv\b|\bcgu\b"
    r"|conditions[- _]g[ée]n[ée]rales|regulamin|warunki|t[ée]rminos|condiciones|termini|condizioni|voorwaarden"
    r"|podm[íi]nky|услови|соглашени|оферт|умови|угод"
    r"|(?:用户|用戶|服务|服務|注册|註冊|使用|会员|會員|网站|網站|平台|交易|购买|購買|销售|銷售)(?:协议|協議)"
    r"|条款|條款|法律声明|法律聲明|規約|약관",
    re.I,
)
PRIVACY = re.compile(r"privacy|cookie|datenschutz|конфіденц|конфиденц|隐私|隱私|プライバシー|개인정보", re.I)
ANCHOR = re.compile(r"""<a\b[^<>]*?\bhref\s*=\s*["']([^"']*)["'][^<>]*>""", re.I)

# a pace in so many requests a time, or a rate limit by name. A number starts where no digit stands before it and
# holds 9 digits at most: a page of a million digits is read in linear time, not tried at every one of them
N = r"(?<!\d)\d{1,9}"
RATE = re.compile(
    rf"{N}(?:[.,]\d{{1,3}})?\s*(?:requests?|calls?|queries|hits|page\s*views?|pages|times)\s*(?:per|/|a|an|each"
    r"|every|in\s+(?:a|one|any))\s*(?:second|sec|minute|min|hour|day)\b"
    r"|\brate[- ]limit"
    rf"|每(?:秒|秒钟|秒鐘|分钟|分鐘|小时|小時|天|日)[^。；;\d]{{0,30}}{N}\s*次|{N}\s*次\s*(?:/|每)\s*(?:秒|分钟|小时)"
    rf"|{N}\s*(?:Anfragen|Zugriffe|Aufrufe)\s*(?:pro|je|in\s+der)\s*(?:Sekunde|Minute|Stunde)"
    rf"|{N}\s*(?:запит\w*|запрос\w*|звернен\w*|обращени\w*)\s*(?:на|за|в)\s*(?:секунд\w*|хвилин\w*|минут\w*|годин\w*"
    r"|час\w*)"
    rf"|{N}\s*(?:requêtes|solicitudes|richieste)\s*(?:par|por|al|per)\s*(?:seconde|segundo|secondo|minute|minuto)",
    re.I,
)
# robots, crawlers, scraping and other automated access
BOTS = re.compile(
    r"\b(?:robots?|spiders?|crawl(?:er|ers|ing)?|scrap(?:e|er|ers|ing)|data[- ]mining|harvest(?:ing)?|bots?"
    r"|automated\s+(?:means|access|tools?|programs?|systems?|software|scripts?|queries|requests?))\b"
    r"|爬虫|爬蟲|抓取|采集|採集|自动化程序|自動化程式|机器人|機器人|蜘蛛"
    r"|\bautomatisiert\w*|\bCrawler\b|\bpars\w+|\bпарс\w+|\bскрап\w*|\bскрейп\w*|\bробот\w*"
    r"|\bавтоматизован\w*|\bавтоматизирован\w*|スクレイピング|クローラ|ロボット|크롤링|스크래핑",
    re.I,
)
# where a page's text breaks: a paragraph, a list item, a line
BREAK = re.compile(r"<(?:br|p|li|tr|/p|/li|/div|/h[1-6]|/tr|/td)\b[^<>]*>", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+|(?<=[。；！？;])|¶")


def terms_links(html: str, base: str) -> list[str]:
    """The addresses a page links as its terms of use: by the link's words first, then by its address alone; not a
    privacy or cookie page. Each once, in the order the page has them."""
    by_words: list[str] = []
    by_address: list[str] = []
    for m in ANCHOR.finditer(html):
        end = html.find("</a>", m.end(), m.end() + 300)
        words = " ".join(TAG.sub(" ", html[m.end() : end]).split()) if end >= 0 else ""
        url = join(base, m.group(1))
        if not url or not url.startswith(("http://", "https://")):
            continue
        if PRIVACY.search(words) or (PRIVACY.search(url) and not TERMS_WORDS.search(words)):
            continue
        if TERMS_WORDS.search(words):
            by_words.append(url)
        elif TERMS_WORDS.search(url.split("?", 1)[0]):
            by_address.append(url)
    return list(dict.fromkeys(by_words + by_address))


def quote(sentence: str, at: int) -> str:
    """A sentence as quoted: whole when short, else TERMS_QUOTE characters around what matched."""
    most = settings.TERMS_QUOTE
    if len(sentence) <= most:
        return sentence
    start = max(0, min(at - most // 3, len(sentence) - most))
    return ("…" if start else "") + sentence[start : start + most] + ("…" if start + most < len(sentence) else "")


def terms_said(html: str) -> dict[str, Any]:
    """The sentences of a page that name a pace ("rate") or robots, crawlers and scraping ("bots"): how many, and
    the first TERMS_QUOTES of each, as written. A sentence that names both counts as a pace."""
    text = visible_text(BREAK.sub(" ¶ ", html))
    rate: list[str] = []
    bots: list[str] = []
    for sentence in SENTENCE.split(text):
        sentence = sentence.strip(" ¶")
        if len(sentence) < 8:
            continue
        if m := RATE.search(sentence):
            rate.append(quote(sentence, m.start()))
        elif m := BOTS.search(sentence):
            bots.append(quote(sentence, m.start()))
    most = settings.TERMS_QUOTES
    return {"rate": rate[:most], "rate_count": len(rate), "bots": bots[:most], "bots_count": len(bots)}

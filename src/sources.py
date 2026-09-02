"""Source definitions and RSS ingestion.

Every source carries a `reuse` flag that decides how much of it we may
put in the digest:

  "open"  - government / public-domain content. We can summarise freely.
  "link"  - commercial publisher. Headline + our own short summary + link out.
            Never their sentences.

This is not decoration. summarize.py and telegram.py both read it.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import feedparser
import requests

# PIB returns 403 to anything that looks automated. A real browser string
# gets through. If it starts 403ing again, this is the line to change.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}


@dataclass
class Source:
    key: str
    name: str
    url: str
    category: str          # judgment | legislation | policy | opportunity
    reuse: str             # open | link
    weight: int = 0        # nudges the importance score


# Task 3 in the concept note settles this list.
#
# PRS has no RSS feed. Their content is CC BY 4.0, so scraping
# prsindia.org/billtrack is fine once someone writes that fetcher. Until
# then legislation news arrives via PIB and the publishers.
SOURCES: list[Source] = [
    Source("pib", "PIB", "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
           "policy", "open", weight=1),
    Source("rbi", "Reserve Bank of India", "https://www.rbi.org.in/pressreleases_rss.xml",
           "policy", "open", weight=1),
    Source("livelaw", "LiveLaw", "https://www.livelaw.in/feed",
           "judgment", "link", weight=1),
    Source("barandbench", "Bar & Bench", "https://www.barandbench.com/feed",
           "judgment", "link", weight=0),
    Source("scconline", "SCC Online Blog", "https://www.scconline.com/blog/feed/",
           "judgment", "link", weight=0),
    Source("lawctopus", "Lawctopus", "https://www.lawctopus.com/feed/",
           "opportunity", "link", weight=-1),
]


@dataclass
class Item:
    id: str
    source_key: str
    source_name: str
    reuse: str
    category: str
    title: str
    url: str
    published: datetime | None
    raw: str = ""
    weight: int = 0
    # filled in later by summarize.py
    what_happened: str = ""
    why_matters: str = ""
    provision: str | None = None
    importance: int = 0
    tags: list[str] = field(default_factory=list)
    deadline: date | None = None        # opportunities only
    related: str | None = None          # "connects to" an earlier item
    related_on: date | None = None
    matter: str | None = None           # canonical name of the underlying matter
    development: str | None = None      # this item's step, in a few words
    story_id: int | None = None
    thread: list = field(default_factory=list)   # [{on, development}]


def _canonical(url: str) -> str:
    """Strip tracking params so the same story doesn't arrive twice."""
    return url.split("?")[0].split("#")[0].rstrip("/").lower()


def item_id(url: str) -> str:
    return hashlib.sha1(_canonical(url).encode()).hexdigest()[:16]


def _parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if val:
            return datetime.fromtimestamp(time.mktime(val), tz=timezone.utc)
    return None


def fetch_source(src: Source, lookback_hours: int) -> list[Item]:
    """Pull one feed. Never raises - a dead feed must not kill the digest."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    try:
        resp = requests.get(src.url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] {src.key}: {type(exc).__name__}: {exc}")
        return []

    out: list[Item] = []
    skipped_old = 0
    for entry in feed.entries[:40]:
        url = getattr(entry, "link", "")
        title = (getattr(entry, "title", "") or "").strip()
        if not url or not title:
            continue

        published = _parse_date(entry)
        if published and published < cutoff:
            skipped_old += 1
            continue

        body = ""
        for key in ("summary", "description"):
            body = getattr(entry, key, "") or body
        if getattr(entry, "content", None):
            body = entry.content[0].get("value", body)

        out.append(Item(
            id=item_id(url),
            source_key=src.key,
            source_name=src.name,
            reuse=src.reuse,
            category=src.category,
            title=title,
            url=url,
            published=published,
            raw=strip_html(body)[:6000],
            weight=src.weight,
        ))
    note = f" ({skipped_old} older than cutoff)" if skipped_old else ""
    print(f"  {src.key}: {len(out)} items{note}")
    return out


def strip_html(html: str) -> str:
    """Crude tag stripper. We only need readable text for the model."""
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
                .replace("&quot;", '"'))
    return re.sub(r"[ \t]+", " ", text).strip()


def fetch_all(lookback_hours: int, sources: list[Source] | None = None) -> list[Item]:
    print("Fetching sources...")
    items: list[Item] = []
    seen: set[str] = set()
    for src in (sources or SOURCES):
        for item in fetch_source(src, lookback_hours):
            if item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
    print(f"Total fetched: {len(items)}")
    return items

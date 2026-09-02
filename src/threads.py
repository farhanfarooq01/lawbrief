"""Grouping items into ongoing stories.

The hard part is that the same matter is described differently every time it
appears. "SC to hear Places of Worship Act pleas" on Monday and "Centre files
counter-affidavit in Places of Worship challenge" three weeks later are the
same story, and nothing about the two strings matches exactly.

So the model gives each item a short canonical descriptor of the underlying
matter, and this module reduces that to significant tokens and matches on
overlap. Kept free of database and network calls so it can be tested directly.
"""
from __future__ import annotations

import re

# Words that appear in almost every Indian legal headline and therefore carry
# no signal about which matter is being described.
STOPWORDS = {
    "about", "after", "against", "and", "another", "before", "bench", "case",
    "challenge", "challenges", "court", "courts", "decision", "delhi", "for",
    "from", "hearing", "high", "india", "indian", "issue", "issues", "judge",
    "judges", "judgment", "justice", "matter", "order", "orders", "others",
    "petition", "petitions", "plea", "pleas", "proceedings", "ruling",
    "supreme", "that", "the", "their", "this", "union", "versus", "with",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(matter: str | None) -> list[str]:
    """Reduce a descriptor to the words that actually identify it.

    Keeps four-letter-and-longer words, plus any four-digit year, since a
    year is often the most distinguishing part of a statute's name.
    """
    if not matter:
        return []
    out: list[str] = []
    for word in _TOKEN.findall(matter.lower()):
        if word in STOPWORDS:
            continue
        if word.isdigit():
            if len(word) == 4:          # a year
                out.append(word)
            continue
        if len(word) >= 4:
            out.append(word)
    # Dedupe, preserving order.
    seen: set[str] = set()
    return [w for w in out if not (w in seen or seen.add(w))]


def overlap(a: list[str], b: list[str]) -> float:
    """Overlap coefficient, not Jaccard.

    Descriptors vary a lot in length - "Places of Worship Act challenge"
    against "constitutional validity of the Places of Worship Act 1991".
    Jaccard punishes that; the overlap coefficient does not.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / min(len(sa), len(sb))


def match_story(item_tokens: list[str], stories: list[dict],
                min_overlap: float = 0.6, min_shared: int = 2) -> dict | None:
    """Find the existing story an item belongs to, if any.

    Both thresholds must be met. Requiring two shared tokens on top of the
    ratio stops short descriptors matching each other on one common word.
    """
    if len(item_tokens) < 2:
        return None

    best: dict | None = None
    best_score = 0.0
    for story in stories:
        their = story.get("tokens") or []
        shared = len(set(item_tokens) & set(their))
        if shared < min_shared:
            continue
        score = overlap(item_tokens, their)
        if score >= min_overlap and score > best_score:
            best, best_score = story, score
    return best


def build_thread(events: list[dict], today, max_shown: int = 4) -> list[dict]:
    """Chronological events for display, oldest first, newest last.

    Trimmed to the most recent `max_shown` so a long-running matter does not
    swamp the digest. The earliest event is always kept, because where a
    story started is usually the most useful part of it.
    """
    ordered = sorted(
        [e for e in events if e.get("on")],
        key=lambda e: e["on"],
    )
    if len(ordered) <= max_shown:
        return ordered
    return [ordered[0], *ordered[-(max_shown - 1):]]

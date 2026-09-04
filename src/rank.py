"""Ranking.

Right now this is a placeholder built on the model's importance score plus a
few source weights. It stays a placeholder until task 2 in the concept note
comes back: a written definition of what makes an item worth a law student's
morning. Feed that definition into SYSTEM in summarize.py and the scoring
below stops guessing.
"""
from __future__ import annotations

from . import config
from .sources import Item

CATEGORY_BONUS = {
    "judgment": 1.0,
    "legislation": 1.0,
    "policy": 0.4,
    "profession": -0.5,     # firm moves rarely belong near the top
    "opportunity": 0.0,
}

# Words that reliably signal a big item. Crude, but better than pure recency.
SIGNALS = (
    "constitution bench", "constitutional validity", "struck down", "ultra vires",
    "supreme court holds", "landmark", "overrules", "full bench", "ordinance",
    "receives assent", "passed by parliament", "notified", "comes into force",
)


def score(item: Item) -> float:
    s = float(item.importance)
    s += CATEGORY_BONUS.get(item.category, 0.0)
    s += item.weight * 0.5

    blob = f"{item.title} {item.what_happened}".lower()
    if any(sig in blob for sig in SIGNALS):
        s += 1.0
    if item.provision:
        s += 0.3
    return s


def rank(items: list[Item], max_items: int, top_n: int) -> tuple[list[Item], list[Item]]:
    """Return (top, rest). `top` is Top Things to Know Today."""
    ordered = sorted(items, key=score, reverse=True)[:max_items]
    top = ordered[:top_n]

    # Neither opportunities nor firm news belong at the top, however loud
    # the headline. Top Things is for law that changed.
    top = [i for i in top if i.category not in ("opportunity", "profession")]
    rest = [i for i in ordered if i not in top]
    return top, rest


def attach_related(items, history: list[dict]) -> None:
    """Link each item to one earlier item on the same subject, if any.

    Matching is on a shared provision first, since that is the strongest
    signal two items concern the same point of law, then on overlapping
    subject tags. Pure logic, so it stays testable without a database.
    """
    if not history:
        return

    for item in items:
        best: dict | None = None

        if item.provision:
            for row in history:
                if row.get("provision") and row["provision"] == item.provision:
                    best = row
                    break

        if best is None and item.tags:
            mine = {t.lower() for t in item.tags}
            for row in history:
                theirs = {t.lower() for t in (row.get("tags") or [])}
                if len(mine & theirs) >= config.RELATED_MIN_TAGS:
                    best = row
                    break

        if best is not None:
            item.related = (best.get("what_happened") or best.get("title") or "")
            item.related_on = best.get("sent_on")


def spread_by_source(items, cap: int, per_source: int | None = None):
    """Choose which items to summarise, without letting one feed dominate.

    Taking the newest N is wrong when feeds publish at wildly different
    rates. Lawctopus posts twenty opportunities a day while the Supreme
    Court gives one judgment, so newest-first hands the whole digest to
    whoever is noisiest.

    Instead, take items round-robin across sources: the newest from each
    feed, then the second newest from each, and so on. A quiet feed still
    gets its item in.
    """
    if len(items) <= cap:
        return list(items)

    buckets: dict[str, list] = {}
    for item in items:
        buckets.setdefault(item.source_key, []).append(item)

    for group in buckets.values():
        group.sort(key=lambda i: (i.published is not None, i.published),
                   reverse=True)

    chosen = []
    round_n = 0
    while len(chosen) < cap:
        added = False
        for key in sorted(buckets):
            if per_source is not None and round_n >= per_source:
                continue
            group = buckets[key]
            if round_n < len(group):
                chosen.append(group[round_n])
                added = True
                if len(chosen) >= cap:
                    break
        if not added:
            break
        round_n += 1

    return chosen

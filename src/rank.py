"""Ranking.

Right now this is a placeholder built on the model's importance score plus a
few source weights. It stays a placeholder until task 2 in the concept note
comes back: a written definition of what makes an item worth a law student's
morning. Feed that definition into SYSTEM in summarize.py and the scoring
below stops guessing.
"""
from __future__ import annotations

from .sources import Item

CATEGORY_BONUS = {
    "judgment": 1.0,
    "legislation": 1.0,
    "policy": 0.4,
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

    # Opportunities never belong in Top Things, however loud the headline.
    top = [i for i in top if i.category != "opportunity"]
    rest = [i for i in ordered if i not in top]
    return top, rest

"""Tests that run on every push.

The provision tests are the point of this file. Everything else is here so
that a broken feed or a formatting change fails in CI instead of at 6:30am.
"""
from datetime import date

import pytest

from src import rank, telegram
from src.sources import Item, item_id, strip_html
from src.summarize import verify_provision


def make(**kw) -> Item:
    base = dict(
        id="x", source_key="pib", source_name="PIB", reuse="open",
        category="judgment", title="t", url="https://example.com/a",
        published=None, raw="", weight=0,
        what_happened="Something happened.", why_matters="It matters.",
        provision=None, importance=3,
    )
    base.update(kw)
    return Item(**base)


# --- the guard that matters -------------------------------------------------

def test_provision_kept_when_present_in_source():
    src = "The Court construed Section 109 of the Transfer of Property Act, 1882."
    assert verify_provision("Section 109, Transfer of Property Act, 1882", src) \
        == "Section 109, Transfer of Property Act, 1882"


def test_invented_provision_is_stripped():
    src = "The Court allowed the appeal and set aside the High Court order."
    assert verify_provision("Section 43B, Income Tax Act, 1961", src) is None


def test_partially_invented_provision_is_stripped():
    src = "The bench referred to Section 109 of the Act."
    # 1882 appears nowhere in the source, so the whole citation is untrusted.
    assert verify_provision("Section 109, Act of 1882", src) is None


def test_null_provision_stays_null():
    assert verify_provision(None, "anything") is None
    assert verify_provision("", "anything") is None


def test_provision_without_numbers_is_rejected():
    assert verify_provision("the Transfer of Property Act", "some text") is None


def test_article_citation_verified():
    src = "held to violate Article 21 of the Constitution"
    assert verify_provision("Article 21", src) == "Article 21"


# --- deduplication ----------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("https://livelaw.in/story-1", "https://livelaw.in/story-1?utm_source=rss"),
    ("https://livelaw.in/story-1", "https://livelaw.in/story-1/"),
    ("https://livelaw.in/story-1", "https://LiveLaw.in/Story-1#top"),
])
def test_same_story_gets_one_id(a, b):
    assert item_id(a) == item_id(b)


def test_different_stories_get_different_ids():
    assert item_id("https://x.com/a") != item_id("https://x.com/b")


# --- ranking ----------------------------------------------------------------

def test_top_is_ordered_by_score():
    items = [make(id=str(n), importance=n) for n in (1, 5, 3)]
    top, _ = rank.rank(items, max_items=10, top_n=2)
    assert [i.importance for i in top] == [5, 3]


def test_opportunities_never_reach_top():
    items = [
        make(id="a", category="opportunity", importance=5),
        make(id="b", category="judgment", importance=4),
    ]
    top, rest = rank.rank(items, max_items=10, top_n=1)
    assert all(i.category != "opportunity" for i in top)
    assert any(i.category == "opportunity" for i in rest)


def test_max_items_is_respected():
    items = [make(id=str(n)) for n in range(50)]
    top, rest = rank.rank(items, max_items=12, top_n=3)
    assert len(top) + len(rest) == 12


# --- formatting -------------------------------------------------------------

def test_no_message_exceeds_telegram_limit():
    items = [make(id=str(n), what_happened="A" * 300, why_matters="B" * 300)
             for n in range(40)]
    top, rest = rank.rank(items, max_items=40, top_n=4)
    for msg in telegram.build(top, rest, [], None, date(2026, 8, 31)):
        assert len(msg) <= 4096


def test_every_item_carries_its_source_link():
    item = make(url="https://prsindia.org/bill-42")
    assert "https://prsindia.org/bill-42" in telegram.render_item(item)
    assert "PIB" in telegram.render_item(item)


def test_missing_provision_prints_nothing_rather_than_guessing():
    assert "Turns on" not in telegram.render_item(make(provision=None))
    assert "Turns on" in telegram.render_item(make(provision="Article 21"))


def test_html_is_escaped():
    out = telegram.render_item(make(what_happened="Ram & Co <script>x</script>"))
    assert "<script>" not in out
    assert "&amp;" in out


def test_empty_why_matters_is_omitted():
    assert telegram.render_item(make(why_matters="")).count("\n") == 1


# --- html stripping ---------------------------------------------------------

def test_strip_html_removes_tags_and_entities():
    assert strip_html("<p>Hello &amp; <b>bye</b></p>").strip() == "Hello & bye"


def test_strip_html_drops_scripts():
    assert "alert" not in strip_html("<script>alert(1)</script><p>ok</p>")

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
        deadline=None, related=None, related_on=None,
        matter=None, development=None, story_id=None, thread=[],
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


def test_firm_news_never_reach_top():
    items = [
        make(id="a", category="firm", importance=5),
        make(id="b", category="judgment", importance=4),
    ]
    top, rest = rank.rank(items, max_items=10, top_n=1)
    assert all(i.category != "firm" for i in top)
    assert any(i.category == "firm" for i in rest)


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


# --- deadline countdowns -----------------------------------------------------

def test_countdown_phrasing():
    today = date(2026, 9, 3)
    assert "today" in telegram.countdown(date(2026, 9, 3), today)
    assert "tomorrow" in telegram.countdown(date(2026, 9, 4), today)
    assert "5 days" in telegram.countdown(date(2026, 9, 8), today)
    assert "Closes" in telegram.countdown(date(2026, 12, 1), today)


def test_past_deadline_renders_nothing():
    assert telegram.countdown(date(2026, 9, 1), date(2026, 9, 3)) == ""


def test_past_deadline_is_rejected_at_parse():
    from src.summarize import _parse_deadline
    assert _parse_deadline("2020-01-01") is None
    assert _parse_deadline("not a date") is None
    assert _parse_deadline(None) is None


def test_deadline_appears_in_item():
    item = make(category="opportunity", deadline=date.today())
    assert "Closes today" in telegram.render_item(item)


# --- header ------------------------------------------------------------------

def test_header_carries_greeting_and_counts():
    items = [make(id="a", category="judgment"), make(id="b", category="judgment"),
             make(id="c", category="opportunity")]
    top, rest = rank.rank(items, 10, 1)
    msg = telegram.build(top, rest, [], None, date(2026, 9, 3),
                         greeting_name="Roshansa")[0]
    assert "Good morning, Roshansa" in msg
    assert "3 items" in msg
    assert "2 judgments" in msg
    assert "1 opportunity" in msg      # singular


def test_greeting_can_be_switched_off():
    msg = telegram.build([make()], [], [], None, date(2026, 9, 3),
                         greeting_name="")[0]
    assert "Good morning" not in msg


def test_verdict_is_rendered_when_present():
    msg = telegram.build([make()], [], [], None, date(2026, 9, 3),
                         verdict="Quiet day.")[0]
    assert "Quiet day." in msg


# --- connects to -------------------------------------------------------------

def test_related_matches_on_shared_provision():
    item = make(provision="Article 21", tags=[])
    history = [{"what_happened": "Earlier ruling on privacy.",
                "title": "", "provision": "Article 21", "tags": [],
                "sent_on": date(2026, 8, 1)}]
    rank.attach_related([item], history)
    assert item.related == "Earlier ruling on privacy."


def test_related_matches_on_two_shared_tags():
    item = make(provision=None, tags=["criminal", "evidence"])
    history = [{"what_happened": "Earlier evidence ruling.", "title": "",
                "provision": None, "tags": ["criminal", "evidence", "bail"],
                "sent_on": date(2026, 8, 1)}]
    rank.attach_related([item], history)
    assert item.related == "Earlier evidence ruling."


def test_one_shared_tag_is_not_enough():
    item = make(provision=None, tags=["criminal"])
    history = [{"what_happened": "Unrelated.", "title": "", "provision": None,
                "tags": ["criminal"], "sent_on": date(2026, 8, 1)}]
    rank.attach_related([item], history)
    assert item.related is None


def test_empty_history_leaves_items_untouched():
    item = make(tags=["criminal", "evidence"])
    rank.attach_related([item], [])
    assert item.related is None


# --- story threading ---------------------------------------------------------

def test_tokens_drop_legal_filler():
    from src import threads
    got = threads.tokens("Supreme Court hearing on Places of Worship Act 1991")
    assert "places" in got and "worship" in got and "1991" in got
    assert "supreme" not in got and "court" not in got and "hearing" not in got


def test_tokens_keep_years_but_drop_other_numbers():
    from src import threads
    got = threads.tokens("Section 12 of the Evidence Act 1872")
    assert "1872" in got
    assert "12" not in got


def test_same_matter_worded_differently_still_matches():
    from src import threads
    a = threads.tokens("Places of Worship Act 1991 constitutional validity")
    b = threads.tokens("Supreme Court hears pleas against Places of Worship Act")
    assert threads.match_story(a, [{"id": 1, "tokens": b}]) is not None


def test_unrelated_matters_do_not_match():
    from src import threads
    a = threads.tokens("Places of Worship Act 1991 constitutional validity")
    b = threads.tokens("Vodafone retrospective taxation arbitration award")
    assert threads.match_story(a, [{"id": 1, "tokens": b}]) is None


def test_single_shared_word_is_not_a_match():
    from src import threads
    a = threads.tokens("Evidence Act electronic records certification")
    b = threads.tokens("Evidence gathering powers of investigating agencies")
    assert threads.match_story(a, [{"id": 1, "tokens": b}]) is None


def test_best_match_wins_when_several_are_close():
    from src import threads
    target = threads.tokens("Places of Worship Act 1991 constitutional validity")
    weak = threads.tokens("Places of pilgrimage access rules")
    strong = threads.tokens("Places of Worship Act 1991 hearing concluded")
    got = threads.match_story(target, [{"id": 1, "tokens": weak},
                                       {"id": 2, "tokens": strong}])
    assert got["id"] == 2


def test_thread_keeps_first_and_most_recent_events():
    from src import threads
    events = [{"on": date(2026, 1, n), "development": f"step {n}"}
              for n in range(1, 9)]
    got = threads.build_thread(events, date(2026, 1, 9), max_shown=4)
    assert len(got) == 4
    assert got[0]["development"] == "step 1"      # origin always kept
    assert got[-1]["development"] == "step 8"     # latest always kept


def test_short_thread_is_returned_whole():
    from src import threads
    events = [{"on": date(2026, 1, 1), "development": "a"},
              {"on": date(2026, 1, 2), "development": "b"}]
    assert len(threads.build_thread(events, date(2026, 1, 3))) == 2


def test_thread_renders_as_a_timeline():
    today = date(2026, 9, 3)
    item = make(thread=[
        {"on": date(2026, 6, 14), "development": "Notice issued to the Centre"},
        {"on": date(2026, 8, 12), "development": "Counter-affidavit filed"},
        {"on": today, "development": "Arguments concluded, judgment reserved"},
    ])
    out = telegram.render_item(item, today=today)
    assert "14 Jun" in out
    assert "Counter-affidavit filed" in out
    assert "Today" in out


def test_single_event_thread_is_not_rendered():
    today = date(2026, 9, 3)
    item = make(thread=[{"on": today, "development": "Only step"}])
    assert "Only step" not in telegram.render_item(item, today=today)


def test_thread_suppresses_the_weaker_connects_to_line():
    today = date(2026, 9, 3)
    item = make(related="Some earlier item", related_on=date(2026, 8, 1),
                thread=[{"on": date(2026, 8, 1), "development": "a"},
                        {"on": today, "development": "b"}])
    assert "Connects to" not in telegram.render_item(item, today=today)

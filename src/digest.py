"""Entry point. Run: python -m src.digest"""
from __future__ import annotations

import sys
from datetime import date

from . import config, rank, store, summarize, telegram, threads
from .sources import fetch_all


def attach_threads(conn, items, today) -> None:
    """Match each item to an ongoing story and load that story's timeline.

    Stories are created here rather than at save time so that an item's own
    step is already in the database when the thread is read back, which is
    what puts "Today" at the end of the timeline.
    """
    stories = store.load_stories(conn, today)

    for item in items:
        if not item.matter:
            continue
        toks = threads.tokens(item.matter)
        if len(toks) < 2:
            continue

        found = threads.match_story(toks, stories)
        if found:
            item.story_id = found["id"]
            store.touch_story(conn, found["id"], today)
        else:
            item.story_id = store.create_story(conn, item.matter, toks, today)
            stories.append({"id": item.story_id, "label": item.matter,
                            "tokens": toks})

    ids = sorted({i.story_id for i in items if i.story_id})
    if not ids:
        return

    events = store.story_events(conn, ids)
    for item in items:
        if not item.story_id:
            continue
        past = events.get(item.story_id, [])
        if not past:
            continue    # brand new story; nothing to show yet
        today_event = {"on": today,
                       "development": item.development or item.what_happened}
        item.thread = threads.build_thread(past + [today_event], today)


def main() -> int:
    today = date.today()
    print(f"=== Morning Brief · {today} ===")

    if not config.DRY_RUN:
        config.require_runtime()

    items = fetch_all(config.LOOKBACK_HOURS)
    if not items:
        print("Nothing fetched. Exiting without sending.")
        return 0

    conn = store.connect()
    store.init(conn)

    fresh = store.filter_new(conn, items)
    if not fresh:
        print("Nothing new today. Exiting without sending.")
        conn.close()
        return 0

    # Summarising takes minutes. Hold no connection across it: Neon drops
    # anything left idle, and reconnecting afterwards costs a second.
    conn.close()

    # Newest first, then cap. Summarising is the only step with a quota.
    fresh.sort(key=lambda i: (i.published is not None, i.published), reverse=True)
    if len(fresh) > config.PRE_SUMMARY_CAP:
        print(f"Capping {len(fresh)} -> {config.PRE_SUMMARY_CAP} before summarising.")
        fresh = fresh[:config.PRE_SUMMARY_CAP]

    fresh = summarize.summarize_all(fresh)
    top, rest = rank.rank(fresh, config.MAX_ITEMS, config.TOP_N)

    conn = store.connect()

    # Chain items into ongoing stories, then fall back to a looser
    # "connects to" for anything that isn't part of one.
    attach_threads(conn, top + rest, today)

    history = store.recent_notable(conn, today)
    rank.attach_related([i for i in top + rest if not i.thread], history)

    revision = store.due_for_revision(conn, today)
    case = store.case_of_the_day(conn, today)
    conn.close()

    print("Writing the day's verdict...")
    day_verdict = summarize.verdict(top + rest)

    messages = telegram.build(top, rest, revision, case, today,
                              verdict=day_verdict)
    telegram.send(messages, config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
                  dry_run=config.DRY_RUN)

    if not config.DRY_RUN:
        conn = store.connect()
        store.save_sent(conn, top + rest, today)
        store.advance_revision(conn, revision, today)
        conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Entry point. Run: python -m src.digest"""
from __future__ import annotations

import sys
from datetime import date

from . import config, rank, store, summarize, telegram
from .sources import fetch_all


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
        return 0

    # Newest first, then cap. Summarising is the only step with a quota.
    fresh.sort(key=lambda i: (i.published is not None, i.published), reverse=True)
    if len(fresh) > config.PRE_SUMMARY_CAP:
        print(f"Capping {len(fresh)} -> {config.PRE_SUMMARY_CAP} before summarising.")
        fresh = fresh[:config.PRE_SUMMARY_CAP]

    fresh = summarize.summarize_all(fresh)
    top, rest = rank.rank(fresh, config.MAX_ITEMS, config.TOP_N)

    revision = store.due_for_revision(conn, today)
    case = store.case_of_the_day(conn, today)

    messages = telegram.build(top, rest, revision, case, today)
    telegram.send(messages, config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
                  dry_run=config.DRY_RUN)

    if not config.DRY_RUN:
        store.save_sent(conn, top + rest, today)
        store.advance_revision(conn, revision, today)

    conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

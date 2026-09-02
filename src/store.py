"""Postgres: deduplication, revision queue, Case of the Day."""
from __future__ import annotations

import time
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

from . import config
from .sources import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    source_key    TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    category      TEXT,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published     TIMESTAMPTZ,
    what_happened TEXT,
    why_matters   TEXT,
    provision     TEXT,
    importance    INT DEFAULT 2,
    tags          TEXT[],
    sent_on       DATE,
    revisit_on    DATE,
    revisit_stage INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_revisit ON items (revisit_on)
    WHERE revisit_on IS NOT NULL;

CREATE TABLE IF NOT EXISTS cases (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    citation  TEXT,
    decided   TEXT,
    why       TEXT,
    last_used DATE
);
"""


def connect(attempts: int = 5):
    """Connect, retrying while the database wakes up.

    Neon's free tier suspends a project after a few minutes idle. The first
    connection after that is routinely refused or dropped mid-handshake while
    the compute spins back up, which takes a few seconds. This is normal
    rather than an error, so retry quietly before giving up.
    """
    last: Exception | None = None
    for n in range(attempts):
        try:
            return psycopg.connect(config.DATABASE_URL, row_factory=dict_row,
                                   connect_timeout=20)
        except psycopg.OperationalError as exc:
            last = exc
            if n == 0:
                print("  database asleep, waiting for it to wake...")
            time.sleep(3 * (n + 1))
    raise RuntimeError(
        f"could not reach the database after {attempts} attempts: {last}"
    )


def init(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def filter_new(conn, items: list[Item]) -> list[Item]:
    """Drop anything already sent. This is what stops repeats."""
    if not items:
        return []
    ids = [i.id for i in items]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM items WHERE id = ANY(%s)", (ids,))
        known = {r["id"] for r in cur.fetchall()}
    fresh = [i for i in items if i.id not in known]
    print(f"New after dedup: {len(fresh)} of {len(items)}")
    return fresh


def save_sent(conn, items: list[Item], today: date | None = None) -> None:
    today = today or date.today()
    first_gap = config.REVISIT_DAYS[0]
    with conn.cursor() as cur:
        for i in items:
            # Only items worth meeting again get queued for revision.
            revisit = today + timedelta(days=first_gap) if i.importance >= 3 else None
            cur.execute(
                """
                INSERT INTO items (id, source_key, source_name, category, title, url,
                                   published, what_happened, why_matters, provision,
                                   importance, tags, sent_on, revisit_on, revisit_stage)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
                ON CONFLICT (id) DO NOTHING
                """,
                (i.id, i.source_key, i.source_name, i.category, i.title, i.url,
                 i.published, i.what_happened, i.why_matters, i.provision,
                 i.importance, i.tags, today, revisit),
            )
    conn.commit()


def due_for_revision(conn, today: date | None = None, limit: int = 2) -> list[dict]:
    today = today or date.today()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM items
               WHERE revisit_on IS NOT NULL AND revisit_on <= %s
               ORDER BY importance DESC, revisit_on ASC LIMIT %s""",
            (today, limit),
        )
        return cur.fetchall()


def advance_revision(conn, rows: list[dict], today: date | None = None) -> None:
    """Move each resurfaced item to the next interval, or retire it."""
    today = today or date.today()
    with conn.cursor() as cur:
        for row in rows:
            stage = (row.get("revisit_stage") or 0) + 1
            if stage < len(config.REVISIT_DAYS):
                nxt = today + timedelta(days=config.REVISIT_DAYS[stage])
            else:
                nxt = None  # met it four times; it's yours now
            cur.execute(
                "UPDATE items SET revisit_on = %s, revisit_stage = %s WHERE id = %s",
                (nxt, stage, row["id"]),
            )
    conn.commit()


def case_of_the_day(conn, today: date | None = None) -> dict | None:
    """Least recently used case. Populated by task 5 in the concept note."""
    today = today or date.today()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM cases ORDER BY last_used NULLS FIRST, id ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE cases SET last_used = %s WHERE id = %s",
                        (today, row["id"]))
            conn.commit()
        return row

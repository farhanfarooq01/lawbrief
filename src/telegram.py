"""Compose and send the digest.

Layout notes, learned from reading it on a phone:

  - No leading-space indentation. Telegram wraps long lines and the wrapped
    portion loses the indent, so indented structure collapses exactly where
    it is needed most.
  - A rule under each section header, and an explicit end marker, so
    consecutive days do not run into each other in the channel.
  - Provision and source share one line. Vertical space is the scarce
    resource on a phone.

Telegram caps a message at 4096 characters, so build() returns a list of
chunks split on section boundaries.
"""
from __future__ import annotations

import html
import re
import time
from datetime import date

import requests

from . import config
from .sources import Item

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 3900  # under 4096, leaves room for entity overhead

RULE = "━━━━━━━━━━━━━━━━━━━━"

CATEGORY_TITLES = {
    "judgment": "⚖️ JUDGMENTS",
    "legislation": "📜 LEGISLATION &amp; BILLS",
    "policy": "🏛 POLICY &amp; REGULATION",
    "profession": "💼 THE PROFESSION",
    "opportunity": "🎓 OPPORTUNITIES",
}
ORDER = ["judgment", "legislation", "policy", "profession", "opportunity"]

COUNT_LABELS = {
    "judgment": ("judgment", "judgments"),
    "legislation": ("bill", "bills"),
    "policy": ("policy item", "policy items"),
    "profession": ("firm update", "firm updates"),
    "opportunity": ("opportunity", "opportunities"),
}

NUMERALS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]


def e(text: str) -> str:
    return html.escape(text or "", quote=False)


def _short_date(value: date) -> str:
    try:
        return value.strftime("%-d %b")
    except ValueError:              # Windows rejects %-d
        return value.strftime("%d %b").lstrip("0")


def _long_date(value: date) -> str:
    try:
        return value.strftime("%A, %-d %B %Y")
    except ValueError:
        return value.strftime("%A, %d %B %Y").replace(" 0", " ")


def countdown(deadline: date, today: date) -> str:
    """Human phrasing for how long is left. Empty if it has passed."""
    days = (deadline - today).days
    try:
        when = deadline.strftime("%-d %B")
    except ValueError:
        when = deadline.strftime("%d %B").lstrip("0")

    if days < 0:
        return ""
    if days == 0:
        return f"⏰ Closes today · {when}"
    if days == 1:
        return f"⏰ Closes tomorrow · {when}"
    if days <= 7:
        return f"⏰ Closes in {days} days · {when}"
    return f"Closes {when}"


def render_item(item: Item, bullet: str = "▸", today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"{bullet} <b>{e(item.what_happened)}</b>"]

    if item.why_matters:
        lines.append(e(item.why_matters))

    if item.thread and len(item.thread) >= 2:
        lines.append("")
        for n, event in enumerate(item.thread):
            last = n == len(item.thread) - 1
            mark = "🔹" if last else "▫️"
            when = "Today" if event["on"] == today else _short_date(event["on"])
            lines.append(f"{mark} <b>{e(when)}</b> — {e(event['development'])}")
        lines.append("")

    if item.related and not item.thread:
        seen = f" ({_short_date(item.related_on)})" if item.related_on else ""
        lines.append(f"↳ <i>Follows{e(seen)}:</i> {e(item.related[:110])}")

    # Provision, deadline and source share the last line where possible.
    tail: list[str] = []
    if item.provision:
        tail.append(f"<i>§ {e(item.provision)}</i>")
    if item.deadline:
        text = countdown(item.deadline, today)
        if text:
            tail.append(e(text))
    tail.append(f'<a href="{e(item.url)}">{e(item.source_name)}</a>')
    lines.append("  ·  ".join(tail))

    return "\n".join(lines)


def _counts_line(items: list[Item]) -> str:
    parts = []
    for cat in ORDER:
        n = sum(1 for i in items if i.category == cat)
        if not n:
            continue
        one, many = COUNT_LABELS[cat]
        parts.append(f"{n} {one if n == 1 else many}")
    return " · ".join(parts)


def _section(title: str, body_lines: list[str]) -> str:
    return "\n".join([f"<b>{title}</b>", RULE, "", *body_lines]).rstrip()


def build(top: list[Item], rest: list[Item],
          revision: list[dict] | None = None,
          case: dict | None = None,
          today: date | None = None,
          verdict: str = "",
          greeting_name: str | None = None) -> list[str]:
    today = today or date.today()
    if greeting_name is None:
        greeting_name = config.GREETING_NAME
    everything = list(top) + list(rest)

    blocks: list[str] = []

    # ---- header ----
    header = [RULE, "⚖️ <b>THE MORNING BRIEF</b>", f"<i>{_long_date(today)}</i>", RULE]
    if greeting_name:
        header.append(f"\nGood morning, {e(greeting_name)}.")
    counts = _counts_line(everything)
    if counts:
        header.append(f"<i>{len(everything)} items · {counts}</i>")
    if verdict:
        header.append(f"\n<blockquote>{e(verdict)}</blockquote>")
    blocks.append("\n".join(header))

    # ---- top things ----
    if top:
        body: list[str] = []
        for n, item in enumerate(top):
            marker = NUMERALS[n] if n < len(NUMERALS) else f"<b>{n + 1}.</b>"
            body.append(render_item(item, bullet=marker, today=today))
            body.append("")
        blocks.append(_section("★ TOP THINGS TO KNOW TODAY", body))

    # ---- by category ----
    for cat in ORDER:
        group = [i for i in rest if i.category == cat]
        if not group:
            continue
        if cat == "opportunity":
            group.sort(key=lambda i: (i.deadline is None, i.deadline or today))
        body = []
        for item in group:
            body.append(render_item(item, today=today))
            body.append("")
        blocks.append(_section(CATEGORY_TITLES[cat], body))

    # ---- case of the day ----
    if case:
        body = [f"<b>{e(case['name'])}</b>"]
        if case.get("citation"):
            body.append(f"<i>{e(case['citation'])}</i>")
        if case.get("decided"):
            body.append(f"\n{e(case['decided'])}")
        if case.get("why"):
            body.append(f"\n<i>Why it matters:</i> {e(case['why'])}")
        blocks.append(_section("📚 CASE OF THE DAY", body))

    # ---- revision ----
    if revision:
        body = ["<i>From your earlier reading.</i>", ""]
        for row in revision:
            body.append(f"▸ <b>{e(row['what_happened'] or row['title'])}</b>")
            tail = []
            if row.get("provision"):
                tail.append(f"<i>§ {e(row['provision'])}</i>")
            tail.append(f'<a href="{e(row["url"])}">{e(row["source_name"])}</a>')
            body.append("  ·  ".join(tail))
            body.append("")
        blocks.append(_section("🔁 WORTH REMEMBERING", body))

    # ---- end marker, so days don't run together in the channel ----
    blocks.append(f"{RULE}\n<i>End of brief · {_short_date(today)}</i>")

    return _pack(blocks)


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _split_block(block: str, limit: int) -> list[str]:
    """Break one oversized section on line boundaries.

    Never mid-line. Every tag we emit opens and closes within a single
    line, so a line boundary is always a safe cut, whereas slicing at a
    character count can land inside <b> and Telegram rejects the entire
    message with "Unclosed start tag".
    """
    out: list[str] = []
    buf = ""
    for line in block.split("\n"):
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) <= limit:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        # A single line over the limit should not happen, but if it does,
        # drop its markup rather than emit something unparseable.
        buf = line if len(line) <= limit else strip_tags(line)[:limit]
    if buf:
        out.append(buf)
    return out


def _pack(blocks: list[str]) -> list[str]:
    """Greedily fill messages up to LIMIT, splitting only between lines."""
    out: list[str] = []
    buf = ""
    for block in blocks:
        candidate = f"{buf}\n\n\n{block}" if buf else block
        if len(candidate) <= LIMIT:
            buf = candidate
            continue
        if buf:
            out.append(buf)
            buf = ""
        if len(block) <= LIMIT:
            buf = block
        else:
            pieces = _split_block(block, LIMIT)
            out.extend(pieces[:-1])
            buf = pieces[-1]
    if buf:
        out.append(buf)
    return out


def _post(token: str, chat_id: str, text: str, html_mode: bool = True):
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if html_mode:
        body["parse_mode"] = "HTML"
    return requests.post(API.format(token=token), json=body, timeout=30)


def send(messages: list[str], token: str, chat_id: str,
         dry_run: bool = False) -> int:
    """Send each message, returning how many got through.

    A malformed message is sent again as plain text rather than lost. One
    bad message must never cost the whole digest, which is what happened
    when this raised on the first failure.
    """
    if dry_run:
        for n, text in enumerate(messages, 1):
            print(f"\n----- message {n}/{len(messages)} "
                  f"({len(text)} chars) -----\n{text}\n")
        print("Dry run complete.")
        return len(messages)

    sent = 0
    for n, text in enumerate(messages, 1):
        resp = _post(token, chat_id, text)

        if resp.status_code == 400 and "parse" in resp.text.lower():
            print(f"  [warn] message {n} rejected as HTML; "
                  f"resending as plain text", flush=True)
            resp = _post(token, chat_id, strip_tags(text), html_mode=False)

        if resp.ok:
            sent += 1
        else:
            print(f"  [error] message {n} failed: "
                  f"{resp.status_code} {resp.text[:200]}", flush=True)

        time.sleep(1.2)  # channel rate limit is ~20 messages/minute

    print(f"Sent {sent} of {len(messages)} message(s).")
    return sent

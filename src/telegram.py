"""Compose and send the digest.

Telegram caps a message at 4096 characters, so build() returns a list of
chunks split on section boundaries. Task 6 in the concept note decides
whether that stays one long message or becomes several.
"""
from __future__ import annotations

import html
import time
from datetime import date

import requests

from . import config
from .sources import Item

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 3900  # under 4096, leaves room for entity overhead

CATEGORY_TITLES = {
    "judgment": "⚖️  JUDGMENTS",
    "legislation": "📜  LEGISLATION &amp; BILLS",
    "policy": "🏛  POLICY &amp; REGULATION",
    "firm": "🏢  LAW FIRMS &amp; DEALS",
    "opportunity": "🎓  OPPORTUNITIES",
}
ORDER = ["judgment", "legislation", "policy", "firm", "opportunity"]

# Singular/plural labels for the header count line.
COUNT_LABELS = {
    "judgment": ("judgment", "judgments"),
    "legislation": ("bill", "bills"),
    "policy": ("policy item", "policy items"),
    "firm": ("firm update", "firm updates"),
    "opportunity": ("opportunity", "opportunities"),
}


def e(text: str) -> str:
    return html.escape(text or "", quote=False)


def countdown(deadline: date, today: date) -> str:
    """Human phrasing for how long is left. Empty if it has passed."""
    days = (deadline - today).days
    try:
        when = deadline.strftime("%-d %B")
    except ValueError:          # Windows rejects %-d
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


def _short_date(value: date) -> str:
    try:
        return value.strftime("%-d %b")
    except ValueError:              # Windows rejects %-d
        return value.strftime("%d %b").lstrip("0")


def render_item(item: Item, bullet: str = "▸", today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"{bullet} <b>{e(item.what_happened)}</b>"]

    sub: list[str] = []
    if item.why_matters:
        sub.append(e(item.why_matters))

    if item.provision:
        sub.append(f"⚖️ <i>Turns on:</i> {e(item.provision)}")

    if item.deadline:
        text = countdown(item.deadline, today)
        if text:
            sub.append(e(text))

    if item.thread and len(item.thread) >= 2:
        thread_lines = []
        for n, event in enumerate(item.thread):
            last = n == len(item.thread) - 1
            mark = "●" if last else "◦"
            when = "Today" if event["on"] == today else _short_date(event["on"])
            thread_lines.append(f"{mark} <b>{e(when)}</b> — {e(event['development'])}")
        sub.append("\n".join(thread_lines))

    if item.related and not item.thread:
        seen = f" ({_short_date(item.related_on)})" if item.related_on else ""
        sub.append(f"↳ <i>Connects to{e(seen)}:</i> {e(item.related[:110])}")

    sub.append(f'<a href="{e(item.url)}">{e(item.source_name)}</a>')

    # Native blockquote gives an indented left border that wraps cleanly
    # on mobile phones without space indentation collapsing.
    body = "\n".join(sub)
    lines.append(f"<blockquote>{body}</blockquote>")
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

    # ---- header with clear day boundary ----
    try:
        nice_date = today.strftime("%A, %-d %B %Y")
    except ValueError:
        nice_date = today.strftime("%A, %d %B %Y").replace(" 0", " ")

    header = [
        "━━━━━━━━━━━━━━━━━━━━",
        "⚖️  <b>THE MORNING BRIEF</b>",
        f"📅  <i>{nice_date}</i>",
    ]
    if greeting_name:
        header.append(f"\nGood morning, {e(greeting_name)}.")
    counts = _counts_line(everything)
    if counts:
        header.append(f"📊  <i>{len(everything)} items · {counts}</i>")
    if verdict:
        header.append(f"\n💡  <i>{e(verdict)}</i>")
    header.append("━━━━━━━━━━━━━━━━━━━━")
    blocks.append("\n".join(header))

    # ---- top things ----
    if top:
        lines = ["★  <b>TOP THINGS TO KNOW TODAY</b>", ""]
        for n, item in enumerate(top, 1):
            lines.append(render_item(item, bullet=f"<b>{n}.</b>", today=today))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    # ---- by category ----
    for cat in ORDER:
        group = [i for i in rest if i.category == cat]
        if not group:
            continue
        if cat == "opportunity":
            # Soonest deadline first; undated ones last.
            group.sort(key=lambda i: (i.deadline is None, i.deadline or today))
        lines = [f"<b>{CATEGORY_TITLES[cat]}</b>", ""]
        for item in group:
            lines.append(render_item(item, today=today))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    # ---- case of the day ----
    if case:
        lines = ["📚  <b>CASE OF THE DAY</b>", "", f"<b>{e(case['name'])}</b>"]
        if case.get("citation"):
            lines.append(f"<i>{e(case['citation'])}</i>")
        if case.get("decided"):
            lines.append(f"\n{e(case['decided'])}")
        if case.get("why"):
            lines.append(f"\n<i>Why it matters:</i> {e(case['why'])}")
        blocks.append("\n".join(lines))

    # ---- revision ----
    if revision:
        lines = ["🔁  <b>WORTH REMEMBERING</b>",
                 "<i>From your earlier reading.</i>", ""]
        for row in revision:
            lines.append(f"▸ <b>{e(row['what_happened'] or row['title'])}</b>")
            rev_sub = []
            if row.get("provision"):
                rev_sub.append(f"⚖️ <i>Turns on:</i> {e(row['provision'])}")
            rev_sub.append(f'<a href="{e(row["url"])}">{e(row["source_name"])}</a>')
            lines.append(f"<blockquote>{chr(10).join(rev_sub)}</blockquote>")
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    # ---- day closing signoff ----
    blocks.append("━━━━━━━━━━━━━━━━━━━━\n✨  <i>End of Morning Brief. Have a productive day!</i>")

    return _pack(blocks)


def _pack(blocks: list[str]) -> list[str]:
    """Greedily fill messages up to LIMIT without splitting a block."""
    out: list[str] = []
    buf = ""
    for block in blocks:
        candidate = f"{buf}\n\n\n{block}" if buf else block
        if len(candidate) <= LIMIT:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            buf = block if len(block) <= LIMIT else block[:LIMIT]
    if buf:
        out.append(buf)
    return out


def send(messages: list[str], token: str, chat_id: str, dry_run: bool = False) -> None:
    for n, text in enumerate(messages, 1):
        if dry_run:
            print(f"\n----- message {n}/{len(messages)} "
                  f"({len(text)} chars) -----\n{text}\n")
            continue
        resp = requests.post(
            API.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        if not resp.ok:
            print(f"  [error] telegram {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
        time.sleep(1.2)  # channel rate limit is ~20 messages/minute
    print(f"Sent {len(messages)} message(s)." if not dry_run else "Dry run complete.")

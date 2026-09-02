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

from .sources import Item

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 3900  # under 4096, leaves room for entity overhead

CATEGORY_TITLES = {
    "judgment": "⚖️ JUDGMENTS",
    "legislation": "📜 LEGISLATION &amp; BILLS",
    "policy": "🏛 POLICY &amp; REGULATION",
    "opportunity": "🎓 OPPORTUNITIES",
}
ORDER = ["judgment", "legislation", "policy", "opportunity"]


def e(text: str) -> str:
    return html.escape(text or "", quote=False)


def render_item(item: Item, bullet: str = "▸") -> str:
    lines = [f"{bullet} <b>{e(item.what_happened)}</b>"]
    if item.why_matters:
        lines.append(f"   {e(item.why_matters)}")
    if item.provision:
        lines.append(f"   <i>Turns on:</i> {e(item.provision)}")
    lines.append(f'   <a href="{e(item.url)}">{e(item.source_name)}</a>')
    return "\n".join(lines)


def build(top: list[Item], rest: list[Item],
          revision: list[dict] | None = None,
          case: dict | None = None,
          today: date | None = None) -> list[str]:
    today = today or date.today()
    blocks: list[str] = []

    header = (f"<b>THE MORNING BRIEF</b>\n"
              f"<i>{today.strftime('%A, %d %B %Y')}</i>")
    blocks.append(header)

    if top:
        lines = ["<b>★ TOP THINGS TO KNOW TODAY</b>", ""]
        for n, item in enumerate(top, 1):
            lines.append(render_item(item, bullet=f"{n}."))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    for cat in ORDER:
        group = [i for i in rest if i.category == cat]
        if not group:
            continue
        lines = [f"<b>{CATEGORY_TITLES[cat]}</b>", ""]
        for item in group:
            lines.append(render_item(item))
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    if case:
        lines = ["<b>📚 CASE OF THE DAY</b>", "",
                 f"<b>{e(case['name'])}</b>"]
        if case.get("citation"):
            lines.append(f"<i>{e(case['citation'])}</i>")
        if case.get("decided"):
            lines.append(f"\n{e(case['decided'])}")
        if case.get("why"):
            lines.append(f"\n<i>Why it matters:</i> {e(case['why'])}")
        blocks.append("\n".join(lines))

    if revision:
        lines = ["<b>🔁 WORTH REMEMBERING</b>",
                 "<i>From your earlier reading.</i>", ""]
        for row in revision:
            lines.append(f"▸ <b>{e(row['what_happened'] or row['title'])}</b>")
            if row.get("provision"):
                lines.append(f"   <i>Turns on:</i> {e(row['provision'])}")
            lines.append(f'   <a href="{e(row["url"])}">{e(row["source_name"])}</a>')
            lines.append("")
        blocks.append("\n".join(lines).rstrip())

    return _pack(blocks)


def _pack(blocks: list[str]) -> list[str]:
    """Greedily fill messages up to LIMIT without splitting a block."""
    out: list[str] = []
    buf = ""
    for block in blocks:
        candidate = f"{buf}\n\n{block}" if buf else block
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

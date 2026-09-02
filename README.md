# The Morning Brief

A daily legal digest posted to Telegram every morning at 06:30 IST.

Concept: Roshansa B. Build: Farhan Farooq Raina.

Each item answers four things — what happened, why it matters, which provision
it turns on, and where to read it in full. Runs entirely on free
infrastructure.

---

## Setup

**1. Clone and install**

```bash
git clone <your-repo-url> && cd lawbrief
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Get four secrets**

| Secret | Where |
|---|---|
| `TELEGRAM_TOKEN` | Message `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | Create a channel, add the bot as admin, forward any channel post to `@userinfobot` |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key |
| `DATABASE_URL` | [neon.tech](https://neon.tech) → new project → connection string |

**3. Local run**

```bash
cp .env.example .env    # fill it in
DRY_RUN=1 python -m src.digest    # prints the digest instead of posting
python -m src.digest              # posts for real
```

**4. Deploy**

Push to GitHub, then add the same four values under
**Settings → Secrets and variables → Actions**. The workflow runs daily at
01:00 UTC and can be triggered by hand from the Actions tab.

Keep the repo **public** — Actions minutes are unlimited on public repos and
capped on private ones.

---

## Layout

```
src/sources.py     Feed definitions and RSS ingestion
src/summarize.py   Gemini call + the provision verification guard
src/rank.py        Importance scoring → Top Things to Know Today
src/store.py       Postgres: dedup, revision queue, Case of the Day
src/telegram.py    Message composition and sending
src/digest.py      Orchestrator — the thing cron runs
tests/             Runs on every push
seed_cases.py      Loads the Case of the Day list from a CSV
```

---

## The accuracy guard

The model is instructed to cite a provision **only if it appears verbatim in
the source text**. `verify_provision()` then checks that claim in code: it
pulls the numbers out of the citation and confirms each one occurs in the
article. If any doesn't, the provision is dropped and the item ships without
one.

This exists because a plausible-but-wrong section number is the single failure
this project cannot have. The tests in `tests/test_pipeline.py` cover it, and
CI blocks the daily send if they fail.

---

## Source handling

Each source in `sources.py` carries a `reuse` flag:

- `open` — government and public-domain material (PIB, PRS, RBI, India Code,
  Gazette). Summarise freely with attribution.
- `link` — commercial publishers (LiveLaw, Bar & Bench, Lawctopus). Headline,
  our own short summary, link out. Never their sentences.

Court judgments themselves are exempt under s.52(1)(q)(iv) of the Copyright
Act. Editorial matter around them — headnotes, copy-edited paragraph numbering —
is not.

---

## Open items

- **Feed URLs are unverified.** The six in `sources.py` are best guesses.
  Run `DRY_RUN=1 python -m src.digest` and check the `[warn]` lines; a feed
  that returns nothing needs its URL corrected.
- **Ranking is a placeholder.** It uses the model's own importance score. It
  gets real once there's a written definition of what makes an item worth a
  law student's morning (task 2).
- **Supreme Court / eSCR is not wired up.** RSS sources only for now.
- **`cases` table is empty** until `seed_cases.py` is run against the case list
  (task 5).
- **Check the Gemini model name** at ai.google.dev/gemini-api/docs/models
  before the first run. Free-tier model availability moves.

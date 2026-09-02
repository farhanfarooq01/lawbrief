"""Turn a fetched item into the four-line format, without inventing law.

The guard that matters is verify_provision(). The model is told to cite a
provision only if it appears in the source text; we then check that claim
in code and blank it if it doesn't hold. A wrong section number in a law
student's morning reading is the one failure this project cannot have.
"""
from __future__ import annotations

import json
import random
import re
import time

import requests

from . import config
from .sources import Item

# Auth via ?key= query param rather than the x-goog-api-key header. Newer
# AQ.-prefixed keys reject the header form with a 404.
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent?key={key}")

# Flipped to False the first time a model rejects thinkingConfig, so the
# rest of the run stops sending it. One-element list so the nested function
# can mutate it without a global statement.
_THINKING_OK = [True]

# Forces well-formed output. Without it the model occasionally returns JSON
# with a trailing comma or an unquoted key, which json.loads rejects.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "what_happened": {"type": "STRING"},
        "why_matters": {"type": "STRING"},
        "provision": {"type": "STRING", "nullable": True},
        "category": {"type": "STRING",
                     "enum": ["judgment", "legislation", "policy", "opportunity"]},
        "importance": {"type": "INTEGER"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["what_happened", "why_matters", "category", "importance"],
}

SYSTEM = """You summarise Indian legal and policy news for a law student.

Work ONLY from the source text you are given. You have no other knowledge of
this item. If the text does not say something, you do not know it.

Return a single JSON object, no markdown fences, with these keys:

  what_happened  One sentence. Plain, concrete, active. What was decided,
                 passed, issued or announced.
  why_matters    One sentence. The consequence. Who it affects and how.
                 If the source does not support a consequence, write "".
  provision      The statute section, article or case citation the item turns
                 on, EXACTLY as written in the source text (e.g. "Section 109,
                 Transfer of Property Act, 1882" or "Article 21"). If no
                 provision appears in the source text, use null. Never infer
                 one. Never recall one from memory.
  category       One of: judgment, legislation, policy, opportunity.
  importance     Integer 1-5. 5 = a Constitution Bench ruling, a new Act, or a
                 change that alters practice nationally. 3 = a significant but
                 narrow ruling or a Bill introduced. 1 = routine, procedural,
                 or a single listing.
  tags           Up to three lowercase subject tags, e.g. ["criminal",
                 "evidence"].

Be dry and specific. No hedging, no throat-clearing, no adjectives that carry
no information."""


def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    """One summarisation call, with backoff on rate limits and network drops.

    The free tier allows only a handful of requests per minute, so 429s are
    expected rather than exceptional. thinkingBudget is zeroed because 2.5
    models otherwise spend the output budget on internal reasoning and return
    truncated JSON.
    """
    gen_config = {
        "temperature": 0.2,
        "maxOutputTokens": 2000,
        "responseMimeType": "application/json",
        "responseSchema": RESPONSE_SCHEMA,
    }
    # Only the 2.x thinking models accept (and need) this. Lite and older
    # models reject it with a 400, so it is added conditionally and dropped
    # entirely on the first INVALID_ARGUMENT.
    if _THINKING_OK[0]:
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }

    last_exc: Exception | None = None
    for attempt in range(config.MAX_RETRIES):
        try:
            resp = requests.post(
                ENDPOINT.format(model=model, key=api_key),
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 0)) or \
                    (config.RETRY_BASE_WAIT * (2 ** attempt))
                wait += random.uniform(0, 1.5)
                print(f"    rate limited, waiting {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            if resp.status_code == 400 and _THINKING_OK[0]:
                # Almost always thinkingConfig on a model that lacks it.
                _THINKING_OK[0] = False
                print("    model rejects thinkingConfig; dropping it",
                      flush=True)
                gen_config.pop("thinkingConfig", None)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            wait = config.RETRY_BASE_WAIT * (2 ** attempt)
            # Never let the URL into a log line - it carries the API key.
            reason = type(exc).__name__
            resp_obj = getattr(exc, "response", None)
            if resp_obj is not None:
                # Body carries Google's actual complaint; the URL carries the key.
                detail = resp_obj.text.replace("\n", " ")[:200]
                reason = f"HTTP {resp_obj.status_code}: {detail}"
            print(f"    {reason}, retry {attempt + 1}/{config.MAX_RETRIES} "
                  f"in {wait:.0f}s", flush=True)
            time.sleep(wait)

    raise RuntimeError(
        f"gave up after {config.MAX_RETRIES} attempts"
        + (f" ({type(last_exc).__name__})" if last_exc else " (rate limited)")
    )


def _loads(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


_NUM = re.compile(r"\d+[A-Za-z]?")


def verify_provision(provision: str | None, source_text: str) -> str | None:
    """Keep the provision only if its numbers actually occur in the source.

    Catches the common failure where the model produces a plausible-looking
    "Section 43B" that appears nowhere in the article.
    """
    if not provision:
        return None
    nums = _NUM.findall(provision)
    if not nums:
        return None
    haystack = source_text.lower()
    if all(n.lower() in haystack for n in nums):
        return provision.strip()
    return None


def summarize(item: Item, api_key: str | None = None, model: str | None = None) -> Item:
    api_key = api_key or config.GEMINI_API_KEY
    model = model or config.GEMINI_MODEL

    source_text = f"HEADLINE: {item.title}\n\nSOURCE TEXT:\n{item.raw}".strip()

    try:
        parsed = _loads(_call_gemini(source_text, api_key, model))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).split("?key=")[0][:160]
        print(f"    [warn] {msg}", flush=True)
        item.what_happened = item.title
        item.why_matters = ""
        item.provision = None
        item.importance = 2
        return item

    item.what_happened = (parsed.get("what_happened") or item.title).strip()
    item.why_matters = (parsed.get("why_matters") or "").strip()
    item.provision = verify_provision(
        (parsed.get("provision") or "").strip() or None, source_text)
    item.category = parsed.get("category") or item.category
    item.tags = [t for t in (parsed.get("tags") or []) if isinstance(t, str)][:3]

    try:
        item.importance = max(1, min(5, int(parsed.get("importance", 2))))
    except (TypeError, ValueError):
        item.importance = 2

    return item


def summarize_all(items: list[Item]) -> list[Item]:
    """Paced so the free tier's per-minute cap isn't tripped on every run."""
    total = len(items)
    delay = config.REQUEST_DELAY
    print(f"Summarising {total} items (~{delay}s apart, "
          f"about {total * delay / 60:.0f} min)...")

    out: list[Item] = []
    for n, item in enumerate(items, 1):
        print(f"  [{n}/{total}] {item.source_key}: {item.title[:64]}", flush=True)
        out.append(summarize(item))
        if n < total:
            time.sleep(delay)
    return out

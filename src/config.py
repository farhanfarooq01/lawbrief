"""Central config. Everything comes from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


def _num(name: str, default: str, cast=int):
    """Read a numeric setting.

    GitHub passes an unset repository variable as an empty string rather
    than omitting it, so os.environ.get's default never fires. Treat empty
    and unparseable values as "use the default".
    """
    raw = (os.environ.get(name) or "").strip()
    try:
        return cast(raw) if raw else cast(default)
    except ValueError:
        print(f"  [warn] {name}={raw!r} is not a number; using {default}")
        return cast(default)


def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Check the current model list at ai.google.dev/gemini-api/docs/models
# before changing this. Free-tier availability moves around.
GEMINI_MODEL = (os.environ.get("GEMINI_MODEL") or "").strip() \
    or "gemini-flash-lite-latest"

# How many items make it into the digest at all.
MAX_ITEMS = _num("MAX_ITEMS", "18")
# How many get pulled up into "Top Things to Know Today".
TOP_N = _num("TOP_N", "4")
# Only look at items published within this window.
LOOKBACK_HOURS = _num("LOOKBACK_HOURS", "26")

# Summarising is the only rate-limited step. Cap how many items reach it, so
# a busy news day doesn't burn the day's quota on items that rank low anyway.
PRE_SUMMARY_CAP = _num("PRE_SUMMARY_CAP", "28")

# Seconds between LLM calls. The free tier allows roughly 10-15 requests per
# minute; 5s keeps a comfortable margin. Lower it if you move to a paid key.
REQUEST_DELAY = _num("REQUEST_DELAY", "12", float)
MAX_RETRIES = _num("MAX_RETRIES", "3")
RETRY_BASE_WAIT = _num("RETRY_BASE_WAIT", "8", float)

# Revision intervals, in days.
REVISIT_DAYS = [7, 30, 90]

DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def require_runtime():
    """Called by digest.py only. Tests import config without needing secrets."""
    _req("TELEGRAM_TOKEN")
    _req("TELEGRAM_CHAT_ID")
    _req("GEMINI_API_KEY")
    _req("DATABASE_URL")

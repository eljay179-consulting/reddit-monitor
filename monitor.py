"""
Watches multiple sets of subreddits for posts matching per-project keyword
lists, and writes a note per match into the PersonalKB vault's _inbox/
folder for manual review.

Each project (e.g. "readysetscholar", "sagp", "0x307") is an independent
watch defined in watches.json — its own subreddits, its own keywords. All
watches write into the same shared inbox, tagged with which project matched,
so they're filterable in Obsidian without needing separate vaults or paths.

This deliberately does NOT reply, post, vote, or otherwise act on Reddit —
it only reads and writes a local note. Every actual reply stays a manual,
human decision. For the readysetscholar watch specifically, see
docs/Marketing/Direct-Outreach-Plan.md in the wa-homeschool-path repo for
reply templates.

Each watch runs in its own thread against its own praw.Reddit instance (read
credentials are the same; separate instances avoid any shared-state concerns
between concurrent streams). A watch whose stream errors is retried with
backoff rather than taking down the other watches or the whole process.

Uses PRAW's submission stream, which handles pagination and de-duplication
of already-seen posts internally (skip_existing=True) — no separate
seen-ID file to maintain, per watch.
"""

import json
import os
import re
import sys
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import praw
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "reddit-monitor/1.0 (by u/change_me)"
)

VAULT_INBOX_PATH = Path(os.environ["VAULT_INBOX_PATH"])
WATCHES_CONFIG_PATH = Path(os.environ.get("WATCHES_CONFIG_PATH", "/app/watches.json"))

# Seconds to wait before restarting a watch's stream after it errors out.
# Backs off up to a cap rather than hammering Reddit on a sustained outage.
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 15 * 60


@dataclass
class Watch:
    name: str
    subreddits: str  # PRAW multireddit syntax, e.g. "homeschool+Homeschooling"
    keywords: list[str]


def load_watches() -> list[Watch]:
    data = json.loads(WATCHES_CONFIG_PATH.read_text(encoding="utf-8"))
    watches = [
        Watch(
            name=w["name"],
            subreddits=w["subreddits"],
            keywords=[k.strip().lower() for k in w["keywords"] if k.strip()],
        )
        for w in data["watches"]
    ]
    if not watches:
        raise ValueError(f"No watches defined in {WATCHES_CONFIG_PATH}")
    return watches


def matches_keywords(text: str, keywords: list[str]) -> list[str]:
    text = text.lower()
    return [kw for kw in keywords if kw in text]


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def write_inbox_note(watch: Watch, submission, matched_keywords: list[str]) -> None:
    VAULT_INBOX_PATH.mkdir(parents=True, exist_ok=True)

    created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
    timestamp = created.strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-reddit-{watch.name}-{slugify(submission.title)}.md"
    filepath = VAULT_INBOX_PATH / filename

    if filepath.exists():
        return

    body = (submission.selftext or "").strip()
    body_preview = (body[:500] + "…") if len(body) > 500 else body

    note = f"""---
tags: [reddit-lead, {watch.name}]
project: {watch.name}
source: reddit
subreddit: r/{submission.subreddit.display_name}
url: https://reddit.com{submission.permalink}
created: {created.isoformat()}
matched_keywords: [{", ".join(matched_keywords)}]
replied: false
---

# {submission.title}

**Project:** {watch.name} · **r/{submission.subreddit.display_name}** · [{submission.permalink}](https://reddit.com{submission.permalink})

{body_preview if body_preview else "*(link post, no self-text)*"}

---

Matched on: {", ".join(matched_keywords)}

Reply is manual — this note is only a heads-up.
"""
    filepath.write_text(note, encoding="utf-8")
    print(f"[{timestamp}] [{watch.name}] wrote inbox note: {filename}", flush=True)


def run_watch(watch: Watch) -> None:
    """Runs one watch's stream forever, restarting with backoff on error."""
    backoff = RETRY_BASE_SECONDS
    while True:
        try:
            reddit = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                user_agent=REDDIT_USER_AGENT,
            )
            reddit.read_only = True
            subreddit = reddit.subreddit(watch.subreddits)

            print(
                f"[{watch.name}] watching r/{watch.subreddits} for: "
                f"{', '.join(watch.keywords)}",
                flush=True,
            )
            backoff = RETRY_BASE_SECONDS  # reset after a clean (re)connect

            for submission in subreddit.stream.submissions(skip_existing=True):
                haystack = f"{submission.title}\n{submission.selftext or ''}"
                matched = matches_keywords(haystack, watch.keywords)
                if matched:
                    write_inbox_note(watch, submission, matched)

        except Exception:
            print(
                f"[{watch.name}] stream error, retrying in {backoff}s:\n"
                f"{traceback.format_exc()}",
                flush=True,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, RETRY_MAX_SECONDS)


def run() -> None:
    watches = load_watches()
    print(f"Loaded {len(watches)} watch(es) from {WATCHES_CONFIG_PATH}", flush=True)
    print(f"Writing matches to: {VAULT_INBOX_PATH}", flush=True)

    threads = [
        threading.Thread(target=run_watch, args=(watch,), name=watch.name, daemon=True)
        for watch in watches
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)

"""
Watches r/homeschool and r/Homeschooling for new posts matching keywords
relevant to ReadySetScholar's outreach (transcripts, GPA, college
applications, compliance questions), and writes a note per match into the
PersonalKB vault's _inbox/ folder for manual review.

This deliberately does NOT reply, post, vote, or otherwise act on Reddit —
it only reads and writes a local note. Every actual reply stays a manual,
human decision, per docs/Marketing/Direct-Outreach-Plan.md in the
wa-homeschool-path repo (skip auto-posting; every post is manual and
context-specific by design).

Uses PRAW's submission stream, which handles pagination and de-duplication
of already-seen posts internally (skip_existing=True) — no separate
seen-ID file to maintain.
"""

import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import praw
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "readysetscholar-outreach-monitor/1.0 (by u/change_me)"
)

SUBREDDITS = os.environ.get("SUBREDDITS", "homeschool+Homeschooling")
KEYWORDS = [
    k.strip().lower()
    for k in os.environ.get(
        "KEYWORDS",
        "transcript,gpa,college application,college applications,"
        "homeschool diploma,high school diploma,declaration of intent,"
        "homeschool affidavit,homeschool compliance,homeschool records",
    ).split(",")
    if k.strip()
]

VAULT_INBOX_PATH = Path(os.environ["VAULT_INBOX_PATH"])


def matches_keywords(text: str) -> list[str]:
    text = text.lower()
    return [kw for kw in KEYWORDS if kw in text]


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def write_inbox_note(submission, matched_keywords: list[str]) -> None:
    VAULT_INBOX_PATH.mkdir(parents=True, exist_ok=True)

    created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
    timestamp = created.strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-reddit-{slugify(submission.title)}.md"
    filepath = VAULT_INBOX_PATH / filename

    if filepath.exists():
        return

    body = (submission.selftext or "").strip()
    body_preview = (body[:500] + "…") if len(body) > 500 else body

    note = f"""---
tags: [reddit-lead, homeschool-outreach, readysetscholar]
source: reddit
subreddit: r/{submission.subreddit.display_name}
url: https://reddit.com{submission.permalink}
created: {created.isoformat()}
matched_keywords: [{", ".join(matched_keywords)}]
replied: false
---

# {submission.title}

**r/{submission.subreddit.display_name}** · [{submission.permalink}](https://reddit.com{submission.permalink})

{body_preview if body_preview else "*(link post, no self-text)*"}

---

Matched on: {", ".join(matched_keywords)}

See `docs/Marketing/Direct-Outreach-Plan.md` in wa-homeschool-path for reply
templates. Reply is manual — this note is only a heads-up.
"""
    filepath.write_text(note, encoding="utf-8")
    print(f"[{timestamp}] wrote inbox note: {filename}", flush=True)


def run() -> None:
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )
    reddit.read_only = True

    subreddit = reddit.subreddit(SUBREDDITS)
    print(
        f"Watching r/{SUBREDDITS} for keywords: {', '.join(KEYWORDS)}",
        flush=True,
    )
    print(f"Writing matches to: {VAULT_INBOX_PATH}", flush=True)

    for submission in subreddit.stream.submissions(skip_existing=True):
        haystack = f"{submission.title}\n{submission.selftext or ''}"
        matched = matches_keywords(haystack)
        if matched:
            write_inbox_note(submission, matched)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)

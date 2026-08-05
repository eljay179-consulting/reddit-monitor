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

DATA SOURCE: Reddit's public per-subreddit RSS feeds (e.g.
reddit.com/r/homeschool/new/.rss), not the official Data API. Reddit's 2026
Responsible Builder Policy gates real API access behind manual approval —
both the standard developer path and, separately, an explicit commercial-use
approval (this tool informs decisions for a paid product and a consulting
practice, so it's arguably commercial) — and small/independent projects are
described as frequently rejected either way. RSS is a long-standing, openly
documented Reddit feature rather than gated API surface, which is a more
defensible posture than hitting internal .json endpoints directly, but it is
still not a sanctioned integration: no SLA, no guarantee it keeps working,
and it should be treated as a genuine fallback, not a long-term foundation.
Polling stays deliberately infrequent (see POLL_INTERVAL_SECONDS) since the
actual use case is a periodic digest, not real-time alerting, and lower
volume is also simply more considerate of Reddit's infrastructure.

Each watch polls independently on its own thread and its own schedule. A
watch whose fetch fails is retried with backoff rather than taking down the
other watches or the whole process. Seen-post IDs persist to disk per watch
(SEEN_STATE_DIR) so a container restart doesn't re-notify on everything
currently in each feed.
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

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

USER_AGENT = os.environ.get("USER_AGENT", "reddit-monitor/1.0 (by u/change_me)")

VAULT_INBOX_PATH = Path(os.environ["VAULT_INBOX_PATH"])
WATCHES_CONFIG_PATH = Path(os.environ.get("WATCHES_CONFIG_PATH", "/app/watches.json"))
SEEN_STATE_DIR = Path(os.environ.get("SEEN_STATE_DIR", "/app/state"))

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", 2 * 60 * 60))  # 2h default
REQUEST_TIMEOUT_SECONDS = 20

# Seconds to wait before retrying a watch's poll after it errors out.
# Backs off up to a cap rather than hammering Reddit on a sustained outage.
RETRY_BASE_SECONDS = 60
RETRY_MAX_SECONDS = 30 * 60

# Seconds between starting each additional watch's thread, so simultaneous
# first-requests from multiple watches don't collide on Reddit's per-IP rate
# limit (empirically tight — see run_watch's docstring context above).
STARTUP_STAGGER_SECONDS = 20

# How many seen-post IDs to retain per watch. Reddit's per-subreddit RSS
# returns ~25 latest posts, so this comfortably covers the feed window with
# room to spare — not meant to be a long-term archive.
MAX_SEEN_IDS = 500


@dataclass
class Watch:
    name: str
    subreddits: str  # e.g. "homeschool+Homeschooling" — used to build the feed URL
    keywords: list[str]

    @property
    def feed_url(self) -> str:
        return f"https://www.reddit.com/r/{self.subreddits}/new/.rss"

    @property
    def seen_ids_path(self) -> Path:
        return SEEN_STATE_DIR / f"{self.name}.seen.json"


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


def load_seen_ids(watch: Watch) -> set[str]:
    if not watch.seen_ids_path.exists():
        return set()
    return set(json.loads(watch.seen_ids_path.read_text(encoding="utf-8")))


def save_seen_ids(watch: Watch, seen_ids: set[str]) -> None:
    SEEN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Trim rather than grow unboundedly — the feed window is small, so only
    # the most recently seen IDs matter for de-duplication.
    trimmed = list(seen_ids)[-MAX_SEEN_IDS:]
    watch.seen_ids_path.write_text(json.dumps(trimmed), encoding="utf-8")


def matches_keywords(text: str, keywords: list[str]) -> list[str]:
    text = text.lower()
    return [kw for kw in keywords if kw in text]


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def fetch_entries(watch: Watch) -> list:
    """Fetches and parses a watch's RSS feed. Raises on network/HTTP failure."""
    response = requests.get(
        watch.feed_url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    return parsed.entries


def write_inbox_note(watch: Watch, entry, matched_keywords: list[str]) -> None:
    VAULT_INBOX_PATH.mkdir(parents=True, exist_ok=True)

    created = datetime.now(timezone.utc)
    if getattr(entry, "published_parsed", None):
        created = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

    timestamp = created.strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}-reddit-{watch.name}-{slugify(entry.title)}.md"
    filepath = VAULT_INBOX_PATH / filename

    if filepath.exists():
        return

    # Reddit's RSS entry content is an HTML snippet (usually a thumbnail + a
    # link back to the post) rather than the plain self-text PRAW would have
    # given us. Strip tags for a readable preview rather than dumping raw HTML
    # into the note.
    raw_body = getattr(entry, "summary", "") or ""
    body = re.sub(r"<[^>]+>", " ", raw_body)
    body = re.sub(r"\s+", " ", body).strip()
    body_preview = (body[:500] + "…") if len(body) > 500 else body

    link = getattr(entry, "link", "")

    note = f"""---
tags: [reddit-lead, {watch.name}]
project: {watch.name}
source: reddit-rss
subreddit: r/{watch.subreddits}
url: {link}
created: {created.isoformat()}
matched_keywords: [{", ".join(matched_keywords)}]
replied: false
---

# {entry.title}

**Project:** {watch.name} · **r/{watch.subreddits}** · [{link}]({link})

{body_preview if body_preview else "*(no preview available)*"}

---

Matched on: {", ".join(matched_keywords)}

Reply is manual — this note is only a heads-up.
"""
    filepath.write_text(note, encoding="utf-8")
    print(f"[{timestamp}] [{watch.name}] wrote inbox note: {filename}", flush=True)


def poll_once(watch: Watch, seen_ids: set[str], first_run: bool) -> set[str]:
    entries = fetch_entries(watch)
    updated_seen_ids = set(seen_ids)

    for entry in entries:
        entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)
        if not entry_id or entry_id in seen_ids:
            continue

        updated_seen_ids.add(entry_id)

        # On the very first run there's no seen-state yet — every post in the
        # feed would look "new" and fire at once. Seed seen-state from the
        # first fetch instead of notifying on it, mirroring the intent of
        # PRAW's skip_existing=True from the earlier OAuth-based version.
        if first_run:
            continue

        haystack = f"{entry.title}\n{getattr(entry, 'summary', '')}"
        matched = matches_keywords(haystack, watch.keywords)
        if matched:
            write_inbox_note(watch, entry, matched)

    return updated_seen_ids


def run_watch(watch: Watch) -> None:
    """Polls one watch's RSS feed forever, retrying with backoff on error."""
    seen_ids = load_seen_ids(watch)
    first_run = not seen_ids
    backoff = RETRY_BASE_SECONDS

    print(
        f"[{watch.name}] polling {watch.feed_url} every {POLL_INTERVAL_SECONDS}s "
        f"for: {', '.join(watch.keywords)}",
        flush=True,
    )

    while True:
        try:
            seen_ids = poll_once(watch, seen_ids, first_run)
            save_seen_ids(watch, seen_ids)
            first_run = False
            backoff = RETRY_BASE_SECONDS  # reset after a clean poll
            time.sleep(POLL_INTERVAL_SECONDS)

        except Exception:
            print(
                f"[{watch.name}] poll error, retrying in {backoff}s:\n"
                f"{traceback.format_exc()}",
                flush=True,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, RETRY_MAX_SECONDS)


def run() -> None:
    watches = load_watches()
    print(f"Loaded {len(watches)} watch(es) from {WATCHES_CONFIG_PATH}", flush=True)
    print(f"Writing matches to: {VAULT_INBOX_PATH}", flush=True)
    print(f"Seen-state stored in: {SEEN_STATE_DIR}", flush=True)

    threads = [
        threading.Thread(target=run_watch, args=(watch,), name=watch.name, daemon=True)
        for watch in watches
    ]
    for i, t in enumerate(threads):
        # Reddit's unauthenticated rate limit turned out tighter than
        # expected in practice (a second request seconds after the first got
        # a 429; recovery took 30-50s). With one watch this never matters —
        # POLL_INTERVAL_SECONDS is hours. With several watches starting at
        # once, though, their first requests would all land in the same
        # instant. Staggering start times avoids that collision.
        if i > 0:
            time.sleep(STARTUP_STAGGER_SECONDS)
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)

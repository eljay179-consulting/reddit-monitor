# reddit-monitor

Watches multiple sets of subreddits — one independent "watch" per project (e.g. `readysetscholar`, `sagp`, `0x307`) — for posts matching that project's keywords, and writes a note per match into your PersonalKB vault's `_inbox/` folder for manual review.

**This does not post, reply, or vote on Reddit.** It only reads public posts and writes a local file. Every actual reply is a manual decision. For the `readysetscholar` watch specifically, see `docs/Marketing/Direct-Outreach-Plan.md` in the `wa-homeschool-path` repo for reply templates and the reasoning behind keeping this manual.

## Data source: RSS, not the official API

Reddit's 2026 Responsible Builder Policy gates real API access behind manual approval — both the standard developer path (`reddit.com/prefs/apps` now redirects to Devvit, which requires mod-installed presence on a specific subreddit, not a fit for watching communities you don't moderate) and, separately, an explicit commercial-use approval, since this tool arguably counts as commercial: it informs decisions for a paid product and a consulting practice, even though it takes no write actions on Reddit itself. Both paths were tried; neither is a reliable route for a small, independent tool like this.

Instead, this polls Reddit's plain per-subreddit RSS feeds (`reddit.com/r/homeschool/new/.rss`) — a long-standing, openly documented Reddit feature, which is a more defensible posture than hitting internal `.json` endpoints directly, but it is **not a sanctioned integration**. No SLA, no guarantee it keeps working, no recourse if Reddit changes or blocks it. Polling is deliberately infrequent (every 2 hours by default) since the actual use case is a periodic digest, not real-time alerting — lower request volume is both lower-risk and simply more considerate of Reddit's infrastructure.

If Reddit ever approves either access request, or the RSS approach stops working, `monitor.py` would need reworking again — this is a fallback, not a foundation to build more on top of without revisiting.

## 1. Configure

```bash
cp .env.example .env
cp watches.example.json watches.json
```

Edit `.env`:
- `USER_AGENT` — replace `change_me` with your Reddit username. No credentials to obtain — just a descriptive header so this isn't anonymous-looking traffic.
- `POLL_INTERVAL_SECONDS` — how often each watch checks its feed (default 7200 = 2 hours)
- `HOST_VAULT_INBOX_PATH` — the real filesystem path to your PersonalKB vault's `_inbox/` folder **on the machine running `docker compose`** (johnsonserve). This is bind-mounted into the container — get it wrong and notes will land somewhere you won't see them.

Edit `watches.json` — one entry per project:

```json
{
  "watches": [
    {
      "name": "readysetscholar",
      "subreddits": "homeschool+Homeschooling",
      "keywords": ["transcript", "gpa", "college application", "..."]
    },
    {
      "name": "sagp",
      "subreddits": "...",
      "keywords": ["...", "..."]
    }
  ]
}
```

`subreddits` uses Reddit's multi-subreddit URL syntax (`sub1+sub2`) — the watch builds its feed URL from this directly (`reddit.com/r/{subreddits}/new/.rss`).

Each watch runs independently (its own thread, its own poll schedule) — one project's feed erroring out doesn't affect the others. All watches write into the same `_inbox/`, tagged with `project: <name>` in the note's frontmatter so they're filterable in Obsidian.

`watches.json` is gitignored, like `.env` — edit it directly on johnsonserve, it isn't part of what gets deployed from git.

## 2. Deploy on johnsonserve

Copy this whole folder to johnsonserve (or see `DEPLOY.md` for the GitHub Actions auto-deploy setup), then:

```bash
docker compose up -d --build
```

Check it's running and watching:

```bash
docker compose logs -f
```

You should see, once per watch:
```
Loaded 1 watch(es) from /app/watches.json
Writing matches to: /vault-inbox
Seen-state stored in: /app/state
[readysetscholar] polling https://www.reddit.com/r/homeschool+Homeschooling/new/.rss every 7200s for: transcript, gpa, ...
```

On the very first run for a given watch, nothing gets written for whatever's already in the feed — it seeds its "seen" state instead of notifying on it, the same way the old PRAW-based version's `skip_existing=True` worked. Only genuinely new posts after that first poll produce a note.

## What happens on a match

A markdown note like `20260729-143022-reddit-readysetscholar-how-do-i-make-a-transcript.md` appears in `_inbox/`, with frontmatter (project, subreddit, URL, matched keywords, `replied: false`), the post title, and a preview of the post (RSS gives an HTML snippet, which is stripped down to plain text for the note).

## Adding a new project

1. Add an entry to `watches.json` (subreddits + keywords)
2. `docker compose restart` — config is read once at startup, so a restart (not a rebuild) picks up the change

## Stopping / updating

```bash
docker compose down          # stop
docker compose restart       # pick up a watches.json change
docker compose up -d --build # rebuild after editing monitor.py itself
```

## Notes on reliability

- Each watch keeps its own "seen post IDs" file (`/app/state/<name>.seen.json`, in a persistent Docker volume) so restarts don't re-notify on the whole current feed — only the RSS feed's own window (~25 latest posts) needs to be tracked, so this file stays small.
- Each watch's poll loop retries with exponential backoff (60s up to 30min) if a fetch fails, rather than crashing the whole process or the other watches.
- `restart: unless-stopped` in `docker-compose.yml` brings the container back if it crashes or the host reboots.
- This is explicitly not a sanctioned integration — see "Data source" above. Expect it to occasionally need attention if Reddit changes how RSS behaves for logged-out requests.

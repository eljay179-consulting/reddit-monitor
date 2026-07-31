# reddit-monitor

Watches multiple sets of subreddits — one independent "watch" per project (e.g. `readysetscholar`, `sagp`, `0x307`) — for posts matching that project's keywords, and writes a note per match into your PersonalKB vault's `_inbox/` folder for manual review.

**This does not post, reply, or vote on Reddit.** It only reads public posts and writes a local file. Every actual reply is a manual decision. For the `readysetscholar` watch specifically, see `docs/Marketing/Direct-Outreach-Plan.md` in the `wa-homeschool-path` repo for reply templates and the reasoning behind keeping this manual.

## 1. Get Reddit API access

As of 2026, this is no longer a two-minute self-serve step. `reddit.com/prefs/apps` now redirects to Devvit, Reddit's platform for apps that run hosted *inside* Reddit (installed onto a specific subreddit by that subreddit's moderators) — not a fit for an external read-only script watching subreddits you don't moderate.

For that, Reddit has a separate data-access-request form (search Reddit's help center for "Developer Platform Accessing Reddit Data" if the link below moves). Fill it in honestly and specifically — vague personal-project descriptions are the most commonly rejected:

- **What benefit will this have for Redditors?** Be honest that a read-only monitor with no posting/replying has no direct benefit to Redditors — the honest framing is that it helps you notice real questions promptly so you can reply personally and substantively, same as if you'd found the post by browsing.
- **What's missing from Devvit?** Devvit requires mod-installed presence on a specific community; this needs to watch subreddits you don't moderate, across multiple unrelated projects.
- **Link to source code:** this repo — https://github.com/eljay179-consulting/reddit-monitor
- **Subreddits:** whatever your current `watches.json` covers, plus a note that more will be added as new projects come up

Approval isn't guaranteed and there's no published turnaround time — expect anywhere from days to no response at all.

## 2. Configure

```bash
cp .env.example .env
cp watches.example.json watches.json
```

Edit `.env`:
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — from step 1, once approved
- `REDDIT_USER_AGENT` — replace `change_me` with your Reddit username (Reddit requires a descriptive, identifiable user agent)
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

Each watch runs independently (its own thread, its own Reddit stream) — one project's subreddits or keywords erroring out doesn't affect the others. All watches write into the same `_inbox/`, tagged with `project: <name>` in the note's frontmatter so they're filterable in Obsidian.

`watches.json` is gitignored, like `.env` — edit it directly on johnsonserve, it isn't part of what gets deployed from git.

## 3. Deploy on johnsonserve

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
[readysetscholar] watching r/homeschool+Homeschooling for: transcript, gpa, ...
```

## What happens on a match

A markdown note like `20260729-143022-reddit-readysetscholar-how-do-i-make-a-transcript.md` appears in `_inbox/`, with frontmatter (project, subreddit, URL, matched keywords, `replied: false`), the post title, a preview of the body.

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

- PRAW's submission stream (`subreddit.stream.submissions`) handles reconnection and skips duplicate posts on its own — no separate "seen posts" file to manage, per watch.
- Each watch's stream loop retries with exponential backoff (30s up to 15min) if it errors, rather than crashing the whole process or the other watches.
- `restart: unless-stopped` in `docker-compose.yml` brings the container back if it crashes or the host reboots.
- Runs read-only against Reddit's official API using approved access — not scraping unauthenticated endpoints.

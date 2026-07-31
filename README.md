# reddit-homeschool-monitor

Watches r/homeschool and r/Homeschooling for new posts matching keywords relevant to ReadySetScholar outreach (transcript, GPA, college applications, etc.) and writes a note per match into your PersonalKB vault's `_inbox/` folder for manual review.

**This does not post, reply, or vote on Reddit.** It only reads public posts and writes a local file. Every actual reply is a manual decision — see `docs/Marketing/Direct-Outreach-Plan.md` in the `wa-homeschool-path` repo for reply templates and the reasoning behind keeping this manual.

## 1. Create a Reddit API app

1. Go to https://www.reddit.com/prefs/apps
2. Click "create app" (or "create another app")
3. Type: **script**
4. Name: anything, e.g. `readysetscholar-outreach-monitor`
5. Redirect URI: `http://localhost` (required field, unused for script apps)
6. Click "create app"
7. Note the **client ID** (the string under the app name, not labeled) and the **secret**

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — from step 1
- `REDDIT_USER_AGENT` — replace `change_me` with your Reddit username (Reddit requires a descriptive, identifiable user agent)
- `HOST_VAULT_INBOX_PATH` — the real filesystem path to your PersonalKB vault's `_inbox/` folder **on the machine running `docker compose`** (johnsonserve). This is bind-mounted into the container — get it wrong and notes will land somewhere you won't see them.
- `KEYWORDS` / `SUBREDDITS` — adjust if you want to broaden/narrow what triggers a note

## 3. Deploy on johnsonserve

Copy this whole folder to johnsonserve, then:

```bash
docker compose up -d --build
```

Check it's running and watching:

```bash
docker compose logs -f
```

You should see:
```
Watching r/homeschool+Homeschooling for keywords: transcript, gpa, ...
Writing matches to: /vault-inbox
```

## What happens on a match

A markdown note like `20260729-143022-reddit-how-do-i-make-a-transcript.md` appears in `_inbox/`, with frontmatter (subreddit, URL, matched keywords, `replied: false`), the post title, a preview of the body, and a pointer back to the reply templates in the outreach plan doc.

## Stopping / updating

```bash
docker compose down          # stop
docker compose up -d --build # rebuild after editing monitor.py
```

## Notes on reliability

- PRAW's submission stream (`subreddit.stream.submissions`) handles reconnection and skips duplicate posts on its own — no separate "seen posts" file to manage.
- `restart: unless-stopped` in `docker-compose.yml` brings the container back if it crashes or the host reboots.
- Runs read-only against Reddit's official API using a registered app — not scraping unauthenticated endpoints, so it's within Reddit's terms at any reasonable polling behavior (PRAW handles Reddit's rate limits internally).

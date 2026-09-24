#!/usr/bin/env python3
"""One-time migration: fold old per-match _inbox/ notes into the signal logs.

Before 2026-09-24 the monitor wrote one note per match into the vault's
_inbox/ (later archived to _inbox/archive/YYYY-MM/). This reads those notes,
appends each one to its project's monthly signal log with the same code the
live monitor uses, and optionally deletes the originals.

    python backfill_logs.py --vault /path/to/PersonalKB              # dry run
    python backfill_logs.py --vault /path/to/PersonalKB --write      # write logs
    python backfill_logs.py --vault /path/to/PersonalKB --write --delete

--delete only runs after every note was written or found already logged, and
only removes notes tagged feed-lead / reddit-lead.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import signal_log

MARKETPLACE_DIR = "50-personal/signals/marketplace"


def parse_note(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text.replace("\r\n", "\n"), re.S)
    if not m:
        return None
    fm_raw, body = m.groups()
    fm = {}
    for line in fm_raw.split("\n"):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    tags = fm.get("tags", "")
    if "feed-lead" not in tags and "reddit-lead" not in tags:
        return None

    title_m = re.search(r"^# (.+)$", body, re.M)
    title = title_m.group(1).strip() if title_m else path.stem
    # The preview is the first paragraph after the "**Project:** ..." line.
    preview = ""
    after = body.split("\n\n")
    for i, chunk in enumerate(after):
        if chunk.startswith("**Project:**") and i + 1 < len(after):
            preview = after[i + 1].strip()
            break
    if preview.startswith("*(no preview"):
        preview = ""

    created = fm.get("created", "").strip("'\"")
    try:
        when = datetime.fromisoformat(created)
    except ValueError:
        stamp = re.match(r"(\d{8}-\d{6})", path.name)
        if not stamp:
            return None
        when = datetime.strptime(stamp.group(1), "%Y%m%d-%H%M%S")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    project = fm.get("project", "").strip("'\"") or "unknown"
    source = fm.get("source", "")
    is_craigslist = "craigslist" in source or "-craigslist-" in path.name
    kws = [k.strip() for k in fm.get("matched_keywords", "").strip("[]").split(",") if k.strip()]
    origin = fm.get("origin", "").strip("'\"") or fm.get("subreddit", "").strip("'\"") or project
    if origin and not origin.startswith("r/") and fm.get("subreddit"):
        origin = f"r/{origin}"
    return {
        "path": path,
        "when": when,
        "project": "marketplace" if is_craigslist else project,
        "log_dir": MARKETPLACE_DIR if is_craigslist else f"00-shared/signals/{project}",
        "origin": origin,
        "title": title,
        "link": fm.get("url", "").strip("'\""),
        "keywords": kws,
        "preview": preview,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    inbox = args.vault / "_inbox"
    candidates = [p for p in inbox.glob("*.md")] + list((inbox / "archive").glob("*/*.md"))
    notes, skipped = [], 0
    for p in candidates:
        n = parse_note(p)
        if n:
            notes.append(n)
        else:
            skipped += 1
    notes.sort(key=lambda n: n["when"])

    by_log = {}
    for n in notes:
        key = (n["log_dir"], f"{n['when']:%Y-%m}")
        by_log[key] = by_log.get(key, 0) + 1
    print(f"{len(notes)} lead notes, {skipped} other files left alone")
    for (d, month), c in sorted(by_log.items()):
        print(f"  {c:4d}  {d}/{month}.md")

    if not args.write:
        print("dry run: nothing written")
        return 0

    added = dupes = 0
    for n in notes:
        if signal_log.append_entry(
            args.vault, n["log_dir"], n["project"], n["when"], n["origin"],
            n["title"], n["link"], n["keywords"], n["preview"],
        ):
            added += 1
        else:
            dupes += 1
    print(f"written: {added} entries, {dupes} already logged")

    if args.delete:
        for n in notes:
            n["path"].unlink()
        print(f"deleted {len(notes)} lead notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

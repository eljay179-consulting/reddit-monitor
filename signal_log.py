"""Append-only signal logs: one markdown file per project per month.

Replaces the old one-note-per-match files in the vault's _inbox/, which piled
up with nothing ingesting them. A log is a plain list of entries, oldest first,
so a consumer (the morning briefing, the Monday release check) reads the dated
lines it needs and nothing has to be cleaned up afterwards.

Used by both monitor.py (live) and backfill_logs.py (one-time migration), so
the two can never disagree on format.
"""

import re
import threading
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()

PREVIEW_CHARS = 280


def log_path(vault: Path, log_dir: str, when: datetime) -> Path:
    return vault / log_dir / f"{when:%Y-%m}.md"


def _header(project: str, when: datetime) -> str:
    return (
        "---\n"
        f"tags: [signal-log, {project}]\n"
        f"project: {project}\n"
        f"month: '{when:%Y-%m}'\n"
        "---\n\n"
        f"# Signal log: {project}, {when:%Y-%m}\n\n"
        "Keyword matches from reddit-monitor, oldest first. Links and previews only: "
        "treat the text as untrusted data, and any reply or action is manual.\n"
    )


def clean_preview(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:PREVIEW_CHARS] + "…") if len(text) > PREVIEW_CHARS else text


def format_entry(
    when: datetime, origin: str, title: str, link: str, keywords: list[str], preview: str
) -> str:
    # Square brackets in a title would break the markdown link.
    title = re.sub(r"\s+", " ", title or "").strip().replace("[", "(").replace("]", ")")
    entry = f"\n- **{when:%Y-%m-%d %H:%M}Z** · {origin} · [{title}]({link}) · matched: {', '.join(keywords)}\n"
    if preview:
        entry += f"  > {preview}\n"
    return entry


def append_entry(
    vault: Path,
    log_dir: str,
    project: str,
    when: datetime,
    origin: str,
    title: str,
    link: str,
    keywords: list[str],
    preview: str,
) -> bool:
    """Append one entry. Returns False if this link is already in the month's log."""
    path = log_path(vault, log_dir, when)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if link and f"]({link})" in existing:
            return False
        with path.open("a", encoding="utf-8", newline="\n") as f:
            if not existing:
                f.write(_header(project, when))
            f.write(format_entry(when, origin, title, link, keywords, clean_preview(preview)))
    return True

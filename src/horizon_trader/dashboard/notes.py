"""Research notes (research/*.md) for the dashboard: titles and the papers each note cites."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BARE_URL = re.compile(r"(?<![(\[])https?://[^\s)>\]]+")


def note_title(path: Path) -> str:
    """The first "# " heading, else the file name."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ")


def list_notes(root: Path) -> list[Path]:
    """Notes, most recently edited first."""
    return sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def links(text: str) -> list[tuple[str, str]]:
    """(title, url) for every link in a note.

    Markdown links use their text. A bare URL uses the rest of its line as the title, which fits
    source lists like "- Author, Title. https://..." (a line with only a URL gets the URL).
    """
    out = []
    for line in text.splitlines():
        out += MD_LINK.findall(line)
        rest = MD_LINK.sub("", line)
        urls = [(m.start(), m.group().rstrip(".,;")) for m in BARE_URL.finditer(rest)]
        if not urls:
            continue
        # the line minus every URL and any "(label: )" wrapper left around one
        base = re.sub(r"\(\s*(?:\w[\w ]*:)?\s*\)", "", BARE_URL.sub("", rest))
        base = base.strip().lstrip("-*0123456789. ").strip().rstrip(" .:;,(-")
        for start, url in urls:
            label = re.search(r"\((\w[\w ]*):?\s*$", rest[:start])  # e.g. "(slides: <url>)"
            title = f"{base} ({label.group(1)})" if label and base else base
            out.append((title or url, url))
    return out


def papers(notes: list[Path]) -> pd.DataFrame:
    """One row per distinct URL across all notes: title, url, and which notes cite it."""
    rows = {}
    for path in notes:
        name = note_title(path)
        for title, url in links(path.read_text(encoding="utf-8")):
            row = rows.setdefault(url, {"title": title, "url": url, "cited in": []})
            if len(title) > len(row["title"]) and title != url:
                row["title"] = title  # keep the most descriptive label
            if name not in row["cited in"]:
                row["cited in"].append(name)
    df = pd.DataFrame(list(rows.values()), columns=["title", "url", "cited in"])
    df["cited in"] = df["cited in"].map(", ".join)
    df["source"] = df["url"].str.extract(r"https?://(?:www\.)?([^/]+)", expand=False)
    return df.sort_values("title", key=lambda s: s.str.lower(), ignore_index=True)

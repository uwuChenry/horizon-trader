"""Research notes (research/*.md) for the dashboard: titles and the papers each note cites."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

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
    return sorted(root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def local_links(path: Path, root: Path) -> list[tuple[str, Path]]:
    """Existing relative report/artifact links, confined to the research directory."""
    found = []
    for label, url in re.findall(
        r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")
    ):
        parts = urlsplit(url)
        if parts.scheme or parts.netloc or not parts.path:
            continue
        target = (path.parent / unquote(parts.path)).resolve()
        if target.is_relative_to(root.resolve()) and target.is_file():
            found.append((label, target))
    return found


def linked_markdown(path: Path, root: Path) -> str:
    """Make relative file links navigate to the Research viewer instead of a 404."""
    targets = {target for _, target in local_links(path, root)}

    def replace(match):
        label, url = match.groups()
        parts = urlsplit(url)
        target = (path.parent / unquote(parts.path)).resolve()
        if parts.scheme or parts.netloc or target not in targets:
            return match.group()
        note = target if target.suffix == ".md" else path
        route = "research?note=" + quote(note.relative_to(root.resolve()).as_posix(), safe="")
        if target.suffix != ".md":
            route += "&artifact=" + quote(target.relative_to(root.resolve()).as_posix(), safe="")
        fragment = urlsplit(url).fragment
        return f"[{label}]({route}" + (f"#{fragment}" if fragment else "") + ")"

    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", replace, path.read_text(encoding="utf-8"))


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

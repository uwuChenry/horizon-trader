"""Research studies (research/<slug>/), their documents, artifacts and the papers they cite."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from horizon_trader import config
from horizon_trader.dashboard import notes as N
from horizon_trader.dashboard.serialize import points, table
from horizon_trader.results import catalog as C
from horizon_trader.results import index as I

router = APIRouter(prefix="/api")
MEDIA = {
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".csv": "text/csv; charset=utf-8",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
    ".parquet": "application/octet-stream",
}


def research_root() -> Path:
    return (config.REPO_ROOT / "research").resolve()


def to_ref(path: Path) -> str:
    """A portable reference the frontend can hand back: research/... or data:..."""
    path = path.resolve()
    data = config.data_dir().resolve()
    if path.is_relative_to(research_root()):
        return path.relative_to(config.REPO_ROOT.resolve()).as_posix()
    if path.is_relative_to(data):
        return "data:" + path.relative_to(data).as_posix()
    raise ValueError(f"Not a research or data file: {path}")


def from_ref(ref: str) -> Path:
    """Resolve a reference, refusing anything outside research/ and the data directory."""
    if ref.startswith("data:"):
        base, rel = config.data_dir().resolve(), ref[5:]
    else:
        base, rel = research_root(), ref.removeprefix("research/")
    path = (base / rel).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() not in C.SUFFIXES:
        raise HTTPException(400, f"Not an allowed file: {ref}")
    if not path.is_file():
        raise HTTPException(404, f"No such file: {ref}")
    return path


def slug_of(result: C.Result) -> str:
    return result.source.parent.relative_to(research_root()).as_posix()


def summary(r: C.Result) -> dict:
    slug = slug_of(r)
    return {
        "id": r.id,
        "slug": slug,
        "parent": slug.rsplit("/", 1)[0] if "/" in slug else None,
        "name": r.name,
        "kind": r.kind,
        "status": r.status,
        "verdict": r.verdict,
        "tags": r.tags,
        "start": r.start,
        "end": r.end,
        "updated": r.metadata.get("updated", ""),
    }


def _studies() -> tuple[list[C.Result], list[str]]:
    return I.studies(config.REPO_ROOT)


@router.get("/studies")
def list_studies() -> dict:
    found, problems = _studies()
    rows = [summary(r) for r in found]
    children: dict[str, list[str]] = {}
    for row in rows:
        if row["parent"]:
            children.setdefault(row["parent"], []).append(row["slug"])
    for row in rows:
        row["children"] = children.get(row["slug"], [])
    return {"statuses": C.STATUSES, "studies": rows, "problems": problems}


@router.get("/studies/{slug:path}")
def study(slug: str) -> dict:
    found, _ = _studies()
    match = next((r for r in found if slug_of(r) == slug), None)
    if match is None:
        raise HTTPException(404, f"No study {slug}")
    folder = match.source.parent
    report = match.report
    docs = [
        {"ref": to_ref(p), "name": p.name, "title": N.note_title(p)}
        for p in sorted(folder.glob("*.md"))
        if p != report
    ]
    artifacts = [
        {
            "ref": to_ref(a.path),
            "label": a.label,
            "role": a.role,
            "suffix": a.path.suffix,
            "bytes": a.path.stat().st_size if a.path.exists() else None,
        }
        for a in match.artifacts
        if a.path.suffix != ".md" and a.path.name != "result.json"
    ]
    out = summary(match) | {
        "description": match.description,
        "code": match.metadata.get("code", []),
        "report": {
            "ref": to_ref(report),
            "markdown": report.read_text(encoding="utf-8"),
        }
        if report
        else None,
        "docs": docs,
        "artifacts": artifacts,
        "children": [summary(r) for r in found if slug_of(r).startswith(slug + "/")],
    }
    return out


@router.get("/doc")
def doc(ref: str = Query(...)) -> dict:
    """Any markdown file under research/, with the study it belongs to (for breadcrumbs)."""
    path = from_ref(ref)
    if path.suffix != ".md":
        raise HTTPException(400, "Not a markdown file")
    owner = next(
        (p for p in [path.parent, *path.parent.parents] if (p / "result.json").is_file()), None
    )
    slug = None
    if owner is not None and owner.is_relative_to(research_root()):
        slug = owner.relative_to(research_root()).as_posix()
    return {
        "ref": to_ref(path),
        "title": N.note_title(path),
        "markdown": path.read_text(encoding="utf-8"),
        "study": slug,
    }


@router.get("/files/table")
def file_table(ref: str = Query(...), limit: int = Query(2000, le=20000)) -> dict:
    path = from_ref(ref)
    try:
        frame = C.read_table(path)
    except Exception as exc:  # malformed evidence should not break the page
        raise HTTPException(422, f"Can't read {ref} as a table: {exc}") from exc
    return table(frame, limit=limit, index=not isinstance(frame.index, pd.RangeIndex))


@router.get("/files/equity")
def file_equity(ref: str = Query(...), limit: int = Query(12, le=40)) -> dict:
    path = from_ref(ref)
    try:
        curves = C.equity_curves(C.read_table(path))
    except Exception as exc:
        raise HTTPException(422, f"Can't chart {ref}: {exc}") from exc
    return {
        "series": [{"name": str(c), "points": points(curves[c])} for c in curves.columns[:limit]],
        "total": len(curves.columns),
    }


@router.get("/files/raw")
def file_raw(ref: str = Query(...)) -> FileResponse:
    path = from_ref(ref)
    return FileResponse(path, media_type=MEDIA.get(path.suffix, "application/octet-stream"))


@router.get("/papers")
def papers() -> dict:
    notes = N.list_notes(research_root())
    return table(N.papers(notes))

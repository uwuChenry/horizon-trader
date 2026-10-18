"""Versioned result manifests and read-only adapters for existing artifacts.

Paths in result.json are relative to that manifest; ``data:`` paths are relative
to HT_DATA_DIR. Discovery never rewrites or re-runs an experiment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from horizon_trader import config

SUFFIXES = {".csv", ".parquet", ".json", ".jsonl", ".md", ".html", ".xml", ".txt"}
KINDS = {"backtest", "research", "shadow", "paper", "live", "forward", "observations", "tests"}


@dataclass(frozen=True)
class Artifact:
    path: Path
    label: str
    role: str


@dataclass
class Result:
    id: str
    name: str
    kind: str
    source: Path
    artifacts: list[Artifact]
    description: str = ""
    start: str = ""
    end: str = ""
    bundle_id: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def updated(self) -> str:
        paths = [self.source, *(a.path for a in self.artifacts)]
        # A newly added catalog descriptor is not a newly executed experiment.
        paths = [p for p in paths if p.name != "result.json" and p.is_file()]
        stamp = max((p.stat().st_mtime for p in paths), default=self.source.stat().st_mtime)
        return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds")


def artifact_role(path: Path) -> str:
    name = path.stem.lower()
    if path.suffix == ".md":
        return "report"
    if "verification" in name or path.suffix == ".xml":
        return "verification"
    if path.suffix == ".html":
        return "chart"
    if "equity" in name or name == "daily" or name.endswith("_daily"):
        return "equity"
    if "drawdown" in name:
        return "drawdown"
    if "metric" in name or "summary" in name or "comparison" in name:
        return "metrics"
    if "trade" in name or "fill" in name or name == "orders":
        return "trades"
    if path.suffix in {".json", ".jsonl"}:
        return "metadata"
    return "table"


def _resolve(ref: str, parent: Path, data: Path) -> Path:
    """Resolve portable references; restrict downloads to result/data locations."""
    base = data if ref.startswith("data:") else parent
    relative = ref[5:] if ref.startswith("data:") else ref
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"Artifact escapes its root: {ref}")
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError(f"Unsupported artifact: {ref}")
    return path


def load_manifest(path: Path, data: Path) -> Result:
    info = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(info, dict):
        raise ValueError("Result manifest must be an object")
    if info.get("schema_version") != 1:
        raise ValueError("Unsupported result schema_version")
    if not all(isinstance(info.get(k), str) and info[k] for k in ["id", "name", "kind"]):
        raise ValueError("A result requires string id, name and kind")
    if info["kind"] not in KINDS:
        raise ValueError("A result requires id, name and a supported kind")
    if not isinstance(info.get("include", []), list) or not isinstance(
        info.get("artifacts", []), list
    ):
        raise ValueError("include and artifacts must be lists")
    artifacts: dict[Path, Artifact] = {}
    for pattern in info.get("include", []):
        if not isinstance(pattern, str):
            raise ValueError("Artifact patterns must be strings")
        base = data if pattern.startswith("data:") else path.parent
        glob = pattern[5:] if pattern.startswith("data:") else pattern
        if Path(glob).is_absolute() or ".." in Path(glob).parts:
            raise ValueError(f"Invalid artifact glob: {pattern}")
        for candidate in sorted(base.glob(glob)):
            if candidate.is_file() and candidate.suffix in SUFFIXES and candidate != path:
                ref = candidate.relative_to(base).as_posix()
                resolved = _resolve(("data:" if base == data else "") + ref, path.parent, data)
                artifacts[resolved] = Artifact(resolved, ref, artifact_role(resolved))
    for item in info.get("artifacts", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Each artifact requires a string path")
        resolved = _resolve(item["path"], path.parent, data)
        artifacts[resolved] = Artifact(
            resolved, item.get("label", item["path"]), item.get("role", artifact_role(resolved))
        )
    return Result(
        id=info["id"],
        name=info["name"],
        kind=info["kind"],
        source=path,
        artifacts=list(artifacts.values()),
        description=info.get("description", ""),
        start=info.get("start", ""),
        end=info.get("end", ""),
        bundle_id=info.get("bundle_id", ""),
        metadata=info,
    )


def write_manifest(path: Path, **info) -> None:
    """Publish a completed result descriptor atomically, after its artifacts exist."""
    payload = {"schema_version": 1, **info}
    if payload.get("kind") not in KINDS or not payload.get("id") or not payload.get("name"):
        raise ValueError("A result requires id, name and a supported kind")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _legacy_bundle(path: Path) -> Result:
    meta = json.loads(path.read_text(encoding="utf-8"))
    files = sorted(p for p in path.parent.rglob("*") if p.suffix in SUFFIXES and p.is_file())
    return Result(
        id=f"backtest:{path.parent.name}",
        name=meta.get("name", path.parent.name),
        kind="backtest",
        source=path,
        artifacts=[
            Artifact(p, p.relative_to(path.parent).as_posix(), artifact_role(p)) for p in files
        ],
        start=meta.get("start", ""),
        end=meta.get("end", ""),
        description=meta.get("strategy", ""),
        bundle_id=path.parent.name,
        metadata=meta,
    )


def discover(repo: Path | None = None, data: Path | None = None) -> tuple[list[Result], list[str]]:
    """One catalog for old bundles, v1 manifests and continually appended ledgers.

    Bad/partial files are reported without hiding the rest of the catalog.
    No table contents are loaded here except the small forward equity ledgers.
    """
    repo = (repo or config.REPO_ROOT).resolve()
    data = (data or config.data_dir()).resolve()
    records, issues = {}, []

    def add(load, path):
        try:
            record = load(path)
            if record.id in records:
                raise ValueError(f"Duplicate result id: {record.id}")
            records[record.id] = record
        except (OSError, ValueError, TypeError, KeyError) as exc:
            issues.append(f"{path}: {exc}")

    for root, pattern in [
        (repo / "research", "**/result.json"),
        (data / "results", "*/result.json"),
        (data / "checks", "*/result.json"),
    ]:
        for path in sorted(root.glob(pattern)):
            add(lambda p: load_manifest(p, data), path)
    for path in sorted((data / "results").glob("*/meta.json")):
        if path.parent / "result.json" not in {r.source for r in records.values()}:
            add(_legacy_bundle, path)
    for path in sorted((data / "live").glob("*/equity.csv")):

        def ledger(p):
            table = pd.read_csv(p)
            dates = pd.to_datetime(table["date"], errors="raise")
            name = p.parent.name
            kind = (
                "shadow"
                if name.endswith("_shadow")
                else "paper"
                if name.endswith("_paper")
                else "forward"
            )
            files = [f for f in sorted(p.parent.iterdir()) if f.suffix in SUFFIXES]
            return Result(
                id=f"{kind}:{name}",
                name=name.replace("_", " "),
                kind=kind,
                source=p,
                artifacts=[Artifact(f, f.name, artifact_role(f)) for f in files],
                start=str(dates.min().date()) if len(dates) else "",
                end=str(dates.max().date()) if len(dates) else "",
                description="Forward ledger. Fills are individual orders, not round-trip trades. "
                "Dividends are not credited by this ledger.",
            )

        add(ledger, path)
    observations = sorted((data / "live" / "observations").glob("*.jsonl"))
    if observations:
        records["observations:ibkr"] = Result(
            id="observations:ibkr",
            name="IBKR observations",
            kind="observations",
            source=observations[-1],
            start=observations[0].stem,
            end=observations[-1].stem,
            artifacts=[Artifact(p, p.name, "metadata") for p in reversed(observations)],
            description="Read-only connection, quote and account observations. "
            "A recorded session does not imply a successful connection or fill.",
        )
    return sorted(records.values(), key=lambda r: (r.updated, r.id), reverse=True), issues


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    return pd.read_csv(path)


def equity_curves(table: pd.DataFrame) -> pd.DataFrame:
    """Adapt indexed, wide and long equity tables without averaging configurations."""
    frame = table.copy()
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.rename_axis("date").reset_index()
    if "date" not in frame:
        raise ValueError("Equity table has no date column or date index")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if "equity" in frame:
        # These describe independent research paths, never additive account components.
        dimensions = [
            c
            for c in [
                "strategy",
                "capital",
                "variant",
                "exit_rule",
                "stop_atr",
                "risk_budget",
                "leverage_cap",
                "cost_case",
                "scenario",
                "restart",
            ]
            if c in frame
        ]
        if dimensions:
            labels = frame[dimensions].astype(str)
            frame["series"] = labels.apply(
                lambda row: " · ".join(f"{c}={row[c]}" for c in dimensions), axis=1
            )
            return frame.pivot(index="date", columns="series", values="equity").sort_index()
        if frame["date"].duplicated().any():
            raise ValueError("Duplicate dates: select one configuration before charting")
        return frame.set_index("date")[["equity"]].sort_index()
    curves = frame.set_index("date").select_dtypes("number")
    if curves.index.has_duplicates:
        raise ValueError("Duplicate dates: select one configuration before charting")
    return curves.sort_index()


def code_fingerprint(repo: Path | None = None) -> str:
    """Identify the code/config checked by a test run, including uncommitted edits."""
    repo = repo or config.REPO_ROOT
    paths = [
        p
        for directory in ["src", "tests", "config"]
        for p in (repo / directory).rglob("*")
        if p.suffix in {".py", ".yaml", ".json"} and p.is_file()
    ]
    paths += [p for p in [repo / "pyproject.toml", repo / "uv.lock"] if p.exists()]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(repo).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()

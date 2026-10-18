"""Run pytest and publish its actual exit status/evidence to the Results catalog.

python -m horizon_trader.results.check [pytest arguments]
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from horizon_trader import config
from horizon_trader.results.catalog import code_fingerprint, write_manifest


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {
        key: sum(int(s.get(key, 0)) for s in suites)
        for key in ["tests", "failures", "errors", "skipped"]
    }
    counts["passed"] = max(
        0, counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    )
    return counts


def main() -> int:
    started = datetime.now(UTC)
    run_id = f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    folder = config.data_dir() / "checks" / run_id
    folder.mkdir(parents=True)
    xml = folder / "pytest.xml"
    fingerprint = code_fingerprint()
    args = sys.argv[1:] or ["-q", "-p", "no:cacheprovider"]
    # This directory is new for each invocation, so pytest cannot clear another run's files.
    command = [
        sys.executable,
        "-m",
        "pytest",
        *args,
        f"--junitxml={xml}",
        f"--basetemp={folder / 'tmp'}",
    ]
    completed = subprocess.run(
        command,
        cwd=config.REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    output = completed.stdout
    print(output, end="")
    (folder / "output.txt").write_text(output, encoding="utf-8")
    counts = junit_counts(xml) if xml.exists() else {}
    finished = datetime.now(UTC)
    unchanged = fingerprint == code_fingerprint()
    status = "failed" if completed.returncode else "passed"
    if not unchanged:
        status = "code changed during tests"
    info = {
        "status": status,
        "exit_code": completed.returncode,
        "counts": counts,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "code_sha256": fingerprint,
        "code_unchanged_during_run": unchanged,
        "command": subprocess.list2cmdline(command),
    }
    (folder / "verification.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    write_manifest(
        folder / "result.json",
        id=f"tests:{run_id}",
        name=f"Pytest {finished:%Y-%m-%d %H:%M} UTC",
        kind="tests",
        start=started.date().isoformat(),
        end=finished.date().isoformat(),
        description="Software checks; the saved command records which tests were run.",
        include=["pytest.xml", "verification.json", "output.txt"],
        **info,
    )
    print(f"Saved test evidence: {folder}")
    return completed.returncode or (1 if not unchanged else 0)


if __name__ == "__main__":
    raise SystemExit(main())

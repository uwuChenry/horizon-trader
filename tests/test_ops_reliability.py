"""Checks added after 2026-11-10: ORB ledgers held overnight, failed steps, step timeouts."""

import json
import subprocess
from datetime import date

from horizon_trader.ops import health as H
from horizon_trader.ops import jobs as J

DAY = date(2026, 11, 10)


def test_flat_ledgers_flags_overnight_orb_holdings(tmp_path):
    for name, holdings in (("orb", {"FA": 48.0}), ("orb_alpaca_paper", {"FA": 0.0})):
        folder = tmp_path / "live" / name
        folder.mkdir(parents=True)
        (folder / "state.json").write_text(json.dumps({"cash": 1.0, "holdings": holdings}))
    rows = {r["name"]: r for r in H.flat_ledgers(tmp_path)}
    assert rows["orb flat"]["status"] == "bad" and "FA" in rows["orb flat"]["detail"]
    assert rows["orb_alpaca_paper flat"]["status"] == "ok"


def test_failed_steps_reads_todays_job_summaries(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"{DAY}-observe.log").write_text(
        "=== 09:24:10 observe\nTraceback ...\nobserve: exit 1 (22864.77s)\n=== 15:45:15 done\n"
    )
    (logs / f"{DAY}-evening.log").write_text("shadow: exit 0 (5.69s)\n")
    (logs / "2026-11-09-orb.log").write_text("orb (IBKR paper): exit 1 (9.08s)\n")  # other day
    row = H.failed_steps(tmp_path, DAY)
    assert row["status"] == "warn" and row["detail"] == "observe (exit 1)"
    (logs / f"{DAY}-observe.log").unlink()
    assert H.failed_steps(tmp_path, DAY)["status"] == "ok"


def test_ibkr_steps_have_timeouts_and_runner_receives_them():
    evening = {s.name: s for s in J.job_steps("evening", DAY)}
    assert evening["orb sync"].timeout == 900
    assert J.job_steps("options_log", DAY)[0].timeout == 3600
    assert J.job_steps("orb", DAY)[0].timeout is None  # the runner stays up all session


def test_timed_out_step_counts_as_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    seen = []

    def runner(command, **kwargs):
        seen.append(kwargs.get("timeout"))
        if kwargs.get("timeout"):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return 0

    monkeypatch.setattr(J, "_alpaca_enabled", lambda: False)
    assert J.run_job("evening", DAY, runner=runner) == 1
    assert 900 in seen
    log = (tmp_path / "logs" / f"{DAY}-orb.log").read_text()
    assert "orb sync failed: TimeoutExpired" in log

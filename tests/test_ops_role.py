"""HT_ROLE guard: only the ops machine sends orders or writes forward-test state."""

import sys

import pytest

from horizon_trader import config


@pytest.fixture
def research(monkeypatch):
    monkeypatch.delenv("HT_ROLE", raising=False)


def test_role_defaults_to_research(research):
    assert config.role() == "research"


def test_role_reads_env(monkeypatch):
    monkeypatch.setenv("HT_ROLE", " OPS ")
    assert config.role() == "ops"
    config.require_ops("anything")  # no raise


def test_bad_role_refuses(monkeypatch):
    monkeypatch.setenv("HT_ROLE", "prod")
    with pytest.raises(SystemExit, match="HT_ROLE must be"):
        config.role()


def test_require_ops_refuses_on_research(research):
    with pytest.raises(SystemExit, match="refusing to trade"):
        config.require_ops("trade")


def _main(monkeypatch, module, *argv):
    monkeypatch.setattr(sys, "argv", [module.__name__, *argv])
    module.main()


# Every one of these must stop at the guard, before touching a broker, Claude or the network.
GUARDED = [
    ("horizon_trader.run_daily", ["--mode", "shadow"]),
    ("horizon_trader.run_daily", ["--mode", "paper"]),
    ("horizon_trader.run_daily", ["--mode", "alpaca"]),
    ("horizon_trader.intraday.orb_live", ["run"]),
    ("horizon_trader.intraday.orb_live", ["sync"]),
    ("horizon_trader.agents.competition", ["run"]),
    ("horizon_trader.agents.journal", ["run"]),
    ("horizon_trader.agents.journal", ["score"]),
    ("horizon_trader.llm.fundamentals", ["export"]),
    ("horizon_trader.llm.fundamentals", ["run"]),
    ("horizon_trader.datasources.ibkr_options_log", ["capture"]),
    ("horizon_trader.intraday.scanner_log", ["capture"]),
    ("horizon_trader.execution.observe", ["--session"]),
]


@pytest.mark.parametrize(("name", "argv"), GUARDED, ids=[f"{n} {a[-1]}" for n, a in GUARDED])
def test_entry_points_refuse_on_research(research, monkeypatch, name, argv):
    import importlib

    module = importlib.import_module(name)
    with pytest.raises(SystemExit, match="refusing to"):
        _main(monkeypatch, module, *argv)


def test_dry_run_is_not_guarded(research, monkeypatch):
    from horizon_trader import run_daily

    calls = []
    monkeypatch.setattr(run_daily, "run", lambda cfg, mode: calls.append(mode))
    _main(monkeypatch, run_daily, "--dry-run")
    _main(monkeypatch, run_daily, "--mode", "what-if")
    assert calls == ["dry-run", "what-if"]


def test_ops_role_passes_the_guard(monkeypatch):
    from horizon_trader import run_daily

    monkeypatch.setenv("HT_ROLE", "ops")
    calls = []
    monkeypatch.setattr(run_daily, "run", lambda cfg, mode: calls.append(mode))
    _main(monkeypatch, run_daily, "--mode", "shadow")
    assert calls == ["shadow"]

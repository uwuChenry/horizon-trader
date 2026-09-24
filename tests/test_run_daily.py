import pandas as pd
import pytest

from horizon_trader.config import DEFAULT_CONFIG, load_settings
from horizon_trader.run_daily import run


def fake_fetch(symbols: list[str]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=5, freq="B")
    return pd.DataFrame({s: [100.0 + i for i in range(5)] for s in symbols}, index=idx)


def test_default_config_loads_and_allocations_fit():
    settings = load_settings(DEFAULT_CONFIG)
    assert sum(s.allocation for s in settings.sleeves.values()) <= 1.0


def test_dry_run_end_to_end_without_network():
    targets, orders = run(DEFAULT_CONFIG, dry_run=True, fetch=fake_fetch)
    assert targets.abs().sum() <= 1.0 + 1e-9
    assert orders and all(o.quantity > 0 for o in orders)  # from all-cash, everything is a buy


def test_live_mode_refuses_until_ibkr_adapter_exists():
    with pytest.raises(SystemExit):
        run(DEFAULT_CONFIG, dry_run=False, fetch=fake_fetch)

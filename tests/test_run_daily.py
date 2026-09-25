import pandas as pd
import pytest

from horizon_trader.config import DEFAULT_CONFIG, load_settings
from horizon_trader.run_daily import run
from horizon_trader.sleeves import build_sleeve

STATIC_CONFIG = """
universe: [SPY, IEF]
sleeves:
  core: {type: static, allocation: 0.9, params: {weights: {SPY: 0.6, IEF: 0.4}}}
risk: {max_weight: 0.6, max_gross: 1.0}
"""


def fake_fetch(symbols: list[str]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=5, freq="B")
    return pd.DataFrame({s: [100.0 + i for i in range(5)] for s in symbols}, index=idx)


@pytest.fixture
def static_config(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(STATIC_CONFIG)
    return path


def test_default_config_builds_every_sleeve():
    settings = load_settings(DEFAULT_CONFIG)
    assert sum(s.allocation for s in settings.sleeves.values()) <= 1.0
    for name, cfg in settings.sleeves.items():
        build_sleeve(name, cfg)


def test_dry_run_end_to_end_without_network(static_config):
    targets, orders = run(static_config, dry_run=True, fetch=fake_fetch)
    assert targets.abs().sum() == pytest.approx(0.9)
    assert orders and all(o.quantity > 0 for o in orders)  # from all-cash, everything is a buy


def test_live_mode_refuses_until_ibkr_adapter_exists(static_config):
    with pytest.raises(SystemExit):
        run(static_config, dry_run=False, fetch=fake_fetch)

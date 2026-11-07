import numpy as np
import pandas as pd
import pytest


def trend(daily_returns: list[float], start: float = 100.0) -> np.ndarray:
    return start * np.cumprod(1 + np.asarray(daily_returns))


@pytest.fixture
def random_prices() -> pd.DataFrame:
    """600 business days of seeded random walks for 5 tickers."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=600)
    rets = rng.normal(0.0004, 0.012, size=(len(idx), 5))
    return pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=list("ABCDE"))


ALERT_ENV = ("DISCORD_WEBHOOK_URL", "DISCORD_USER_ID", "NTFY_TOPIC", "NTFY_URL")


@pytest.fixture(autouse=True)
def _no_real_alerts(monkeypatch):
    """The ops machine's .env holds real alert channels and deploy runs pytest there: no test
    may post to them. Tests that need a channel set a fake one themselves."""
    for key in ALERT_ENV:
        monkeypatch.delenv(key, raising=False)

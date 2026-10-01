import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import ema_vwap as E


def _blocks(values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(values, index=pd.bdate_range("2026-03-02", periods=values.shape[0]))


def test_ema_carries_across_days_and_is_causal():
    rng = np.random.default_rng(0)
    close = _blocks(100 + np.cumsum(rng.normal(0, 0.1, (5, 78)), axis=1))
    ema = E.ema_across_days(close, 12)
    flat = close.stack().ewm(span=12, adjust=False).mean().unstack()
    pd.testing.assert_frame_equal(ema, flat, check_names=False)
    cut = close.copy()
    cut.iloc[3:] = np.nan  # the future (days 3-4) doesn't change days 0-2
    pd.testing.assert_frame_equal(E.ema_across_days(cut, 12).iloc[:3], ema.iloc[:3])


def test_session_vwap_uses_ohlc4_and_resets_each_day():
    o = _blocks(np.array([[10.0, 12.0], [20.0, 20.0]]))
    vol = pd.DataFrame([[1.0, 3.0], [1.0, 3.0]], index=o.index, columns=o.columns)
    b = {"open": o, "high": o + 1, "low": o - 1, "close": o, "volume": vol}
    v = E.session_vwap(b)
    assert v.iloc[0, 0] == pytest.approx(10.0)  # (10 + 11 + 9 + 10) / 4
    assert v.iloc[0, 1] == pytest.approx((10 * 1 + 12 * 3) / 4)
    assert v.iloc[1, 0] == pytest.approx(20.0)  # day 2 starts fresh


def test_targets_long_only_is_flat_where_sar_is_short():
    close = _blocks(np.array([[10.0, 11.0, 12.0, 9.0, 8.0, 8.5]]))
    b = {"close": close, "open": close, "high": close, "low": close, "volume": close * 0 + 1}
    sar, long_ = E.targets(b, "E12 SAR"), E.targets(b, "E12 LONG")
    assert set(np.unique(sar.to_numpy())) <= {-1, 0, 1}
    assert ((sar.to_numpy() == -1) == ((long_.to_numpy() == 0) & (sar.to_numpy() != 0))).all()
    assert (long_.to_numpy()[sar.to_numpy() == 1] == 1).all()
